import json
import re
from collections.abc import Mapping
from typing import Any

MAX_METADATA_BYTES = 8_192
MAX_METADATA_DEPTH = 4

# Keys are compared after lowercasing and replacing "-", " ", and "." with "_".
_FORBIDDEN_KEY_FRAGMENTS = (
    "password",
    "passphrase",
    "secret",
    "csrf",
    "authorization",
    "cookie",
    "credential",
    "api_key",
    "apikey",
    "private_key",
)
_FORBIDDEN_KEYS = frozenset(
    {"token", "jwt", "bearer", "token_hash", "body", "request_body", "payload", "form", "form_data"}
)
# Identifiers such as token_family_id and token_version are allowed; token values are not.
_FORBIDDEN_KEY_SUFFIXES = ("_token", "_jwt")
# Values that look like credentials are refused even under an innocent key.
_FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"^\$argon2(id|i|d)\$"),
    re.compile(r"^eyJ[\w-]+\.[\w-]+\.[\w-]*$"),
    re.compile(r"^bearer\s", re.IGNORECASE),
)


class UnsafeAuditMetadataError(ValueError):
    pass


def validate_audit_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``metadata`` as a plain dict, or raise if it could leak sensitive data.

    The error names the offending path, never the offending value.
    """
    _check(metadata, path="", depth=1)
    try:
        encoded = json.dumps(metadata, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise UnsafeAuditMetadataError("Audit metadata must be JSON-serializable.") from exc
    if len(encoded.encode()) > MAX_METADATA_BYTES:
        raise UnsafeAuditMetadataError(
            f"Audit metadata must be at most {MAX_METADATA_BYTES} bytes."
        )
    return dict(metadata)


def _check(value: Any, path: str, depth: int) -> None:
    if isinstance(value, Mapping):
        if depth > MAX_METADATA_DEPTH:
            raise UnsafeAuditMetadataError(
                f"Audit metadata must be at most {MAX_METADATA_DEPTH} levels deep."
            )
        for key, item in value.items():
            if not isinstance(key, str):
                raise UnsafeAuditMetadataError("Audit metadata keys must be strings.")
            item_path = f"{path}.{key}" if path else key
            if _is_forbidden_key(key):
                raise UnsafeAuditMetadataError(f"Audit metadata key {item_path!r} is not allowed.")
            _check(item, item_path, depth + 1)
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _check(item, f"{path}[{index}]", depth)
    elif isinstance(value, str) and any(p.search(value) for p in _FORBIDDEN_VALUE_PATTERNS):
        raise UnsafeAuditMetadataError(f"Audit metadata value at {path!r} looks like a credential.")


def _is_forbidden_key(key: str) -> bool:
    normalized = re.sub(r"[-\s.]+", "_", key.strip().lower())
    return (
        normalized in _FORBIDDEN_KEYS
        or normalized.endswith(_FORBIDDEN_KEY_SUFFIXES)
        or any(fragment in normalized for fragment in _FORBIDDEN_KEY_FRAGMENTS)
    )
