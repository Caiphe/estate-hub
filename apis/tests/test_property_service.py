"""Property service: create, update, archive/restore, directory search, and permissions."""

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from auth_support import Sessions
from catalog_support import actor_for, audit_events, create_contact
from sqlalchemy import text

from app.auth.errors import PermissionDeniedError
from app.auth.policy import Actor
from app.catalog.errors import (
    ArchivedRecordError,
    CatalogConflictError,
    CatalogNotFoundError,
    CatalogValidationError,
    DependencyConflictError,
    InvalidRelationshipError,
    StaleVersionError,
)
from app.catalog.models import Amenity, PropertySubtype, PropertyType
from app.contacts.service import ContactService
from app.properties.constants import ManagementMode, PropertyStatus
from app.properties.schemas import (
    PropertyCreate,
    PropertyDetail,
    PropertyListQuery,
    PropertySort,
    PropertyUpdate,
)
from app.properties.service import PropertyService
from app.properties.units import UnitService


@dataclass(frozen=True)
class Reference:
    residential: uuid.UUID
    apartment: uuid.UUID
    house: uuid.UUID
    commercial: uuid.UUID
    shop: uuid.UUID
    pool: uuid.UUID
    garden: uuid.UUID


@pytest.fixture
async def ref(session_factory: Sessions) -> Reference:
    async with session_factory() as db:
        residential = PropertyType(name="Residential")
        residential.subtypes = [PropertySubtype(name="Apartment"), PropertySubtype(name="House")]
        commercial = PropertyType(name="Commercial")
        commercial.subtypes = [PropertySubtype(name="Shop")]
        pool, garden = Amenity(name="Pool"), Amenity(name="Garden")
        db.add_all([residential, commercial, pool, garden])
        await db.commit()
        return Reference(
            residential.id,
            residential.subtypes[0].id,
            residential.subtypes[1].id,
            commercial.id,
            commercial.subtypes[0].id,
            pool.id,
            garden.id,
        )


@pytest.fixture
async def manager(session_factory: Sessions) -> Actor:
    return await actor_for(session_factory, "manager")


def payload(ref: Reference, **overrides: Any) -> PropertyCreate:
    values: dict[str, Any] = {
        "name": "Rose Cottage",
        "property_type_id": ref.residential,
        "property_subtype_id": ref.house,
        "address_line_1": "1 High Street",
        "locality": "Bath",
        "region": "Somerset",
        "country_code": "GB",
    }
    return PropertyCreate.model_validate(values | overrides)


async def create(session_factory: Sessions, actor: Actor, data: PropertyCreate) -> PropertyDetail:
    async with session_factory() as db:
        return await PropertyService(db).create_property(actor, data, request_id="req-1")


async def update(
    session_factory: Sessions, actor: Actor, detail: PropertyDetail, **fields: Any
) -> PropertyDetail:
    async with session_factory() as db:
        return await PropertyService(db).update_property(
            actor, detail.id, PropertyUpdate.model_validate({"version": detail.version} | fields)
        )


async def counts(session_factory: Sessions) -> dict[str, int]:
    async with session_factory() as db:
        return {
            table: int(await db.scalar(text(f"SELECT count(*) FROM {table}")) or 0)
            for table in ("properties", "property_ownerships", "units", "property_amenities")
        }


# --- Create -----------------------------------------------------------------------------


async def test_create_generates_server_fields_and_audits(
    session_factory: Sessions, ref: Reference, manager: Actor
) -> None:
    detail = await create(session_factory, manager, payload(ref, amenity_ids=[ref.pool]))

    assert detail.reference.startswith("PR-")
    assert (detail.status, detail.management_mode, detail.version) == (
        PropertyStatus.DRAFT,
        ManagementMode.WHOLE,
        1,
    )
    assert detail.created_by_id == manager.user_id
    assert detail.property_subtype is not None and detail.property_subtype.name == "House"
    assert [a.name for a in detail.amenities] == ["Pool"]
    [event] = await audit_events(session_factory, "property.created")
    assert (event.entity_id, event.request_id) == (detail.id, "req-1")
    assert event.details == {"amenity_count": 1, "owner_count": 0, "unit_count": 0}


async def test_references_are_unique_across_concurrent_creates(
    session_factory: Sessions, ref: Reference, manager: Actor
) -> None:
    created = await asyncio.gather(
        *(create(session_factory, manager, payload(ref, name=f"P{i}")) for i in range(8))
    )

    assert len({detail.reference for detail in created}) == 8


async def test_create_with_owners_and_units_is_atomic(
    session_factory: Sessions, ref: Reference, manager: Actor
) -> None:
    olive = await create_contact(session_factory)
    oscar = await create_contact(session_factory, display_name="Oscar Owner")

    detail = await create(
        session_factory,
        manager,
        payload(
            ref,
            name="Rose Court",
            property_subtype_id=ref.apartment,
            management_mode="units",
            owners=[
                {"contact_id": str(olive), "share_percentage": "60"},
                {"contact_id": str(oscar), "share_percentage": "40"},
            ],
            units=[
                {"identifier": "Flat 2", "property_subtype_id": str(ref.apartment)},
                {"identifier": "Flat 1", "amenity_ids": [str(ref.garden)]},
            ],
        ),
    )

    assert [u.identifier for u in detail.units] == ["Flat 1", "Flat 2"]
    assert detail.owners is not None and detail.owners.shares.complete
    codes = [event.event_code for event in await audit_events(session_factory)]
    assert codes.count("property.owner_added") == 2 and codes.count("unit.created") == 2


@pytest.mark.parametrize(
    ("overrides", "error", "field"),
    [
        ({"property_type_id": uuid.uuid4()}, InvalidRelationshipError, "property_type_id"),
        ({"property_subtype_id": "shop"}, InvalidRelationshipError, "property_subtype_id"),
        ({"amenity_ids": ["missing"]}, InvalidRelationshipError, "amenity_ids"),
        (
            {
                "management_mode": "units",
                "units": [{"identifier": "A", "property_subtype_id": "shop"}],
            },
            InvalidRelationshipError,
            "units.0.property_subtype_id",
        ),
        (
            {
                "management_mode": "units",
                "units": [{"identifier": "A"}, {"identifier": "B", "amenity_ids": ["missing"]}],
            },
            InvalidRelationshipError,
            "units.1.amenity_ids",
        ),
        (
            {"owners": [{"contact_id": "missing"}]},
            InvalidRelationshipError,
            "owners.0.contact_id",
        ),
        (
            {
                "owners": [
                    {"contact_id": "olive", "share_percentage": "70"},
                    {"contact_id": "oscar", "share_percentage": "40"},
                ]
            },
            CatalogConflictError,
            "owners",
        ),
    ],
)
async def test_failed_creates_leave_nothing_behind(
    session_factory: Sessions,
    ref: Reference,
    manager: Actor,
    overrides: dict[str, Any],
    error: type[Exception],
    field: str,
) -> None:
    contacts = {
        "olive": await create_contact(session_factory),
        "oscar": await create_contact(session_factory),
        "missing": uuid.uuid4(),
        "shop": ref.shop,
    }

    def resolve(value: Any) -> Any:
        if isinstance(value, str) and value in contacts:
            return contacts[value]
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if isinstance(value, dict):
            return {key: resolve(item) for key, item in value.items()}
        return value

    with pytest.raises(error) as raised:
        await create(session_factory, manager, payload(ref, **resolve(overrides)))

    assert field in (raised.value.fields or {})  # type: ignore[attr-defined]
    assert await counts(session_factory) == {
        "properties": 0,
        "property_ownerships": 0,
        "units": 0,
        "property_amenities": 0,
    }
    assert await audit_events(session_factory) == []


async def test_disabled_references_cannot_be_newly_assigned(
    session_factory: Sessions, ref: Reference, manager: Actor
) -> None:
    async with session_factory() as db:
        await db.execute(
            text("UPDATE property_subtypes SET is_active = false WHERE name = 'House'")
        )
        await db.execute(text("UPDATE amenities SET is_active = false WHERE name = 'Pool'"))
        await db.commit()

    for data in (payload(ref), payload(ref, property_subtype_id=None, amenity_ids=[ref.pool])):
        with pytest.raises(InvalidRelationshipError):
            await create(session_factory, manager, data)

    async with session_factory() as db:
        await db.execute(
            text("UPDATE property_types SET is_active = false WHERE name = 'Commercial'")
        )
        await db.commit()
    with pytest.raises(InvalidRelationshipError):
        await create(
            session_factory,
            manager,
            payload(ref, property_type_id=ref.commercial, property_subtype_id=None),
        )


async def test_archived_contacts_cannot_become_initial_owners(
    session_factory: Sessions, ref: Reference, manager: Actor
) -> None:
    contact_id = await create_contact(session_factory)
    async with session_factory() as db:
        await ContactService(db).archive_contact(manager, contact_id)

    with pytest.raises(InvalidRelationshipError):
        await create(session_factory, manager, payload(ref, owners=[{"contact_id": contact_id}]))


# --- Update -----------------------------------------------------------------------------


async def test_update_changes_fields_and_versions(
    session_factory: Sessions, ref: Reference, manager: Actor
) -> None:
    detail = await create(session_factory, manager, payload(ref))

    updated = await update(
        session_factory,
        manager,
        detail,
        name="Rose Cottage East",
        postal_code="ba1 1aa",
        bedrooms=3,
    )
    unchanged = await update(session_factory, manager, updated, name="Rose Cottage East")
    amenity_only = await update(session_factory, manager, unchanged, amenity_ids=[ref.garden])

    assert (updated.name, updated.postal_code, updated.bedrooms, updated.version) == (
        "Rose Cottage East",
        "BA1 1AA",
        3,
        2,
    )
    assert unchanged.version == 2
    assert amenity_only.version == 3 and [a.name for a in amenity_only.amenities] == ["Garden"]
    events = await audit_events(session_factory, "property.updated")
    assert [e.details for e in events] == [
        {"changed_fields": ["bedrooms", "name", "postal_code"], "version": 2},
        {"changed_fields": ["amenity_ids"], "version": 3},
    ]
    assert "Rose" not in json.dumps([e.details for e in events])


async def test_stale_updates_never_overwrite(
    session_factory: Sessions, ref: Reference, manager: Actor
) -> None:
    detail = await create(session_factory, manager, payload(ref))
    await update(session_factory, manager, detail, name="Newer name")

    with pytest.raises(StaleVersionError):
        await update(session_factory, manager, detail, name="Stale name")

    async with session_factory() as db:
        assert (await PropertyService(db).get_property(manager, detail.id)).name == "Newer name"


async def test_concurrent_updates_with_one_version_let_one_win(
    session_factory: Sessions, ref: Reference, manager: Actor
) -> None:
    detail = await create(session_factory, manager, payload(ref))

    results = await asyncio.gather(
        *(update(session_factory, manager, detail, name=f"Name {i}") for i in range(4)),
        return_exceptions=True,
    )

    winners = [r for r in results if isinstance(r, PropertyDetail)]
    assert len(winners) == 1 and winners[0].version == 2
    assert all(isinstance(r, StaleVersionError) for r in results if r not in winners)


async def test_update_rechecks_merged_cross_field_rules(
    session_factory: Sessions, ref: Reference, manager: Actor
) -> None:
    detail = await create(
        session_factory, manager, payload(ref, floor_area="80", area_unit="square_metre")
    )

    with pytest.raises(CatalogValidationError) as error:
        await update(session_factory, manager, detail, latitude="51.5")
    assert "latitude" in (error.value.fields or {})
    with pytest.raises(CatalogValidationError):
        await update(session_factory, manager, detail, area_unit=None)
    assert (
        await update(session_factory, manager, detail, floor_area=None, area_unit=None)
    ).area_unit is None


async def test_classification_changes_follow_reference_rules(
    session_factory: Sessions, ref: Reference, manager: Actor
) -> None:
    detail = await create(session_factory, manager, payload(ref))

    # The stored subtype belongs to the old type, so changing type alone is refused.
    with pytest.raises(InvalidRelationshipError):
        await update(session_factory, manager, detail, property_type_id=ref.commercial)
    moved = await update(
        session_factory,
        manager,
        detail,
        property_type_id=ref.commercial,
        property_subtype_id=ref.shop,
    )
    assert moved.property_type.name == "Commercial"

    # A disabled subtype already in use stays valid through other edits.
    async with session_factory() as db:
        await db.execute(text("UPDATE property_subtypes SET is_active = false WHERE name = 'Shop'"))
        await db.commit()
    kept = await update(session_factory, manager, moved, name="Corner shop")
    assert kept.property_subtype is not None and not kept.property_subtype.is_active


async def test_type_changes_and_whole_mode_respect_units(
    session_factory: Sessions, ref: Reference, manager: Actor
) -> None:
    detail = await create(
        session_factory,
        manager,
        payload(
            ref,
            property_subtype_id=None,
            management_mode="mixed",
            units=[{"identifier": "Flat 1", "property_subtype_id": str(ref.apartment)}],
        ),
    )

    with pytest.raises(DependencyConflictError):
        await update(session_factory, manager, detail, property_type_id=ref.commercial)
    with pytest.raises(DependencyConflictError):
        await update(session_factory, manager, detail, management_mode="whole")

    async with session_factory() as db:
        await UnitService(db).archive_unit(manager, detail.id, detail.units[0].id)
    whole = await update(session_factory, manager, detail, management_mode="whole")
    assert whole.management_mode == ManagementMode.WHOLE


# --- Archive and restore ----------------------------------------------------------------


async def test_archive_and_restore(
    session_factory: Sessions, ref: Reference, manager: Actor
) -> None:
    detail = await create(
        session_factory,
        manager,
        payload(ref, status="active", management_mode="units", units=[{"identifier": "Flat 1"}]),
    )

    async with session_factory() as db:
        service = PropertyService(db)
        archived = await service.archive_property(manager, detail.id)
        again = await service.archive_property(manager, detail.id)
        assert (archived.status, archived.archived_by_id) == (
            PropertyStatus.ARCHIVED,
            manager.user_id,
        )
        assert again.version == archived.version
        # The unit is kept and shown on the archived record, but not in unit lists.
        assert [u.identifier for u in archived.units] == ["Flat 1"]
        assert await UnitService(db).list_units(manager, detail.id) == []
        with pytest.raises(ArchivedRecordError):
            await service.update_property(
                manager, detail.id, PropertyUpdate(version=archived.version, name="X")
            )
        restored = await service.restore_property(manager, detail.id)

    assert (restored.status, restored.archived_at, restored.archived_by_id) == (
        PropertyStatus.INACTIVE,
        None,
        None,
    )
    codes = [event.event_code for event in await audit_events(session_factory)]
    assert codes.count("property.archived") == 1 and codes.count("property.restored") == 1


async def test_missing_properties_are_not_found(session_factory: Sessions, manager: Actor) -> None:
    async with session_factory() as db:
        service = PropertyService(db)
        for call in (
            service.get_property(manager, uuid.uuid4()),
            service.archive_property(manager, uuid.uuid4()),
            service.update_property(manager, uuid.uuid4(), PropertyUpdate(version=1, name="X")),
        ):
            with pytest.raises(CatalogNotFoundError):
                await call


# --- Permissions ------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["agent", "accountant"])
async def test_read_only_roles_cannot_change_properties(
    session_factory: Sessions, ref: Reference, manager: Actor, role: str
) -> None:
    detail = await create(session_factory, manager, payload(ref, internal_notes="Alarm 1234"))
    actor = await actor_for(session_factory, role)

    async with session_factory() as db:
        service = PropertyService(db)
        for call in (
            service.create_property(actor, payload(ref)),
            service.update_property(actor, detail.id, PropertyUpdate(version=1, name="X")),
            service.archive_property(actor, detail.id),
            service.restore_property(actor, detail.id),
            service.list_properties(actor, PropertyListQuery(include_archived=True)),
        ):
            with pytest.raises(PermissionDeniedError):
                await call
        seen = await service.get_property(actor, detail.id)

    rendered = seen.model_dump(mode="json")
    if role == "accountant":
        assert "internal_notes" not in rendered and "owners" not in rendered
    else:
        assert rendered["internal_notes"] == "Alarm 1234" and "owners" in rendered


# --- Directory --------------------------------------------------------------------------


async def directory(session_factory: Sessions, actor: Actor, **query: Any) -> tuple[list[str], int]:
    async with session_factory() as db:
        rows, total = await PropertyService(db).list_properties(
            actor, PropertyListQuery.model_validate(query)
        )
    return [row.name for row in rows], total


@pytest.fixture
async def catalog(
    session_factory: Sessions, ref: Reference, manager: Actor
) -> dict[str, uuid.UUID]:
    owner = await create_contact(session_factory, display_name="Olive Proprietor")
    rows = {
        "Alpha House": payload(
            ref,
            name="Alpha House",
            locality="Bath",
            status="active",
            amenity_ids=[ref.pool, ref.garden],
            owners=[{"contact_id": owner}],
        ),
        "beta flat": payload(
            ref,
            name="beta flat",
            property_subtype_id=ref.apartment,
            locality="bristol",
            region="Avon",
            status="draft",
            amenity_ids=[ref.pool],
        ),
        "Corner Shop": payload(
            ref,
            name="Corner Shop",
            property_type_id=ref.commercial,
            property_subtype_id=ref.shop,
            locality="Bath",
            country_code="IE",
            status="inactive",
            management_mode="mixed",
            units=[{"identifier": "A"}, {"identifier": "B"}],
        ),
        "100% Pure_Plaza": payload(ref, name="100% Pure_Plaza", status="active"),
        "Gone Cottage": payload(ref, name="Gone Cottage", locality="BATH", status="active"),
    }
    ids = {name: (await create(session_factory, manager, data)).id for name, data in rows.items()}
    async with session_factory() as db:
        await PropertyService(db).archive_property(manager, ids["Gone Cottage"])
    return ids


async def test_directory_filters(
    session_factory: Sessions, ref: Reference, manager: Actor, catalog: dict[str, uuid.UUID]
) -> None:
    by_name = {"sort": "name"}

    assert await directory(session_factory, manager, **by_name) == (
        ["100% Pure_Plaza", "Alpha House", "beta flat", "Corner Shop"],
        4,
    )
    cases: list[tuple[dict[str, Any], list[str]]] = [
        ({"status": ["draft", "inactive"]}, ["beta flat", "Corner Shop"]),
        ({"property_type_id": [ref.commercial]}, ["Corner Shop"]),
        ({"property_subtype_id": [ref.apartment, ref.shop]}, ["beta flat", "Corner Shop"]),
        ({"amenity_id": [ref.pool]}, ["Alpha House", "beta flat"]),
        ({"amenity_id": [ref.pool, ref.garden]}, ["Alpha House"]),
        ({"management_mode": ["mixed"]}, ["Corner Shop"]),
        ({"locality": "BATH"}, ["100% Pure_Plaza", "Alpha House", "Corner Shop"]),
        ({"region": "avon"}, ["beta flat"]),
        ({"country_code": "ie"}, ["Corner Shop"]),
        ({"q": "FLAT"}, ["beta flat"]),
        ({"q": "bristol"}, ["beta flat"]),
        ({"q": "100%"}, ["100% Pure_Plaza"]),
        ({"q": "e_P"}, ["100% Pure_Plaza"]),
        ({"q": "%"}, ["100% Pure_Plaza"]),
        (
            {"include_archived": True, "locality": "bath"},
            ["100% Pure_Plaza", "Alpha House", "Corner Shop", "Gone Cottage"],
        ),
        ({"include_archived": True, "status": ["archived"]}, ["Gone Cottage"]),
    ]
    for filters, expected in cases:
        names, total = await directory(session_factory, manager, **by_name, **filters)
        assert (names, total) == (expected, len(expected)), filters


async def test_search_by_owner_name_needs_ownership_read(
    session_factory: Sessions, manager: Actor, catalog: dict[str, uuid.UUID]
) -> None:
    accountant = await actor_for(session_factory, "accountant")

    assert await directory(session_factory, manager, q="proprietor") == (["Alpha House"], 1)
    assert await directory(session_factory, accountant, q="proprietor") == ([], 0)


async def test_directory_rows_carry_unit_counts_and_classification(
    session_factory: Sessions, manager: Actor, catalog: dict[str, uuid.UUID]
) -> None:
    async with session_factory() as db:
        rows, _ = await PropertyService(db).list_properties(manager, PropertyListQuery(q="Corner"))

    [row] = rows
    assert (row.unit_count, row.property_type.name, row.cover_media_id) == (2, "Commercial", None)
    assert "address_line_1" not in row.model_dump()


@pytest.mark.parametrize("sort", list(PropertySort), ids=str)
async def test_every_sort_key_pages_without_gaps_or_duplicates(
    session_factory: Sessions, ref: Reference, manager: Actor, sort: PropertySort
) -> None:
    # Identical sort values everywhere force the ID tie-breaker to do the work.
    for _ in range(7):
        await create(session_factory, manager, payload(ref, name="Same"))

    seen: list[uuid.UUID] = []
    for offset in range(0, 7, 3):
        async with session_factory() as db:
            rows, total = await PropertyService(db).list_properties(
                manager, PropertyListQuery(sort=sort, limit=3, offset=offset)
            )
        assert total == 7
        seen.extend(row.id for row in rows)

    assert len(seen) == len(set(seen)) == 7
    async with session_factory() as db:
        full, _ = await PropertyService(db).list_properties(
            manager, PropertyListQuery(sort=sort, limit=100)
        )
    assert [row.id for row in full] == seen


async def test_sort_direction(
    session_factory: Sessions, manager: Actor, catalog: dict[str, uuid.UUID]
) -> None:
    ascending, _ = await directory(session_factory, manager, sort="locality")
    descending, _ = await directory(session_factory, manager, sort="-locality")
    by_reference, _ = await directory(session_factory, manager, sort="reference")

    assert ascending[-1] == "beta flat" and descending[0] == "beta flat"
    assert by_reference == ["Alpha House", "beta flat", "Corner Shop", "100% Pure_Plaza"]
