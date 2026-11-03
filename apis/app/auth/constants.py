from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fastapi import status

CSRF_HEADER_NAME = "X-CSRF-Token"
TOKEN_TYPE: Final = "bearer"
# Methods that never change state and therefore never require a CSRF token.
CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class AuthErrorCode(StrEnum):
    """Stable machine-readable authentication error codes.

    Codes are public. They must never reveal whether an account exists or why it was
    rejected: an unknown email, a wrong password, and a disabled account all map to
    ``INVALID_CREDENTIALS``; a revoked, expired, unknown, or reused refresh token all
    map to ``INVALID_SESSION``. Detailed reasons belong in audit events only.
    """

    INVALID_CREDENTIALS = "invalid_credentials"
    AUTHENTICATION_REQUIRED = "authentication_required"
    INVALID_TOKEN = "invalid_token"
    TOKEN_EXPIRED = "token_expired"
    INVALID_SESSION = "invalid_session"
    CSRF_FAILED = "csrf_failed"
    PERMISSION_DENIED = "permission_denied"
    RATE_LIMITED = "auth_rate_limited"
    SERVICE_UNAVAILABLE = "auth_service_unavailable"
    CURRENT_PASSWORD_INCORRECT = "current_password_incorrect"


@dataclass(frozen=True, slots=True)
class AuthErrorSpec:
    status_code: int
    message: str


AUTH_ERRORS: dict[AuthErrorCode, AuthErrorSpec] = {
    AuthErrorCode.INVALID_CREDENTIALS: AuthErrorSpec(
        status.HTTP_401_UNAUTHORIZED, "Incorrect email or password."
    ),
    AuthErrorCode.AUTHENTICATION_REQUIRED: AuthErrorSpec(
        status.HTTP_401_UNAUTHORIZED, "Authentication is required."
    ),
    AuthErrorCode.INVALID_TOKEN: AuthErrorSpec(
        status.HTTP_401_UNAUTHORIZED, "The access token is invalid."
    ),
    AuthErrorCode.TOKEN_EXPIRED: AuthErrorSpec(
        status.HTTP_401_UNAUTHORIZED, "The access token has expired."
    ),
    AuthErrorCode.INVALID_SESSION: AuthErrorSpec(
        status.HTTP_401_UNAUTHORIZED, "The session is no longer valid. Please sign in again."
    ),
    AuthErrorCode.CSRF_FAILED: AuthErrorSpec(
        status.HTTP_403_FORBIDDEN, "The request could not be verified."
    ),
    AuthErrorCode.PERMISSION_DENIED: AuthErrorSpec(
        status.HTTP_403_FORBIDDEN, "You do not have permission to perform this action."
    ),
    AuthErrorCode.RATE_LIMITED: AuthErrorSpec(
        status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Please try again later."
    ),
    # The caller is already authenticated, so this is a field error, not a 401 that a
    # frontend would treat as an expired session.
    AuthErrorCode.CURRENT_PASSWORD_INCORRECT: AuthErrorSpec(
        status.HTTP_422_UNPROCESSABLE_CONTENT, "The current password is incorrect."
    ),
    AuthErrorCode.SERVICE_UNAVAILABLE: AuthErrorSpec(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Sign-in is temporarily unavailable. Please try again later.",
    ),
}

# Keyed refresh-token hashes are hex-encoded HMAC-SHA256 digests.
REFRESH_TOKEN_HASH_LENGTH = 64
USER_AGENT_MAX_LENGTH = 255
CLIENT_IP_PREFIX_MAX_LENGTH = 50
# Client addresses are stored only as these network prefixes, never as full addresses.
CLIENT_IPV4_PREFIX = 24
CLIENT_IPV6_PREFIX = 48


class RevocationReason(StrEnum):
    LOGOUT = "logout"
    ROTATED = "rotated"
    REUSE_DETECTED = "reuse_detected"
    PASSWORD_CHANGED = "password_changed"
    USER_DISABLED = "user_disabled"
    ROLES_CHANGED = "roles_changed"
    ADMIN_REVOKED = "admin_revoked"
