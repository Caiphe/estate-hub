"""Property ownership: share arithmetic, service rules, privacy, and concurrency."""

import asyncio
import json
import uuid
from datetime import date
from decimal import Decimal
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
    CatalogConflictError,
    CatalogError,
    CatalogNotFoundError,
    CatalogValidationError,
    DependencyConflictError,
    DuplicateReferenceError,
    InvalidRelationshipError,
)
from app.contacts.service import ContactService
from app.properties.constants import PropertyStatus
from app.properties.ownership import OwnershipService
from app.properties.schemas import OwnershipCreate, OwnershipUpdate, owners_view
from app.properties.shares import ShareSpan, peak_known_share, share_summary

D = Decimal


def span(share: str | None, start: date | None = None, end: date | None = None) -> ShareSpan:
    return ShareSpan(D(share) if share else None, start, end)


# --- Share arithmetic -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spans", "peak"),
    [
        ([], "0"),
        ([span("60"), span("40")], "100"),
        ([span("60"), span(None), span("50")], "110"),
        # Sequential ownership: each owner held 100%, never at the same time.
        (
            [
                span("100", date(2010, 1, 1), date(2019, 12, 31)),
                span("100", date(2020, 1, 1)),
            ],
            "100",
        ),
        # Overlapping by one day.
        (
            [
                span("100", date(2010, 1, 1), date(2020, 1, 1)),
                span("50", date(2020, 1, 1)),
            ],
            "150",
        ),
        # An undated link overlaps everything.
        ([span("70"), span("40", date(2030, 1, 1))], "110"),
        ([span("33.33"), span("33.33"), span("33.34")], "100.00"),
    ],
)
def test_peak_known_share(spans: list[ShareSpan], peak: str) -> None:
    assert peak_known_share(spans) == D(peak)


def test_share_summary_never_assumes_unknown_shares() -> None:
    today = date(2026, 11, 4)

    partial = share_summary([span("60"), span(None)], today)
    full = share_summary([span("60"), span("40"), span("10", end=date(2020, 1, 1))], today)

    assert (partial.known_total, partial.unknown_count, partial.complete) == (D("60"), 1, False)
    assert (full.known_total, full.unknown_count, full.complete) == (D("100"), 0, True)


@pytest.mark.parametrize(
    "payload",
    [
        {"share_percentage": "0"},
        {"share_percentage": "100.01"},
        {"share_percentage": "12.345"},
        {"start_date": "2024-02-01", "end_date": "2024-01-31"},
        {"start_date": "2024-02-30"},
        {"archived_at": "2024-01-01T00:00:00Z"},
        {"property_id": str(uuid.uuid4())},
    ],
)
def test_create_schema_rejects_invalid_ownership(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        OwnershipCreate.model_validate({"contact_id": str(uuid.uuid4())} | payload)


def test_share_percentage_is_an_exact_decimal() -> None:
    created = OwnershipCreate.model_validate(
        {"contact_id": str(uuid.uuid4()), "share_percentage": "33.33"}
    )

    assert created.share_percentage == D("33.33")


def test_update_schema_keeps_explicit_nulls_and_refuses_contact_changes() -> None:
    assert OwnershipUpdate.model_validate({"share_percentage": None}).changes() == {
        "share_percentage": None
    }
    with pytest.raises(ValidationError, match="At least one field"):
        OwnershipUpdate.model_validate({})
    with pytest.raises(ValidationError, match="Extra inputs"):
        OwnershipUpdate.model_validate({"contact_id": str(uuid.uuid4())})


# --- Service ----------------------------------------------------------------------------


@pytest.fixture
async def manager(session_factory: Sessions) -> Actor:
    return await actor_for(session_factory, "manager")


@pytest.fixture
async def property_id(session_factory: Sessions) -> uuid.UUID:
    return await create_property(session_factory)


async def add(
    session_factory: Sessions,
    actor: Actor,
    property_id: uuid.UUID,
    contact_id: uuid.UUID | None = None,
    **fields: Any,
) -> Any:
    contact_id = contact_id or await create_contact(session_factory)
    async with session_factory() as db:
        return await OwnershipService(db).add_owner(
            actor, property_id, OwnershipCreate(contact_id=contact_id, **fields)
        )


async def test_add_owner_records_an_id_only_audit_event(
    session_factory: Sessions, manager: Actor, property_id: uuid.UUID
) -> None:
    contact_id = await create_contact(
        session_factory, email="olive@example.com", telephone="+447700900123"
    )

    link = await add(
        session_factory, manager, property_id, contact_id, share_percentage=D("50"), notes="Note"
    )

    assert link.contact.display_name == "Olive Owner"
    [event] = await audit_events(session_factory, "property.owner_added")
    assert (event.entity_type, event.entity_id) == ("property", property_id)
    assert event.details == {"ownership_id": str(link.id), "contact_id": str(contact_id)}
    rendered = json.dumps(event.details)
    # The exact match above already excludes the share; these catch free-text leaks.
    for private in ("olive@example.com", "+447700900123", "Note"):
        assert private not in rendered


async def test_a_contact_may_own_many_properties_and_a_property_many_owners(
    session_factory: Sessions, manager: Actor, property_id: uuid.UUID
) -> None:
    contact_id = await create_contact(session_factory)
    other_property = await create_property(session_factory)

    await add(session_factory, manager, property_id, contact_id, share_percentage=D("50"))
    await add(session_factory, manager, property_id, share_percentage=D("50"))
    await add(session_factory, manager, other_property, contact_id)

    async with session_factory() as db:
        links, summary = await OwnershipService(db).list_owners(manager, property_id)
    assert len(links) == 2
    assert (summary.known_total, summary.complete) == (D("100"), True)


async def test_duplicate_current_link_is_rejected(
    session_factory: Sessions, manager: Actor, property_id: uuid.UUID
) -> None:
    contact_id = await create_contact(session_factory)
    link = await add(session_factory, manager, property_id, contact_id)

    with pytest.raises(DuplicateReferenceError) as error:
        await add(session_factory, manager, property_id, contact_id)
    assert error.value.fields == {"contact_id": ["This contact already owns the property."]}

    # Once the link has ended, the contact can be linked again.
    async with session_factory() as db:
        await OwnershipService(db).end_owner(manager, property_id, link.id)
    await add(session_factory, manager, property_id, contact_id)


async def test_database_rejects_a_second_current_link(
    session_factory: Sessions, manager: Actor, property_id: uuid.UUID
) -> None:
    link = await add(session_factory, manager, property_id)

    async with session_factory() as db:
        with pytest.raises(DBAPIError, match="uq_property_ownerships_current_link"):
            await db.execute(
                text(
                    "INSERT INTO property_ownerships (id, property_id, contact_id) "
                    "VALUES (gen_random_uuid(), :property_id, :contact_id)"
                ),
                {"property_id": property_id, "contact_id": link.contact_id},
            )


async def test_known_shares_cannot_exceed_100(
    session_factory: Sessions, manager: Actor, property_id: uuid.UUID
) -> None:
    first = await add(session_factory, manager, property_id, share_percentage=D("60"))
    await add(session_factory, manager, property_id)  # Unknown share: allowed, not counted.
    await add(session_factory, manager, property_id, share_percentage=D("40"))

    with pytest.raises(CatalogConflictError) as error:
        await add(session_factory, manager, property_id, share_percentage=D("0.01"))
    assert "share_percentage" in (error.value.fields or {})
    async with session_factory() as db:
        with pytest.raises(CatalogConflictError):
            await OwnershipService(db).update_owner(
                manager, property_id, first.id, OwnershipUpdate(share_percentage=D("60.01"))
            )

    # Once the first owner's ownership ends, a later owner may take its 60%.
    async with session_factory() as db:
        await OwnershipService(db).update_owner(
            manager, property_id, first.id, OwnershipUpdate(end_date=date(2024, 12, 31))
        )
    await add(
        session_factory, manager, property_id, share_percentage=D("60"), start_date=date(2025, 1, 1)
    )
    async with session_factory() as db:
        _, summary = await OwnershipService(db).list_owners(manager, property_id)
    # 40 + 60 known today, plus one unknown share: never reported as complete.
    assert (summary.known_total, summary.unknown_count, summary.complete) == (D("100"), 1, False)


async def test_update_checks_date_order_against_stored_dates(
    session_factory: Sessions, manager: Actor, property_id: uuid.UUID
) -> None:
    link = await add(session_factory, manager, property_id, start_date=date(2024, 6, 1))

    async with session_factory() as db:
        with pytest.raises(CatalogValidationError) as error:
            await OwnershipService(db).update_owner(
                manager, property_id, link.id, OwnershipUpdate(end_date=date(2024, 5, 31))
            )
    assert error.value.fields == {"end_date": ["end_date must be on or after start_date."]}

    async with session_factory() as db:
        updated = await OwnershipService(db).update_owner(
            manager,
            property_id,
            link.id,
            OwnershipUpdate(share_percentage=D("25"), end_date=date(2024, 6, 1)),
        )
    assert (updated.share_percentage, updated.end_date) == (D("25.00"), date(2024, 6, 1))
    [event] = await audit_events(session_factory, "property.owner_updated")
    assert event.details["changed_fields"] == ["end_date", "share_percentage"]


async def test_ended_links_are_final_history(
    session_factory: Sessions, manager: Actor, property_id: uuid.UUID
) -> None:
    link = await add(session_factory, manager, property_id)

    async with session_factory() as db:
        service = OwnershipService(db)
        ended = await service.end_owner(manager, property_id, link.id)
        again = await service.end_owner(manager, property_id, link.id)
        assert ended.archived_by_id == manager.user_id
        assert again.archived_at == ended.archived_at
        with pytest.raises(ArchivedRecordError):
            await service.update_owner(
                manager, property_id, link.id, OwnershipUpdate(notes="Late note")
            )
        current, _ = await service.list_owners(manager, property_id)
        history, _ = await service.list_owners(manager, property_id, include_ended=True)

    assert current == []
    assert [row.id for row in history] == [link.id]
    assert len(await audit_events(session_factory, "property.owner_removed")) == 1


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ("archived_contact", InvalidRelationshipError),
        ("missing_contact", InvalidRelationshipError),
        ("archived_property", ArchivedRecordError),
        ("missing_property", CatalogNotFoundError),
    ],
)
async def test_unusable_records_are_rejected(
    session_factory: Sessions, manager: Actor, setup: str, expected: type[CatalogError]
) -> None:
    property_id = await create_property(
        session_factory,
        status=PropertyStatus.ARCHIVED if setup == "archived_property" else PropertyStatus.ACTIVE,
    )
    contact_id = await create_contact(session_factory)
    if setup == "archived_contact":
        async with session_factory() as db:
            await ContactService(db).archive_contact(manager, contact_id)
    if setup == "missing_contact":
        contact_id = uuid.uuid4()
    if setup == "missing_property":
        property_id = uuid.uuid4()

    with pytest.raises(expected):
        await add(session_factory, manager, property_id, contact_id)
    assert await audit_events(session_factory, "property.owner_added") == []


async def test_links_under_another_property_are_not_found(
    session_factory: Sessions, manager: Actor, property_id: uuid.UUID
) -> None:
    link = await add(session_factory, manager, property_id)
    other = await create_property(session_factory)

    async with session_factory() as db:
        service = OwnershipService(db)
        with pytest.raises(CatalogNotFoundError):
            await service.end_owner(manager, other, link.id)
        with pytest.raises(CatalogNotFoundError):
            await service.update_owner(manager, other, link.id, OwnershipUpdate(notes="x"))


# --- Authorization and privacy ----------------------------------------------------------


async def test_ownership_permissions_by_role(
    session_factory: Sessions, manager: Actor, property_id: uuid.UUID
) -> None:
    link = await add(session_factory, manager, property_id)
    agent = await actor_for(session_factory, "agent")
    accountant = await actor_for(session_factory, "accountant")
    contact_id = await create_contact(session_factory)

    async with session_factory() as db:
        service = OwnershipService(db)
        links, _ = await service.list_owners(agent, property_id)
        assert [row.id for row in links] == [link.id]
        with pytest.raises(PermissionDeniedError):
            await service.add_owner(agent, property_id, OwnershipCreate(contact_id=contact_id))
        with pytest.raises(PermissionDeniedError):
            await service.end_owner(agent, property_id, link.id)
        with pytest.raises(PermissionDeniedError):
            await service.list_owners(accountant, property_id)


async def test_owner_contact_details_require_contacts_read(
    session_factory: Sessions, manager: Actor, property_id: uuid.UUID
) -> None:
    await add(session_factory, manager, property_id)
    # An actor with ownership read but not contacts read (no built-in role is shaped
    # this way today; the view must not rely on that).
    restricted = Actor(user_id=manager.user_id, role_codes=frozenset(), active=True)

    async with session_factory() as db:
        links, summary = await OwnershipService(db).list_owners(manager, property_id)

    full = owners_view(manager, links, summary).items[0]
    redacted = owners_view(restricted, links, summary).items[0]
    assert full.contact is not None and full.contact.email is not None
    assert redacted.contact is None
    assert redacted.contact_display_name == "Olive Owner"
    assert "@" not in redacted.model_dump_json()


# --- Concurrency ------------------------------------------------------------------------


async def test_concurrent_additions_cannot_exceed_100(
    session_factory: Sessions, manager: Actor, property_id: uuid.UUID
) -> None:
    contacts = [await create_contact(session_factory) for _ in range(4)]

    async def attempt(contact_id: uuid.UUID) -> object:
        async with session_factory() as db:
            return await OwnershipService(db).add_owner(
                manager,
                property_id,
                OwnershipCreate(contact_id=contact_id, share_percentage=D("40")),
            )

    results = await asyncio.gather(*map(attempt, contacts), return_exceptions=True)

    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(results) - len(failures) == 2
    assert all(isinstance(f, CatalogConflictError) for f in failures)
    async with session_factory() as db:
        assert await db.scalar(text("SELECT sum(share_percentage) FROM property_ownerships")) == D(
            "80.00"
        )


async def test_concurrent_duplicate_links_resolve_to_one(
    session_factory: Sessions, manager: Actor, property_id: uuid.UUID
) -> None:
    contact_id = await create_contact(session_factory)

    results = await asyncio.gather(
        *(add(session_factory, manager, property_id, contact_id) for _ in range(3)),
        return_exceptions=True,
    )

    assert sum(not isinstance(r, BaseException) for r in results) == 1
    assert all(
        isinstance(r, DuplicateReferenceError) for r in results if isinstance(r, BaseException)
    )


async def test_archiving_a_contact_races_safely_with_adding_it_as_owner(
    session_factory: Sessions, manager: Actor, property_id: uuid.UUID
) -> None:
    contact_id = await create_contact(session_factory)

    async def archive() -> object:
        async with session_factory() as db:
            return await ContactService(db).archive_contact(manager, contact_id)

    results = await asyncio.gather(
        archive(), add(session_factory, manager, property_id, contact_id), return_exceptions=True
    )

    # Exactly one wins; never an archived contact that still owns the property.
    archived, added = results
    assert isinstance(archived, DependencyConflictError) != isinstance(
        added, InvalidRelationshipError
    )
    async with session_factory() as db:
        status = await db.scalar(
            text("SELECT status FROM contacts WHERE id = :id"), {"id": contact_id}
        )
        links = await db.scalar(text("SELECT count(*) FROM property_ownerships"))
    assert (status, links) in {("archived", 0), ("active", 1)}
