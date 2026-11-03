import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from fastapi import Depends, Request, Security
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import policy
from app.auth.constants import CSRF_SAFE_METHODS, AuthErrorCode
from app.auth.errors import PermissionDeniedError
from app.auth.http import AuthAPIError, require_csrf
from app.auth.permissions import Permission
from app.auth.policy import Actor
from app.auth.service import AuthConfig, AuthService
from app.core.config import Settings, get_settings, settings
from app.core.database import get_db_session
from app.core.middleware import get_request_id
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


PermissionGuard = Callable[[Request, CurrentIdentity], Awaitable[CurrentIdentity]]


def _guard(mode: Literal["all", "any"], permissions: tuple[Permission, ...]) -> PermissionGuard:
    # Validated when the route is declared, so a mistake fails at startup.
    policy.validate_permissions(permissions)
    check = policy.require_permissions if mode == "all" else policy.require_any_permission

    async def dependency(request: Request, identity: CurrentIdentityDep) -> CurrentIdentity:
        # Authentication failures have already returned 401; this is the 403 layer.
        try:
            check(identity.actor, *permissions)
        except PermissionDeniedError as exc:
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
