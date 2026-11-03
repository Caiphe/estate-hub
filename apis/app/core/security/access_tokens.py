import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Self

import jwt
from jwt.exceptions import InvalidJTIError, InvalidSubjectError

from app.core.config import Settings
from app.core.security.exceptions import (
    ExpiredAccessTokenError,
    InvalidAccessTokenError,
    SecurityConfigurationError,
)

ACCESS_TOKEN_TYPE = "access"
# Generous for our claim set; anything longer is rejected before parsing.
MAX_ACCESS_TOKEN_LENGTH = 4096
_REQUIRED_CLAIMS = ("iss", "aud", "sub", "iat", "nbf", "exp", "jti", "typ", "ver")
_TOKEN_ID = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True, slots=True)
class AccessTokenConfig:
    secret_key: str
    algorithm: str
    issuer: str
    audience: str
    lifetime: timedelta

    def __repr__(self) -> str:
        return (
            f"AccessTokenConfig(algorithm={self.algorithm!r}, issuer={self.issuer!r}, "
            f"audience={self.audience!r}, lifetime={self.lifetime!r})"
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        if settings.jwt_secret_key is None:
            raise SecurityConfigurationError("jwt_secret_key_missing")
        return cls(
            secret_key=settings.jwt_secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            lifetime=timedelta(minutes=settings.access_token_ttl_minutes),
        )


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    token_version: int
    token_id: str
    issued_at: datetime
    not_before: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class IssuedAccessToken:
    token: str
    claims: AccessTokenClaims
    expires_in: int

    def __repr__(self) -> str:
        return f"IssuedAccessToken(claims={self.claims!r}, expires_in={self.expires_in})"


def utc_now() -> datetime:
    return datetime.now(UTC)


def _require_aware(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Security timestamps must be timezone-aware.")
    return now.astimezone(UTC)


def create_access_token(
    user_id: uuid.UUID,
    token_version: int,
    config: AccessTokenConfig,
    now: datetime | None = None,
) -> IssuedAccessToken:
    """Sign a short-lived access token.

    Role codes are deliberately absent: authorization reads current roles from the
    database so role changes and account disabling apply immediately.
    """
    if token_version < 0:
        raise ValueError("token_version must not be negative.")
    # JWT times have one-second precision; truncate so claims round-trip exactly.
    issued_at = _require_aware(now or utc_now()).replace(microsecond=0)
    expires_at = issued_at + config.lifetime
    claims = AccessTokenClaims(
        user_id=user_id,
        token_version=token_version,
        token_id=uuid.uuid4().hex,
        issued_at=issued_at,
        not_before=issued_at,
        expires_at=expires_at,
    )
    payload = {
        "iss": config.issuer,
        "aud": config.audience,
        "sub": str(user_id),
        "iat": int(issued_at.timestamp()),
        "nbf": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": claims.token_id,
        "typ": ACCESS_TOKEN_TYPE,
        "ver": token_version,
    }
    token = jwt.encode(payload, config.secret_key, algorithm=config.algorithm)
    return IssuedAccessToken(
        token=token, claims=claims, expires_in=int(config.lifetime.total_seconds())
    )


def decode_access_token(
    token: str,
    config: AccessTokenConfig,
    now: datetime | None = None,
    leeway: timedelta = timedelta(0),
) -> AccessTokenClaims:
    """Verify an access token and return its claims, or raise a typed security error."""
    if not token or len(token) > MAX_ACCESS_TOKEN_LENGTH:
        raise InvalidAccessTokenError("malformed")
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            config.secret_key,
            # Only the configured algorithm is accepted, whatever the header claims.
            algorithms=[config.algorithm],
            audience=config.audience,
            issuer=config.issuer,
            # Time claims are checked below against an injectable clock.
            options={
                "require": list(_REQUIRED_CLAIMS),
                "verify_exp": False,
                "verify_nbf": False,
                "verify_iat": False,
            },
        )
    except jwt.InvalidSignatureError:
        raise InvalidAccessTokenError("bad_signature") from None
    except jwt.InvalidAlgorithmError:
        raise InvalidAccessTokenError("algorithm_not_allowed") from None
    except jwt.InvalidAudienceError:
        raise InvalidAccessTokenError("wrong_audience") from None
    except jwt.InvalidIssuerError:
        raise InvalidAccessTokenError("wrong_issuer") from None
    except jwt.MissingRequiredClaimError:
        raise InvalidAccessTokenError("missing_claim") from None
    except InvalidSubjectError:
        raise InvalidAccessTokenError("malformed_subject") from None
    except InvalidJTIError:
        raise InvalidAccessTokenError("malformed_token_id") from None
    except jwt.PyJWTError:
        raise InvalidAccessTokenError("malformed") from None

    claims = _parse_claims(payload)
    current = _require_aware(now or utc_now())
    if current + leeway < claims.not_before:
        raise InvalidAccessTokenError("not_yet_valid")
    if current - leeway >= claims.expires_at:
        raise ExpiredAccessTokenError()
    return claims


def _parse_claims(payload: dict[str, Any]) -> AccessTokenClaims:
    if payload.get("typ") != ACCESS_TOKEN_TYPE:
        raise InvalidAccessTokenError("wrong_purpose")

    subject = payload.get("sub")
    try:
        user_id = uuid.UUID(subject) if isinstance(subject, str) else None
    except ValueError:
        user_id = None
    if user_id is None or str(user_id) != subject:
        raise InvalidAccessTokenError("malformed_subject")

    version = payload.get("ver")
    # bool is an int subclass; reject it explicitly.
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise InvalidAccessTokenError("malformed_token_version")

    token_id = payload.get("jti")
    if not isinstance(token_id, str) or not _TOKEN_ID.fullmatch(token_id):
        raise InvalidAccessTokenError("malformed_token_id")

    times: list[int] = []
    for name in ("iat", "nbf", "exp"):
        value = payload.get(name)
        if not isinstance(value, int) or isinstance(value, bool):
            raise InvalidAccessTokenError("malformed_time_claim")
        times.append(value)
    try:
        issued_at, not_before, expires_at = (datetime.fromtimestamp(value, UTC) for value in times)
    except OverflowError, OSError, ValueError:
        raise InvalidAccessTokenError("malformed_time_claim") from None
    if not issued_at <= not_before < expires_at:
        raise InvalidAccessTokenError("inconsistent_time_claims")

    return AccessTokenClaims(
        user_id=user_id,
        token_version=version,
        token_id=token_id,
        issued_at=issued_at,
        not_before=not_before,
        expires_at=expires_at,
    )
