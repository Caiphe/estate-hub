import hashlib
import hmac
import re
import secrets

from app.core.config import Settings
from app.core.security.exceptions import (
    MalformedRefreshTokenError,
    SecurityConfigurationError,
)

# 32 random bytes = 256 bits of entropy, encoded as 43 URL-safe base64 characters.
TOKEN_BYTES = 32
_URL_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def refresh_token_hash_key(settings: Settings) -> bytes:
    if settings.refresh_token_hash_secret is None:
        raise SecurityConfigurationError("refresh_token_hash_secret_missing")
    return settings.refresh_token_hash_secret.get_secret_value().encode()


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_refresh_token(token: str, key: bytes) -> str:
    """Return the keyed HMAC-SHA256 hex digest stored and indexed in place of the token.

    A keyed hash means a database leak alone cannot be used to test guessed tokens.
    """
    if not _URL_SAFE_TOKEN.fullmatch(token):
        raise MalformedRefreshTokenError()
    return hmac.new(key, token.encode("ascii"), hashlib.sha256).hexdigest()


def refresh_token_matches(token: str, stored_hash: str, key: bytes) -> bool:
    try:
        candidate = hash_refresh_token(token, key)
    except MalformedRefreshTokenError:
        return False
    return hmac.compare_digest(candidate.encode("ascii"), stored_hash.encode("utf-8"))


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def csrf_tokens_match(cookie_value: str | None, header_value: str | None) -> bool:
    """Constant-time comparison of the CSRF cookie and header (double-submit pattern)."""
    if not cookie_value or not header_value:
        return False
    if not _URL_SAFE_TOKEN.fullmatch(cookie_value) or not _URL_SAFE_TOKEN.fullmatch(header_value):
        return False
    return hmac.compare_digest(cookie_value.encode("ascii"), header_value.encode("ascii"))


def derive_key(secret: bytes, label: str) -> bytes:
    """A purpose-specific subkey, so one secret never keys two different uses directly."""
    return hmac.new(secret, label.encode(), hashlib.sha256).digest()


def keyed_fingerprint(value: str, key: bytes) -> str:
    """A stable, non-reversible reference to a value such as an email or IP address.

    Equal inputs give equal fingerprints, so events can be correlated without storing
    the value itself.
    """
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()
