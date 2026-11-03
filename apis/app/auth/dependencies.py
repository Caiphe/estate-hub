import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from fastapi import Depends, Request, Security
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.events import AuditEventCode
from app.audit.service import record_audit_event
from app.auth import policy
from app.auth.constants import CSRF_SAFE_METHODS, AuthErrorCode
from app.auth.errors import PermissionDeniedError
from app.auth.http import AuthAPIError, require_csrf
from app.auth.permissions import Permission
from app.auth.policy import Actor
from app.auth.rate_limit import (
    AuthRateLimits,
    RateLimiter,
    RateLimiterUnavailable,
    RateLimitExceeded,
    RateLimitRule,
)
from app.auth.schemas import ClientMetadata
from app.auth.service import AuthConfig, AuthService
from app.core.client_ip import client_ip
from app.core.config import Settings, get_settings, settings
from app.core.database import get_db_session
from app.core.middleware import get_request_id
from app.core.redis import redis_client
from app.core.security.access_tokens import AccessTokenClaims, decode_access_token, utc_now
from app.core.security.exceptions import (
    ExpiredAccessTokenError,
    InvalidAccessTokenError,
    SecurityConfigurationError,
)
from app.users.models import User
from app.users.repository import UserRepository

# Absolute so Swagger UI posts to the right place regardless of the docs URL.
logger = logging.getLogger(__name__)

TOKEN_URL = f"{settings.api_v1_prefix}/auth/token"
# Documents the OAuth2 password flow and bearer scheme in OpenAPI. auto_error=False so
# cookie-authenticated browsers are handled by get_current_identity instead.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=TOKEN_URL, auto_error=False)

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_clock() -> Callable[[], datetime]:
    return utc_now


ClockDep = Annotated[Callable[[], datetime], Depends(get_clock)]


def get_auth_config(settings: SettingsDep) -> AuthConfig:
    try:
        return AuthConfig.from_settings(settings)
    except SecurityConfigurationError as exc:
        # Only possible in development/test: staging and production refuse to start
        # without these secrets.
        logger.error("Authentication is not configured: %s", exc.reason)
        raise AuthAPIError(AuthErrorCode.SERVICE_UNAVAILABLE) from None


AuthConfigDep = Annotated[AuthConfig, Depends(get_auth_config)]


def get_auth_service(db: DbDep, config: AuthConfigDep, clock: ClockDep) -> AuthService:
    return AuthService(db, config, clock=clock)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


@dataclass(frozen=True, slots=True)
class CurrentIdentity:
    """The authenticated staff member for this request, with roles loaded."""

    user: User
    claims: AccessTokenClaims
    method: Literal["bearer", "cookie"]

    @property
    def actor(self) -> Actor:
        return Actor.from_user(self.user)


async def get_current_identity(
    request: Request,
    bearer_token: Annotated[str | None, Security(oauth2_scheme)],
    settings: SettingsDep,
    config: AuthConfigDep,
    clock: ClockDep,
    db: DbDep,
) -> CurrentIdentity:
    """Authenticate from the Authorization header, or else the access cookie.

    An Authorization header always takes precedence and is never combined with the
    cookie: a malformed or non-Bearer header fails instead of falling back. Cookie
    authentication of unsafe methods also requires a valid CSRF header.
    """
    method: Literal["bearer", "cookie"]
    if "authorization" in request.headers:
        if not bearer_token:
            raise AuthAPIError(AuthErrorCode.INVALID_TOKEN)
        token, method = bearer_token, "bearer"
    else:
        cookie_token = request.cookies.get(settings.auth_access_cookie_name)
        if not cookie_token:
            raise AuthAPIError(AuthErrorCode.AUTHENTICATION_REQUIRED)
        if request.method not in CSRF_SAFE_METHODS:
            require_csrf(request, settings)
        token, method = cookie_token, "cookie"

    try:
        claims = decode_access_token(token, config.access, now=clock())
    except ExpiredAccessTokenError:
        raise AuthAPIError(AuthErrorCode.TOKEN_EXPIRED) from None
    except InvalidAccessTokenError:
        raise AuthAPIError(AuthErrorCode.INVALID_TOKEN) from None

    user = await UserRepository(db).get_by_id(claims.user_id)
    # A disabled account or a bumped token version (password change, revoke-all) makes
    # every earlier access token invalid immediately.
    if user is None or not user.is_active or user.token_version != claims.token_version:
        raise AuthAPIError(AuthErrorCode.INVALID_TOKEN)
    return CurrentIdentity(user=user, claims=claims, method=method)


CurrentIdentityDep = Annotated[CurrentIdentity, Depends(get_current_identity)]


PermissionGuard = Callable[..., Awaitable[CurrentIdentity]]


async def _record_denial(
    request: Request, db: AsyncSession, identity: CurrentIdentity, exc: PermissionDeniedError
) -> None:
    try:
        record_audit_event(
            db,
            AuditEventCode.AUTH_PERMISSION_DENIED,
            actor_id=identity.user.id,
            request_id=get_request_id(request),
            metadata={
                "required_permissions": list(exc.required),
                "permission_mode": exc.mode,
                "method": request.method,
                "path": request.url.path,
            },
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Could not record permission-denied audit event")


def _guard(mode: Literal["all", "any"], permissions: tuple[Permission, ...]) -> PermissionGuard:
    # Validated when the route is declared, so a mistake fails at startup.
    policy.validate_permissions(permissions)
    check = policy.require_permissions if mode == "all" else policy.require_any_permission

    async def dependency(
        request: Request, identity: CurrentIdentityDep, db: DbDep
    ) -> CurrentIdentity:
        # Authentication failures have already returned 401; this is the 403 layer.
        try:
            check(identity.actor, *permissions)
        except PermissionDeniedError as exc:
            await _record_denial(request, db, identity, exc)
            logger.info(
                "Permission denied",
                extra={
                    "user_id": str(identity.user.id),
                    "required_permissions": list(exc.required),
                    "permission_mode": exc.mode,
                    "method": request.method,
                    "path": request.url.path,
                    "request_id": get_request_id(request),
                },
            )
            raise AuthAPIError(AuthErrorCode.PERMISSION_DENIED) from None
        return identity

    return dependency


def require_permissions(*permissions: Permission) -> PermissionGuard:
    """Dependency that requires every listed permission. Returns the identity."""
    return _guard("all", permissions)


def require_any_permission(*permissions: Permission) -> PermissionGuard:
    """Dependency that requires at least one listed permission. Returns the identity."""
    return _guard("any", permissions)


# --- Rate limiting ----------------------------------------------------------------------


def get_redis() -> Redis:
    client: Redis = redis_client
    return client


RedisDep = Annotated[Redis, Depends(get_redis)]


def get_client_metadata(request: Request, settings: SettingsDep) -> ClientMetadata:
    """User agent and client address, honouring only configured trusted proxies."""
    return ClientMetadata.from_request_values(
        request.headers.get("user-agent"), client_ip(request, settings.trusted_proxies)
    )


ClientDep = Annotated[ClientMetadata, Depends(get_client_metadata)]


@dataclass(frozen=True, slots=True)
class _Check:
    rule: RateLimitRule
    value: str
    metadata: Mapping[str, object]


async def _enforce(
    request: Request,
    db: AsyncSession,
    redis: Redis,
    settings: Settings,
    config: AuthConfig,
    checks: list[_Check],
    *,
    fail_closed: bool,
    actor_id: uuid.UUID | None = None,
) -> None:
    limiter = RateLimiter(redis, settings.rate_limit_key_prefix)
    for check in checks:
        try:
            # Only keyed fingerprints reach Redis, never raw emails or addresses.
            await limiter.hit(check.rule, config.fingerprint(check.value))
        except RateLimitExceeded as exc:
            if exc.first:
                await _record_rate_limited(request, db, check, actor_id)
            raise AuthAPIError(
                AuthErrorCode.RATE_LIMITED, headers={"Retry-After": str(exc.retry_after)}
            ) from None
        except RateLimiterUnavailable:
            if fail_closed:
                logger.error("Rate limiter unavailable; refusing %s", request.url.path)
                raise AuthAPIError(AuthErrorCode.SERVICE_UNAVAILABLE) from None
            logger.warning("Rate limiter unavailable; allowing %s", request.url.path)
            return


async def _record_rate_limited(
    request: Request, db: AsyncSession, check: _Check, actor_id: uuid.UUID | None
) -> None:
    try:
        record_audit_event(
            db,
            AuditEventCode.AUTH_RATE_LIMITED,
            actor_id=actor_id,
            request_id=get_request_id(request),
            metadata={
                "rule": check.rule.name,
                **{key: value for key, value in check.metadata.items() if value is not None},
            },
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Could not record rate-limit audit event")


async def limit_login(
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    client: ClientDep,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    config: AuthConfigDep,
) -> OAuth2PasswordRequestForm:
    """Per client IP and per normalized email. Fails closed when Redis is down.

    Checked before the email is looked up, so known and unknown emails behave alike.
    Returns the parsed form so the route declares it only once.
    """
    limits = AuthRateLimits.from_settings(settings)
    ip = client_ip(request, settings.trusted_proxies) or "unknown"
    email = form.username.strip().lower()
    base = {"client_ip_prefix": client.client_ip_prefix}
    await _enforce(
        request,
        db,
        redis,
        settings,
        config,
        [
            _Check(limits.login_ip, ip, base),
            _Check(
                limits.login_email, email, base | {"email_fingerprint": config.fingerprint(email)}
            ),
        ],
        fail_closed=True,
    )
    return form


async def limit_refresh(
    request: Request,
    client: ClientDep,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    config: AuthConfigDep,
) -> None:
    """Per client IP. The user is unknown until the token is validated. Fails open: the
    request still needs a valid refresh token, and rotation detects reuse."""
    limits = AuthRateLimits.from_settings(settings)
    ip = client_ip(request, settings.trusted_proxies) or "unknown"
    await _enforce(
        request,
        db,
        redis,
        settings,
        config,
        [_Check(limits.refresh_ip, ip, {"client_ip_prefix": client.client_ip_prefix})],
        fail_closed=False,
    )


async def limit_session(
    request: Request,
    client: ClientDep,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    config: AuthConfigDep,
) -> None:
    """Per client IP for logout and the read-only session endpoints. Fails open."""
    limits = AuthRateLimits.from_settings(settings)
    ip = client_ip(request, settings.trusted_proxies) or "unknown"
    await _enforce(
        request,
        db,
        redis,
        settings,
        config,
        [_Check(limits.session_ip, ip, {"client_ip_prefix": client.client_ip_prefix})],
        fail_closed=False,
    )


async def limit_password_change(
    request: Request,
    identity: CurrentIdentityDep,
    client: ClientDep,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    config: AuthConfigDep,
) -> None:
    """Per client IP and per user, so the current password cannot be guessed quickly.
    Fails closed when Redis is down."""
    limits = AuthRateLimits.from_settings(settings)
    ip = client_ip(request, settings.trusted_proxies) or "unknown"
    base = {"client_ip_prefix": client.client_ip_prefix}
    await _enforce(
        request,
        db,
        redis,
        settings,
        config,
        [
            _Check(limits.password_change_ip, ip, base),
            _Check(limits.password_change_user, str(identity.user.id), base),
        ],
        fail_closed=True,
        actor_id=identity.user.id,
    )


LoginForm = Annotated[OAuth2PasswordRequestForm, Depends(limit_login)]
