from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event

from app.audit.events import AuditEventCode
from app.audit.metadata import (
    EVENT_METADATA_SCHEMAS,
    MAX_METADATA_DEPTH,
    MAX_METADATA_LIST_ITEMS,
    MetadataKind,
    UnsafeAuditMetadataError,
    validate_audit_metadata,
    validate_event_metadata,
)
from app.audit.models import AuditEvent, AuditEventImmutableError, _refuse_change
from app.audit.schemas import AuditEventCreate, AuditEventPublic


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "new_password",
        "Password-Hash",
        "refresh_token",
        "access.token",
        "token",
        "token_hash",
        "csrf",
        "X-CSRF-Token",
        "jwt_secret_key",
        "Authorization",
        "set_cookie",
        "credentials",
        "api_key",
        "request_body",
        "payload",
    ],
)
def test_forbidden_metadata_keys_are_rejected(key: str) -> None:
    with pytest.raises(UnsafeAuditMetadataError, match="not allowed"):
        validate_audit_metadata({key: "value"})


def test_forbidden_keys_are_found_in_nested_values() -> None:
    with pytest.raises(UnsafeAuditMetadataError, match=r"changes\[0\]\.password"):
        validate_audit_metadata({"changes": [{"password": "hunter2"}]})


@pytest.mark.parametrize(
    "value",
    [
        "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl",
        "Bearer abc.def",
    ],
)
def test_credential_like_values_are_rejected(value: str) -> None:
    with pytest.raises(UnsafeAuditMetadataError, match="looks like a credential") as error:
        validate_audit_metadata({"note": value})

    assert value not in str(error.value)


def test_safe_identifiers_are_allowed() -> None:
    metadata = {
        "token_family_id": str(uuid4()),
        "token_version": 3,
        "reason": "reuse_detected",
        "roles": {"added": ["agent"], "removed": []},
        "client_ip_prefix": "203.0.113.0/24",
    }

    assert validate_audit_metadata(metadata) == metadata


def test_metadata_size_and_depth_are_bounded() -> None:
    with pytest.raises(UnsafeAuditMetadataError, match="bytes"):
        validate_audit_metadata({"note": "x" * 9_000})

    nested: dict[str, Any] = {"leaf": True}
    for _ in range(MAX_METADATA_DEPTH):
        nested = {"level": nested}
    with pytest.raises(UnsafeAuditMetadataError, match="levels deep"):
        validate_audit_metadata(nested)


def test_metadata_must_be_json() -> None:
    with pytest.raises(UnsafeAuditMetadataError, match="JSON"):
        validate_audit_metadata({"when": datetime.now(UTC)})


def test_model_refuses_unsafe_details() -> None:
    with pytest.raises(UnsafeAuditMetadataError):
        AuditEvent(event_code="auth.login_failed", details={"password": "hunter2"})


def test_audit_events_are_append_only() -> None:
    assert event.contains(AuditEvent, "before_update", _refuse_change)
    assert event.contains(AuditEvent, "before_delete", _refuse_change)
    with pytest.raises(AuditEventImmutableError):
        _refuse_change(None, None, AuditEvent(event_code="auth.login_failed"))  # type: ignore[arg-type]


def test_audit_create_validates_input() -> None:
    created = AuditEventCreate(
        event_code="staff.roles_changed",
        actor_id=uuid4(),
        entity_type="user",
        entity_id=uuid4(),
        metadata={"added": ["agent"]},
    )
    assert created.metadata == {"added": ["agent"]}

    for invalid in [
        {"event_code": "LoginFailed"},
        {"event_code": "auth"},
        {"event_code": "auth.login_failed", "entity_type": "user"},
        {"event_code": "auth.login_failed", "metadata": {"refresh_token": "x"}},
        {"event_code": "auth.login_failed", "unexpected": "x"},
    ]:
        with pytest.raises(ValidationError):
            AuditEventCreate.model_validate(invalid)


def test_audit_public_reads_from_the_model() -> None:
    audit_event = AuditEvent(
        id=uuid4(),
        event_code="auth.login_succeeded",
        actor_id=uuid4(),
        occurred_at=datetime(2026, 11, 3, tzinfo=UTC),
        request_id="req-1",
        details={"client_ip_prefix": "203.0.113.0/24"},
    )

    public = AuditEventPublic.model_validate(audit_event).model_dump()

    assert public["metadata"] == {"client_ip_prefix": "203.0.113.0/24"}
    assert public["event_code"] == "auth.login_succeeded"
    assert "details" not in public


# --- Catalog event allow-lists ----------------------------------------------------------

CATALOG_EVENT_PREFIXES = (
    "property.",
    "unit.",
    "media.",
    "document.",
    "contact.",
    "reference_data.",
)
SAMPLE_VALUES: dict[MetadataKind, Any] = {
    MetadataKind.ID: str(uuid4()),
    MetadataKind.ID_LIST: [str(uuid4()), str(uuid4())],
    MetadataKind.COUNT: 3,
    MetadataKind.FIELD_NAMES: ["name", "address_line_1"],
    MetadataKind.CODE: "title_deed",
    MetadataKind.MEDIA_TYPE: "image/webp",
}


def test_every_catalog_event_has_a_metadata_allow_list() -> None:
    catalog = {code for code in AuditEventCode if code.value.startswith(CATALOG_EVENT_PREFIXES)}

    assert catalog == set(EVENT_METADATA_SCHEMAS)
    for code in (
        "property.created",
        "property.updated",
        "property.archived",
        "property.restored",
        "property.owner_added",
        "unit.created",
        "media.uploaded",
        "document.uploaded",
    ):
        assert AuditEventCode(code) in EVENT_METADATA_SCHEMAS


def test_allow_listed_keys_pass_the_deny_list() -> None:
    for schema in EVENT_METADATA_SCHEMAS.values():
        for key in schema:
            validate_audit_metadata({key: 1})


@pytest.mark.parametrize("code", list(EVENT_METADATA_SCHEMAS), ids=str)
def test_catalog_events_accept_their_allow_listed_metadata(code: AuditEventCode) -> None:
    metadata = {key: SAMPLE_VALUES[kind] for key, kind in EVENT_METADATA_SCHEMAS[code].items()}

    created = AuditEventCreate(
        event_code=code, entity_type="property", entity_id=uuid4(), metadata=metadata
    )

    assert created.metadata == metadata


@pytest.mark.parametrize(
    "key",
    [
        "email",
        "telephone",
        "address",
        "notes",
        "internal_notes",
        "filename",
        "storage_key",
        "title",
    ],
)
def test_catalog_events_refuse_private_keys(key: str) -> None:
    with pytest.raises(UnsafeAuditMetadataError, match="not allowed for property.updated"):
        validate_event_metadata("property.updated", {key: "x"})


@pytest.mark.parametrize(
    ("code", "metadata"),
    [
        ("property.updated", {"changed_fields": ["owner@example.com"]}),
        ("property.updated", {"changed_fields": "city"}),
        ("property.updated", {"version": -1}),
        ("property.updated", {"version": True}),
        ("property.owner_added", {"contact_id": "Jane Owner"}),
        ("media.reordered", {"media_ids": [str(uuid4())] * (MAX_METADATA_LIST_ITEMS + 1)}),
        ("media.uploaded", {"media_type": "image/png; name=../../etc/passwd"}),
        ("document.uploaded", {"category": "Lease for 12 Main St"}),
    ],
)
def test_catalog_events_refuse_free_text_values(code: str, metadata: dict[str, Any]) -> None:
    with pytest.raises(UnsafeAuditMetadataError, match="must be") as error:
        validate_event_metadata(code, metadata)

    for value in metadata.values():
        if isinstance(value, str):
            assert value not in str(error.value)


def test_audit_create_applies_the_catalog_allow_list() -> None:
    with pytest.raises(ValidationError):
        AuditEventCreate(event_code="contact.created", metadata={"email": "owner@example.com"})


def test_events_without_an_allow_list_use_the_deny_list_only() -> None:
    validate_event_metadata("staff.roles_changed", {"added": ["agent"]})
    validate_event_metadata("not.registered", {"anything": "goes"})
