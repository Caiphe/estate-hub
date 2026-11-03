import secrets
import unicodedata
from dataclasses import dataclass
from functools import cache

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.security.exceptions import PasswordHashError, PasswordPolicyError
from app.users.constants import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH

# Argon2id with the argon2-cffi RFC 9106 low-memory defaults (t=3, m=64 MiB, p=4).
# Changing these parameters makes existing hashes report needs-rehash on next login.
DEFAULT_PASSWORD_HASHER = PasswordHash((Argon2Hasher(),))


@dataclass(frozen=True, slots=True)
class PasswordCheck:
    valid: bool
    # A fresh hash when the stored one uses outdated parameters; persist it on login.
    replacement_hash: str | None = None


def normalize_password(password: str) -> str:
    # NFKC makes visually identical input (for example a precomposed "é" and "e" plus a
    # combining accent) produce the same hash. Nothing is trimmed or truncated.
    return unicodedata.normalize("NFKC", password)


def hash_password(password: str, hasher: PasswordHash = DEFAULT_PASSWORD_HASHER) -> str:
    """Hash a new password after enforcing the length policy."""
    length = len(password)
    if length < PASSWORD_MIN_LENGTH:
        raise PasswordPolicyError("password_too_short")
    if length > PASSWORD_MAX_LENGTH:
        raise PasswordPolicyError("password_too_long")
    return hasher.hash(normalize_password(password))


def verify_password(
    password: str, password_hash: str, hasher: PasswordHash = DEFAULT_PASSWORD_HASHER
) -> PasswordCheck:
    """Check a password against a stored hash.

    Input longer than the policy maximum cannot match any stored hash, so it is rejected
    without spending Argon2 work on it.
    """
    if not password or len(password) > PASSWORD_MAX_LENGTH:
        return PasswordCheck(valid=False)
    try:
        valid, replacement = hasher.verify_and_update(normalize_password(password), password_hash)
    except UnknownHashError:
        # The library error message contains the stored hash; do not chain it.
        raise PasswordHashError() from None
    return PasswordCheck(valid=valid, replacement_hash=replacement)


@cache
def _dummy_hash(hasher: PasswordHash) -> str:
    return hasher.hash(secrets.token_urlsafe(32))


def verify_dummy_password(password: str, hasher: PasswordHash = DEFAULT_PASSWORD_HASHER) -> None:
    """Spend the same Argon2 work as a real check when no account matches.

    Callers use this for unknown emails so response time does not reveal whether an
    account exists. The result is always a failed check.
    """
    verify_password(password, _dummy_hash(hasher), hasher)
