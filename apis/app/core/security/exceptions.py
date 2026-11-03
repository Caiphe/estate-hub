class SecurityError(Exception):
    """Base class for security primitive failures.

    ``reason`` is a short, non-sensitive code for logs and audit events. Messages never
    contain passwords, tokens, hashes, or keys.
    """

    default_reason = "security_error"

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason or self.default_reason
        super().__init__(self.reason)


class SecurityConfigurationError(SecurityError):
    """A required secret or security setting is missing or unusable."""

    default_reason = "misconfigured"


class PasswordPolicyError(SecurityError):
    """A new password does not satisfy the length policy."""

    default_reason = "password_policy"


class PasswordHashError(SecurityError):
    """A stored password hash is not a recognized Argon2id hash."""

    default_reason = "unrecognized_password_hash"


class InvalidAccessTokenError(SecurityError):
    """The access token is malformed, tampered with, or not meant for this service."""

    default_reason = "invalid_token"


class ExpiredAccessTokenError(InvalidAccessTokenError):
    """The access token was valid but has expired."""

    default_reason = "token_expired"


class MalformedRefreshTokenError(SecurityError):
    """The value cannot be a refresh token issued by this service."""

    default_reason = "malformed_refresh_token"
