import uuid
from collections.abc import Sequence
from typing import Literal

from app.auth.constants import AuthErrorCode


class AuthServiceError(Exception):
    """A business failure from the authentication service.

    ``public_code`` is the only thing an API response may reveal. ``reason`` is a short,
    non-sensitive code for audit events and logs.
    """

    public_code = AuthErrorCode.INVALID_SESSION
    default_reason = "auth_failed"

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason or self.default_reason
        super().__init__(self.reason)


class InvalidCredentialsError(AuthServiceError):
    public_code = AuthErrorCode.INVALID_CREDENTIALS
    default_reason = "invalid_credentials"


class DisabledUserError(InvalidCredentialsError):
    """Correct password for a disabled account. Publicly identical to invalid credentials."""

    default_reason = "user_disabled"


class IncorrectCurrentPasswordError(AuthServiceError):
    """The authenticated user's current password did not verify during a password change."""

    public_code = AuthErrorCode.CURRENT_PASSWORD_INCORRECT
    default_reason = "current_password_incorrect"


class InvalidSessionError(AuthServiceError):
    public_code = AuthErrorCode.INVALID_SESSION
    default_reason = "invalid_session"


class ExpiredSessionError(InvalidSessionError):
    default_reason = "session_expired"


class ReusedRefreshTokenError(InvalidSessionError):
    """An already-rotated refresh token was presented again; its family is now revoked.

    Carries the identifiers the caller needs to record a security audit event.
    """

    default_reason = "refresh_token_reused"

    def __init__(self, user_id: uuid.UUID, family_id: uuid.UUID, revoked_sessions: int) -> None:
        super().__init__()
        self.user_id = user_id
        self.family_id = family_id
        self.revoked_sessions = revoked_sessions


class SessionConflictError(InvalidSessionError):
    """Another request rotated the same refresh token moments ago."""

    default_reason = "concurrent_rotation"


class PermissionDeniedError(AuthServiceError):
    """An authenticated actor lacks a required permission.

    ``required`` and ``mode`` are for logs and audit events; responses reveal only the
    public code.
    """

    public_code = AuthErrorCode.PERMISSION_DENIED
    default_reason = "permission_denied"

    def __init__(self, required: Sequence[str], mode: Literal["all", "any"]) -> None:
        super().__init__()
        self.required = tuple(str(permission) for permission in required)
        self.mode = mode
