"""Contacts: normalization, validation, constraints, service rules, and authorization."""

import json
import uuid
from datetime import date
from typing import Any

import pytest
from auth_support import Sessions
from catalog_support import actor_for, audit_events, create_contact, create_property
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.auth.errors import PermissionDeniedError
from app.auth.policy import Actor
from app.catalog.errors import (
    ArchivedRecordError,
    CatalogNotFoundError,
    CatalogValidationError,
    DependencyConflictError,
    StaleVersionError,
)
from app.contacts.constants import ContactKind, ContactStatus
from app.contacts.models import Contact
from app.contacts.normalization import InvalidTelephoneError, normalize_telephone
from app.contacts.schemas import (
    ContactCreate,
    ContactDetail,
    ContactListQuery,
    ContactSort,
    ContactSummary,
    ContactUpdate,
)
from app.contacts.service import ContactService
from app.properties.ownership import OwnershipService
from app.properties.schemas import OwnershipCreate

PERSON: dict[str, Any] = {"kind": "person", "display_name": "Olive Owner"}
PRIVATE_VALUES = ("olive@example.com", "+447700900123", "Keys under the mat", "1 Private Road")


# --- Normalization ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+44 7700 900123", "+447700900123"),
        ("0044 (0)7700-900.123", "+4407700900123"),
        ("(555) 010-9999", "5550109999"),
        ("  +1 202 555 0143 ", "+12025550143"),
    ],
)
def test_telephones_are_normalized(raw: str, expected: str) -> None:
    assert normalize_telephone(raw) == expected


@pytest.mark.parametrize("raw", ["12345", "+44 7700 abc", "1" * 16, "++447700900123", "ext 12"])
def test_invalid_telephones_are_rejected_without_echo(raw: str) -> None:
    with pytest.raises(InvalidTelephoneError) as error:
        normalize_telephone(raw)

    assert raw not in str(error.value)


def test_create_schema_normalizes_contact_fields() -> None:
    created = ContactCreate.model_validate(
        PERSON
        | {
            "display_name": "  Olive   Owner ",
            "organization_name": "  ",
            "email": " Olive@Example.COM ",
            "telephone": "+44 7700 900123",
            "address_line_1": " 1  Private Road",
            "locality": "Bath",
            "postal_code": " ba1 1aa ",
            "country_code": "gb",
            "internal_notes": "  ",
        }
    )

    assert created.display_name == "Olive Owner"
    assert created.organization_name is None
    assert created.email == "olive@example.com"
    assert created.telephone == "+447700900123"
    assert created.address_line_1 == "1 Private Road"
    assert (created.postal_code, created.country_code) == ("BA1 1AA", "GB")
    assert created.internal_notes is None


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "Provide an email, a telephone number, or an address"),
        (
            {"kind": "organization", "organization_name": "Acme", "email": "a@example.com"},
            "Only people have an organization name",
        ),
        ({"email": "a@example.com", "alternative_telephone": "+447700900123"}, "main telephone"),
        (
            {"telephone": "+447700900123", "alternative_telephone": "+44 7700 900123"},
            "Must differ",
        ),
        ({"address_line_1": "1 Private Road"}, "Required when a correspondence address"),
        ({"email": "not-an-email"}, "email"),
        ({"telephone": "abc"}, "telephone"),
        ({"email": "a@example.com", "country_code": "GBR"}, "country_code"),
        ({"email": "a@example.com", "id": str(uuid.uuid4())}, "Extra inputs"),
        ({"email": "a@example.com", "status": "archived"}, "Extra inputs"),
        ({"email": "a@example.com", "version": 3}, "Extra inputs"),
    ],
)
def test_create_schema_rejects_invalid_contacts(payload: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError) as error:
        ContactCreate.model_validate(PERSON | payload)

    assert message in str(error.value)


def test_validation_errors_never_echo_private_input() -> None:
    with pytest.raises(ValidationError) as error:
        ContactCreate.model_validate(
            PERSON
            | {"email": "olive@", "telephone": "+44 7700 abc", "internal_notes": "x" * 10_001}
        )

    rendered = str(error.value)
    assert "olive@" not in rendered
    assert "7700 abc" not in rendered


def test_update_schema_distinguishes_omitted_from_null() -> None:
    update = ContactUpdate.model_validate({"version": 2, "email": None, "region": "Avon"})

    assert update.changes() == {"email": None, "region": "Avon"}
    with pytest.raises(ValidationError, match="At least one field"):
        ContactUpdate.model_validate({"version": 2})
    with pytest.raises(ValidationError, match="display_name cannot be null"):
        ContactUpdate.model_validate({"version": 2, "display_name": None})
    for forbidden in ("kind", "status", "archived_at", "created_by_id"):
        with pytest.raises(ValidationError, match="Extra inputs"):
            ContactUpdate.model_validate({"version": 2, forbidden: "x"})


def test_summary_omits_notes_and_address() -> None:
    assert "internal_notes" not in ContactSummary.model_fields
    assert "address_line_1" not in ContactSummary.model_fields
    assert "internal_notes" in ContactDetail.model_fields


# --- Database constraints ---------------------------------------------------------------


async def insert_contact(session_factory: Sessions, **columns: str) -> None:
    values = {
        "id": "gen_random_uuid()",
        "kind": "'person'",
        "display_name": "'Olive Owner'",
        "email": "'olive@example.com'",
    } | columns
    async with session_factory() as db:
        columns_sql, values_sql = ", ".join(values), ", ".join(values.values())
        await db.execute(text(f"INSERT INTO contacts ({columns_sql}) VALUES ({values_sql})"))
        await db.commit()


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"email": "NULL"}, "ck_contacts_has_contact_method"),
        ({"email": "'Olive@Example.com'"}, "ck_contacts_email_normalized"),
        ({"email": "'not-an-email'"}, "ck_contacts_email_normalized"),
        ({"telephone": "'+44 7700 900123'"}, "ck_contacts_telephone_format"),
        ({"alternative_telephone": "'+447700900123'"}, "ck_contacts_alternative_telephone"),
        (
            {"telephone": "'+447700900123'", "alternative_telephone": "'+447700900123'"},
            "ck_contacts_alternative_telephone_secondary",
        ),
        (
            {"kind": "'organization'", "organization_name": "'Acme'"},
            "ck_contacts_organization_name_for_people",
        ),
        ({"kind": "'robot'"}, "ck_contacts_contact_kind"),
        ({"display_name": "'  '"}, "ck_contacts_display_name_normalized"),
        ({"address_line_1": "'1 Road'"}, "ck_contacts_address_complete"),
        ({"region": "'Somerset'"}, "ck_contacts_address_complete"),
        (
            {"address_line_1": "'1 Road'", "locality": "'Bath'", "country_code": "'gb'"},
            "ck_contacts_country_code_format",
        ),
        ({"internal_notes": "' '"}, "ck_contacts_internal_notes_not_blank"),
        ({"status": "'archived'"}, "ck_contacts_archived_state_consistent"),
        ({"version": "0"}, "ck_contacts_version_positive"),
    ],
)
async def test_database_rejects_invalid_contacts(
    session_factory: Sessions, columns: dict[str, str], constraint: str
) -> None:
    with pytest.raises(DBAPIError) as error:
        await insert_contact(session_factory, **columns)

    assert constraint in str(error.value)


async def test_address_only_contacts_are_valid(session_factory: Sessions) -> None:
    await insert_contact(
        session_factory,
        email="NULL",
        address_line_1="'1 Private Road'",
        locality="'Bath'",
        country_code="'GB'",
    )


# --- Service ----------------------------------------------------------------------------


@pytest.fixture
async def manager(session_factory: Sessions) -> Actor:
    return await actor_for(session_factory, "manager")


def private_create() -> ContactCreate:
    return ContactCreate.model_validate(
        PERSON
        | {
            "email": "olive@example.com",
            "telephone": "+447700900123",
            "address_line_1": "1 Private Road",
            "locality": "Bath",
            "country_code": "GB",
            "internal_notes": "Keys under the mat",
        }
    )


async def test_create_records_an_audit_event_without_personal_data(
    session_factory: Sessions, manager: Actor
) -> None:
    async with session_factory() as db:
        contact = await ContactService(db).create_contact(
            manager, private_create(), request_id="req-1"
        )

    assert contact.version == 1
    assert contact.status == ContactStatus.ACTIVE
    assert contact.created_by_id == manager.user_id
    [event] = await audit_events(session_factory, "contact.created")
    assert (event.entity_type, event.entity_id, event.actor_id) == (
        "contact",
        contact.id,
        manager.user_id,
    )
    assert event.details == {"kind": "person"}
    assert not any(value in json.dumps(event.details) for value in PRIVATE_VALUES)


async def test_update_applies_changes_and_increments_version(
    session_factory: Sessions, manager: Actor
) -> None:
    contact_id = await create_contact(session_factory, telephone="+447700900123")

    async with session_factory() as db:
        updated = await ContactService(db).update_contact(
            manager,
            contact_id,
            ContactUpdate.model_validate(
                {"version": 1, "email": None, "telephone": "+44 7700 900999"}
            ),
        )

    assert updated.email is None
    assert updated.telephone == "+447700900999"
    assert updated.version == 2
    [event] = await audit_events(session_factory, "contact.updated")
    assert event.details == {"changed_fields": ["email", "telephone"], "version": 2}


async def test_stale_update_is_rejected_without_changes(
    session_factory: Sessions, manager: Actor
) -> None:
    contact_id = await create_contact(session_factory)
    async with session_factory() as db:
        service = ContactService(db)
        await service.update_contact(
            manager,
            contact_id,
            ContactUpdate.model_validate({"version": 1, "organization_name": "Acme Lettings"}),
        )

    async with session_factory() as db:
        with pytest.raises(StaleVersionError):
            await ContactService(db).update_contact(
                manager,
                contact_id,
                ContactUpdate.model_validate({"version": 1, "display_name": "Stale Name"}),
            )

    async with session_factory() as db:
        assert (await ContactService(db).get_contact(manager, contact_id)).display_name == (
            "Olive Owner"
        )
    assert len(await audit_events(session_factory, "contact.updated")) == 1


async def test_update_rechecks_rules_against_the_stored_contact(
    session_factory: Sessions, manager: Actor
) -> None:
    contact_id = await create_contact(session_factory)

    async with session_factory() as db:
        with pytest.raises(CatalogValidationError) as error:
            await ContactService(db).update_contact(
                manager, contact_id, ContactUpdate.model_validate({"version": 1, "email": None})
            )

    assert error.value.fields == {
        "__root__": ["Provide an email, a telephone number, or an address."]
    }
    assert await audit_events(session_factory, "contact.updated") == []


async def test_unchanged_update_writes_no_event(session_factory: Sessions, manager: Actor) -> None:
    contact_id = await create_contact(session_factory, display_name="Olive Owner")

    async with session_factory() as db:
        result = await ContactService(db).update_contact(
            manager,
            contact_id,
            ContactUpdate.model_validate({"version": 1, "display_name": " Olive  Owner "}),
        )

    assert result.version == 1
    assert await audit_events(session_factory, "contact.updated") == []


async def test_archive_and_restore(session_factory: Sessions, manager: Actor) -> None:
    contact_id = await create_contact(session_factory)

    async with session_factory() as db:
        service = ContactService(db)
        archived = await service.archive_contact(manager, contact_id)
        again = await service.archive_contact(manager, contact_id)
        assert archived.status == ContactStatus.ARCHIVED
        assert archived.archived_by_id == manager.user_id
        assert again.version == archived.version

        with pytest.raises(ArchivedRecordError):
            await service.update_contact(
                manager,
                contact_id,
                ContactUpdate.model_validate({"version": archived.version, "region": "Avon"}),
            )

        restored = await service.restore_contact(manager, contact_id)
        assert restored.status == ContactStatus.ACTIVE
        assert restored.archived_at is None

    codes = [event.event_code for event in await audit_events(session_factory)]
    assert codes.count("contact.archived") == 1
    assert codes.count("contact.restored") == 1


async def test_contact_with_current_ownership_cannot_be_archived(
    session_factory: Sessions, manager: Actor
) -> None:
    contact_id = await create_contact(session_factory)
    property_id = await create_property(session_factory)
    async with session_factory() as db:
        link = await OwnershipService(db).add_owner(
            manager, property_id, OwnershipCreate(contact_id=contact_id)
        )

    async with session_factory() as db:
        with pytest.raises(DependencyConflictError):
            await ContactService(db).archive_contact(manager, contact_id)

    # Ownership that ended in the real world, or an ended link, no longer blocks.
    async with session_factory() as db:
        await db.execute(
            text("UPDATE property_ownerships SET end_date = :day WHERE id = :id"),
            {"day": date(2020, 1, 1), "id": link.id},
        )
        await db.commit()
    async with session_factory() as db:
        archived = await ContactService(db).archive_contact(manager, contact_id)
    assert archived.is_archived


async def test_missing_contacts_are_not_found(session_factory: Sessions, manager: Actor) -> None:
    async with session_factory() as db:
        with pytest.raises(CatalogNotFoundError):
            await ContactService(db).get_contact(manager, uuid.uuid4())


async def test_listing_filters_searches_sorts_and_pages(
    session_factory: Sessions, manager: Actor
) -> None:
    await create_contact(
        session_factory, display_name="beta Builders", kind=ContactKind.ORGANIZATION
    )
    await create_contact(session_factory, display_name="Alpha Owner", telephone="+447700900123")
    archived_id = await create_contact(session_factory, display_name="Archived Owner")
    async with session_factory() as db:
        await ContactService(db).archive_contact(manager, archived_id)

    async def names(**query: Any) -> tuple[list[str], int]:
        async with session_factory() as db:
            rows, total = await ContactService(db).list_contacts(
                manager, ContactListQuery.model_validate(query)
            )
        return [row.display_name for row in rows], total

    assert await names() == (["Alpha Owner", "beta Builders"], 2)
    assert await names(include_archived=True) == (
        ["Alpha Owner", "Archived Owner", "beta Builders"],
        3,
    )
    assert await names(kind="organization") == (["beta Builders"], 1)
    assert await names(q="ALPHA") == (["Alpha Owner"], 1)
    assert await names(q="7700 900") == (["Alpha Owner"], 1)
    assert await names(q="100%") == ([], 0)
    assert await names(sort=ContactSort.DISPLAY_NAME_DESC) == (
        ["beta Builders", "Alpha Owner"],
        2,
    )
    first, total = await names(limit=1)
    second, _ = await names(limit=1, offset=1)
    assert (first, second, total) == (["Alpha Owner"], ["beta Builders"], 2)


@pytest.mark.parametrize("role", ["accountant"])
async def test_roles_without_contact_permissions_are_denied(
    session_factory: Sessions, role: str
) -> None:
    actor = await actor_for(session_factory, role)
    contact_id = await create_contact(session_factory)

    async with session_factory() as db:
        service = ContactService(db)
        with pytest.raises(PermissionDeniedError):
            await service.get_contact(actor, contact_id)
        with pytest.raises(PermissionDeniedError):
            await service.list_contacts(actor, ContactListQuery())
        with pytest.raises(PermissionDeniedError):
            await service.create_contact(actor, private_create())
        with pytest.raises(PermissionDeniedError):
            await service.archive_contact(actor, contact_id)


async def test_agents_manage_contacts(session_factory: Sessions) -> None:
    agent = await actor_for(session_factory, "agent")

    async with session_factory() as db:
        created = await ContactService(db).create_contact(agent, private_create())

    assert isinstance(created, Contact)


async def test_failed_mutation_leaves_no_partial_record(
    session_factory: Sessions, manager: Actor
) -> None:
    # A manager is allowed, but the contact row rejects a value the schema let through.
    bad = private_create().model_copy(update={"country_code": "G1"})

    async with session_factory() as db:
        with pytest.raises(DBAPIError):
            await ContactService(db).create_contact(manager, bad)

    async with session_factory() as db:
        assert await db.scalar(text("SELECT count(*) FROM contacts")) == 0
    assert await audit_events(session_factory, "contact.created") == []
