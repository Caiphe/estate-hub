import json
import re
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from app.audit.events import AuditEventCode

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


# --- Allow-listed event metadata ---------------------------------------------------------
#
# Catalog events touch owner contact details, notes, and private files. Their metadata is
# restricted to identifiers, counts, changed field names, and short codes, so free text
# (an email, a note, a filename, a storage key) has nowhere to go.

_UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MEDIA_TYPE_PATTERN = re.compile(r"^[a-z]+/[a-z0-9.+-]{1,64}$")
MAX_METADATA_LIST_ITEMS = 100


class MetadataKind(StrEnum):
    ID = "id"
    ID_LIST = "id_list"
    COUNT = "count"
    FIELD_NAMES = "field_names"
    CODE = "code"
    MEDIA_TYPE = "media_type"


K = MetadataKind
_PARENT = {"property_id": K.ID, "unit_id": K.ID}
_CHANGED = {"changed_fields": K.FIELD_NAMES}
_VERSION = {"version": K.COUNT}
_FILE = {"media_type": K.MEDIA_TYPE, "byte_size": K.COUNT}

EVENT_METADATA_SCHEMAS: Mapping[AuditEventCode, Mapping[str, MetadataKind]] = MappingProxyType(
    {
        AuditEventCode.PROPERTY_CREATED: {
            "amenity_count": K.COUNT,
            "owner_count": K.COUNT,
            "unit_count": K.COUNT,
        },
        AuditEventCode.PROPERTY_UPDATED: _CHANGED | _VERSION,
        AuditEventCode.PROPERTY_ARCHIVED: _VERSION,
        AuditEventCode.PROPERTY_RESTORED: _VERSION,
        AuditEventCode.PROPERTY_OWNER_ADDED: {"ownership_id": K.ID, "contact_id": K.ID},
        AuditEventCode.PROPERTY_OWNER_UPDATED: {"ownership_id": K.ID, "contact_id": K.ID}
        | _CHANGED,
        AuditEventCode.PROPERTY_OWNER_REMOVED: {"ownership_id": K.ID, "contact_id": K.ID},
        AuditEventCode.UNIT_CREATED: {"property_id": K.ID},
        AuditEventCode.UNIT_UPDATED: {"property_id": K.ID} | _CHANGED | _VERSION,
        AuditEventCode.UNIT_ARCHIVED: {"property_id": K.ID} | _VERSION,
        AuditEventCode.UNIT_RESTORED: {"property_id": K.ID} | _VERSION,
        AuditEventCode.MEDIA_UPLOADED: _PARENT | _FILE,
        AuditEventCode.MEDIA_UPDATED: _PARENT | _CHANGED,
        AuditEventCode.MEDIA_REORDERED: _PARENT | {"media_ids": K.ID_LIST},
        AuditEventCode.MEDIA_COVER_CHANGED: _PARENT | {"previous_cover_id": K.ID},
        AuditEventCode.MEDIA_ARCHIVED: _PARENT,
        AuditEventCode.DOCUMENT_UPLOADED: _PARENT | _FILE | {"category": K.CODE},
        AuditEventCode.DOCUMENT_UPDATED: _PARENT | _CHANGED,
        AuditEventCode.DOCUMENT_REPLACED: _PARENT | _FILE,
        AuditEventCode.DOCUMENT_ARCHIVED: _PARENT,
        AuditEventCode.DOCUMENT_DOWNLOADED: _PARENT,
        AuditEventCode.CONTACT_CREATED: {"kind": K.CODE},
        AuditEventCode.CONTACT_UPDATED: _CHANGED | _VERSION,
        AuditEventCode.CONTACT_ARCHIVED: _VERSION,
        AuditEventCode.CONTACT_RESTORED: _VERSION,
        AuditEventCode.REFERENCE_DATA_CREATED: {"property_type_id": K.ID},
        AuditEventCode.REFERENCE_DATA_UPDATED: {"property_type_id": K.ID} | _CHANGED,
        AuditEventCode.REFERENCE_DATA_DISABLED: {"property_type_id": K.ID},
        AuditEventCode.REFERENCE_DATA_REACTIVATED: {"property_type_id": K.ID},
        AuditEventCode.REFERENCE_DATA_REORDERED: {
            "record_type": K.CODE,
            "property_type_id": K.ID,
            "ids": K.ID_LIST,
        },
    }
)


def validate_event_metadata(code: str, metadata: Mapping[str, Any]) -> None:
    """Raise unless ``metadata`` fits the allow-list for ``code``.

    Events without a schema (authentication, staff) rely on the deny-list alone. Keys are
    optional; unknown keys and values of the wrong shape are refused. Errors name the
    key, never the value.
    """
    try:
        schema = EVENT_METADATA_SCHEMAS.get(AuditEventCode(code))
    except ValueError:
        return
    if schema is None:
        return
    for key, value in metadata.items():
        kind = schema.get(key)
        if kind is None:
            raise UnsafeAuditMetadataError(f"Audit metadata key {key!r} is not allowed for {code}.")
        if not _fits(kind, value):
            raise UnsafeAuditMetadataError(f"Audit metadata key {key!r} must be {kind.value}.")


def _fits(kind: MetadataKind, value: Any) -> bool:
    match kind:
        case MetadataKind.ID:
            return isinstance(value, str) and bool(_UUID_PATTERN.match(value))
        case MetadataKind.COUNT:
            return isinstance(value, int) and not isinstance(value, bool) and value >= 0
        case MetadataKind.CODE:
            return isinstance(value, str) and bool(_NAME_PATTERN.match(value))
        case MetadataKind.MEDIA_TYPE:
            return isinstance(value, str) and bool(_MEDIA_TYPE_PATTERN.match(value))
        case MetadataKind.ID_LIST:
            return _list_of(value, MetadataKind.ID)
        case MetadataKind.FIELD_NAMES:
            return _list_of(value, MetadataKind.CODE)


def _list_of(value: Any, kind: MetadataKind) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= MAX_METADATA_LIST_ITEMS
        and all(_fits(kind, item) for item in value)
    )
