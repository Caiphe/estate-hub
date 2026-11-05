"""Units: configurations, identifiers, subtypes, facts, archival, privacy, and queries."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import pytest
from auth_support import Sessions
from catalog_support import (
    actor_for,
    audit_events,
    create_property,
    create_property_type,
    subtype_id,
)
from pydantic import ValidationError
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.errors import PermissionDeniedError
from app.auth.policy import Actor
from app.catalog.errors import (
    ArchivedRecordError,
    CatalogConflictError,
    CatalogNotFoundError,
    CatalogValidationError,
    DependencyConflictError,
    DuplicateReferenceError,
    InvalidRelationshipError,
    StaleVersionError,
)
from app.catalog.models import Amenity, PropertySubtype
from app.properties.constants import AreaUnit, ManagementMode, PropertyStatus, UnitStatus
from app.properties.models import Property, Unit
from app.properties.repository import PropertyRepository
from app.properties.rules import ensure_mode_change_allowed
from app.properties.schemas import UnitCreate, UnitUpdate, unit_view
from app.properties.units import UnitService

UNITS = ManagementMode.UNITS


@pytest.fixture
async def manager(session_factory: Sessions) -> Actor:
    return await actor_for(session_factory, "manager")


async def create_unit(
    session_factory: Sessions, actor: Actor, property_id: uuid.UUID, identifier: str, **fields: Any
) -> Unit:
    async with session_factory() as db:
        return await UnitService(db).create_unit(
            actor, property_id, UnitCreate(identifier=identifier, **fields)
        )


async def update_unit(
    session_factory: Sessions, actor: Actor, property_id: uuid.UUID, unit: Unit, **fields: Any
) -> Unit:
    async with session_factory() as db:
        return await UnitService(db).update_unit(
            actor,
            property_id,
            unit.id,
            UnitUpdate.model_validate({"version": unit.version} | fields),
        )


async def set_mode(session_factory: Sessions, property_id: uuid.UUID, mode: str) -> None:
    async with session_factory() as db:
        await db.execute(
            text("UPDATE properties SET management_mode = :mode WHERE id = :id"),
            {"mode": mode, "id": property_id},
        )
        await db.commit()


# --- Configurations ---------------------------------------------------------------------


async def test_standalone_properties_need_no_units_and_refuse_them(
    session_factory: Sessions, manager: Actor
) -> None:
    property_id = await create_property(session_factory)

    async with session_factory() as db:
        assert await UnitService(db).list_units(manager, property_id) == []
    with pytest.raises(CatalogConflictError) as error:
        await create_unit(session_factory, manager, property_id, "Flat 1")
    assert "management_mode" in (error.value.fields or {})


@pytest.mark.parametrize("mode", [ManagementMode.UNITS, ManagementMode.MIXED])
async def test_unit_managed_and_mixed_properties_take_units(
    session_factory: Sessions, manager: Actor, mode: ManagementMode
) -> None:
    property_id = await create_property(session_factory, management_mode=mode)

    for identifier in ("Flat 2", "Flat 1", "Shop A"):
        await create_unit(session_factory, manager, property_id, identifier)

    async with session_factory() as db:
        units = await UnitService(db).list_units(manager, property_id)
    assert [unit.identifier for unit in units] == ["Flat 1", "Flat 2", "Shop A"]
    assert {unit.status for unit in units} == {UnitStatus.AVAILABLE}


def test_switching_to_whole_requires_no_active_units() -> None:
    ensure_mode_change_allowed(ManagementMode.WHOLE, 0)
    ensure_mode_change_allowed(ManagementMode.MIXED, 3)
    with pytest.raises(DependencyConflictError):
        ensure_mode_change_allowed(ManagementMode.WHOLE, 1)


async def test_restoring_a_unit_into_a_whole_property_is_refused(
    session_factory: Sessions, manager: Actor
) -> None:
    property_id = await create_property(session_factory, management_mode=UNITS)
    unit = await create_unit(session_factory, manager, property_id, "Flat 1")
    async with session_factory() as db:
        await UnitService(db).archive_unit(manager, property_id, unit.id)
        assert await PropertyRepository(db).count_active_units(property_id) == 0
    await set_mode(session_factory, property_id, "whole")

    async with session_factory() as db:
        with pytest.raises(CatalogConflictError):
            await UnitService(db).restore_unit(manager, property_id, unit.id)


# --- Identifiers ------------------------------------------------------------------------


async def test_identifiers_are_unique_per_property_ignoring_case(
    session_factory: Sessions, manager: Actor
) -> None:
    property_id = await create_property(session_factory, management_mode=UNITS)
    other_id = await create_property(session_factory, management_mode=UNITS)
    first = await create_unit(session_factory, manager, property_id, "Flat 2B")

    with pytest.raises(DuplicateReferenceError) as error:
        await create_unit(session_factory, manager, property_id, "  flat   2b ")
    assert "identifier" in (error.value.fields or {})
    await create_unit(session_factory, manager, other_id, "Flat 2B")

    second = await create_unit(session_factory, manager, property_id, "Flat 3")
    with pytest.raises(DuplicateReferenceError):
        await update_unit(session_factory, manager, property_id, second, identifier="FLAT 2B")

    # An archived unit releases its identifier; restoring it then conflicts.
    async with session_factory() as db:
        await UnitService(db).archive_unit(manager, property_id, first.id)
    await create_unit(session_factory, manager, property_id, "flat 2b")
    async with session_factory() as db:
        with pytest.raises(DuplicateReferenceError):
            await UnitService(db).restore_unit(manager, property_id, first.id)


async def test_database_rejects_duplicate_active_identifiers(
    session_factory: Sessions, manager: Actor
) -> None:
    property_id = await create_property(session_factory, management_mode=UNITS)
    await create_unit(session_factory, manager, property_id, "Flat 1")

    async with session_factory() as db:
        with pytest.raises(DBAPIError, match="uq_units_current_identifier"):
            await db.execute(
                text(
                    "INSERT INTO units (id, property_id, identifier) "
                    "VALUES (gen_random_uuid(), :id, 'FLAT 1')"
                ),
                {"id": property_id},
            )


# --- Subtypes and amenities -------------------------------------------------------------


async def test_unit_subtypes_must_belong_to_the_property_type(
    session_factory: Sessions, manager: Actor
) -> None:
    residential = await create_property_type(session_factory, "Apartment", "Studio")
    commercial = await create_property_type(session_factory, "Shop")
    property_id = await create_property(
        session_factory, management_mode=UNITS, property_type_id=residential
    )
    apartment = await subtype_id(session_factory, residential, "Apartment")
    shop = await subtype_id(session_factory, commercial, "Shop")

    unit = await create_unit(
        session_factory, manager, property_id, "Flat 1", property_subtype_id=apartment
    )
    assert unit.property_subtype is not None and unit.property_subtype.name == "Apartment"

    for bad in (shop, uuid.uuid4()):
        with pytest.raises(InvalidRelationshipError) as error:
            await create_unit(
                session_factory, manager, property_id, "Flat 2", property_subtype_id=bad
            )
        assert "property_subtype_id" in (error.value.fields or {})
    with pytest.raises(InvalidRelationshipError):
        await update_unit(session_factory, manager, property_id, unit, property_subtype_id=shop)


async def test_disabled_subtypes_and_amenities_cannot_be_newly_assigned(
    session_factory: Sessions, manager: Actor
) -> None:
    type_id = await create_property_type(session_factory, "Apartment", "Studio")
    property_id = await create_property(
        session_factory, management_mode=UNITS, property_type_id=type_id
    )
    studio = await subtype_id(session_factory, type_id, "Studio")
    async with session_factory() as db:
        pool, gym = Amenity(name="Pool"), Amenity(name="Gym")
        db.add_all([pool, gym])
        await db.flush()
        pool_id, gym_id = pool.id, gym.id
        await db.commit()

    unit = await create_unit(
        session_factory,
        manager,
        property_id,
        "Flat 1",
        property_subtype_id=studio,
        amenity_ids=[pool_id],
    )
    async with session_factory() as db:
        (await db.get_one(PropertySubtype, studio)).is_active = False
        (await db.get_one(Amenity, pool_id)).is_active = False
        (await db.get_one(Amenity, gym_id)).is_active = False
        await db.commit()

    with pytest.raises(InvalidRelationshipError):
        await create_unit(
            session_factory, manager, property_id, "Flat 2", property_subtype_id=studio
        )
    with pytest.raises(InvalidRelationshipError):
        await update_unit(
            session_factory, manager, property_id, unit, amenity_ids=[pool_id, gym_id]
        )
    with pytest.raises(InvalidRelationshipError):
        await create_unit(
            session_factory, manager, property_id, "Flat 3", amenity_ids=[uuid.uuid4()]
        )

    # Disabled values already on the unit stay valid through other changes.
    updated = await update_unit(
        session_factory, manager, property_id, unit, name="Garden flat", amenity_ids=[pool_id]
    )
    assert updated.property_subtype_id == studio
    assert [a.id for a in updated.amenities] == [pool_id]


async def test_amenity_only_changes_bump_the_version(
    session_factory: Sessions, manager: Actor
) -> None:
    property_id = await create_property(session_factory, management_mode=UNITS)
    async with session_factory() as db:
        pool = Amenity(name="Pool")
        db.add(pool)
        await db.commit()
    unit = await create_unit(session_factory, manager, property_id, "Flat 1")

    updated = await update_unit(session_factory, manager, property_id, unit, amenity_ids=[pool.id])

    assert updated.version == 2
    [event] = await audit_events(session_factory, "unit.updated")
    assert event.details["changed_fields"] == ["amenity_ids"]


# --- Facts ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"bedrooms": -1},
        {"capacity": -1},
        {"bathrooms": "1.3"},
        {"bathrooms": "-0.5"},
        {"floor_area": "-1", "area_unit": "square_metre"},
        {"floor_area": "50"},
        {"area_unit": "square_foot"},
        {"floor_area": "1.234", "area_unit": "square_metre"},
        {"status": "rented"},
        {"identifier": "   "},
        {"amenity_ids": [str(uuid.UUID(int=1))] * 2},
        {"property_id": str(uuid.uuid4())},
        {"parent_unit_id": str(uuid.uuid4())},
    ],
)
def test_invalid_unit_input_is_rejected(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        UnitCreate.model_validate({"identifier": "Flat 1"} | fields)


def test_valid_facts_use_exact_decimals() -> None:
    created = UnitCreate.model_validate(
        {
            "identifier": " Flat  1 ",
            "bedrooms": 0,
            "bathrooms": "1.5",
            "capacity": 4,
            "floor_area": "52.50",
            "area_unit": "square_metre",
        }
    )

    assert created.identifier == "Flat 1"
    assert created.bathrooms == Decimal("1.5")
    assert created.floor_area == Decimal("52.50")


async def test_update_rechecks_area_against_the_stored_unit(
    session_factory: Sessions, manager: Actor
) -> None:
    property_id = await create_property(session_factory, management_mode=UNITS)
    unit = await create_unit(
        session_factory,
        manager,
        property_id,
        "Flat 1",
        floor_area=Decimal("40"),
        area_unit=AreaUnit.SQUARE_METRE,
    )

    with pytest.raises(CatalogValidationError):
        await update_unit(session_factory, manager, property_id, unit, area_unit=None)


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"identifier": "' Flat'"}, "ck_units_identifier_normalized"),
        ({"bedrooms": "-1"}, "ck_units_bedrooms_non_negative"),
        ({"capacity": "-1"}, "ck_units_capacity_non_negative"),
        ({"bathrooms": "2.25"}, "ck_units_bathrooms_half_units"),
        ({"floor_area": "10"}, "ck_units_area_unit_matches_area"),
        ({"status": "'rented'"}, "ck_units_unit_status"),
        ({"version": "0"}, "ck_units_version_positive"),
        ({"archived_by_id": "gen_random_uuid()"}, "ck_units_archived_by_needs_date"),
    ],
)
async def test_database_rejects_invalid_units(
    session_factory: Sessions, columns: dict[str, str], constraint: str
) -> None:
    property_id = await create_property(session_factory, management_mode=UNITS)
    values = {"id": "gen_random_uuid()", "property_id": f"'{property_id}'", "identifier": "'U1'"}
    values |= columns

    async with session_factory() as db:
        with pytest.raises(DBAPIError) as error:
            await db.execute(
                text(
                    f"INSERT INTO units ({', '.join(values)}) VALUES ({', '.join(values.values())})"
                )
            )
    assert constraint in str(error.value)


async def test_database_rejects_unknown_management_modes(session_factory: Sessions) -> None:
    property_id = await create_property(session_factory)

    with pytest.raises(DBAPIError, match="ck_properties_management_mode"):
        await set_mode(session_factory, property_id, "partial")


# --- Archival and movement --------------------------------------------------------------


async def test_units_never_move_between_properties(
    session_factory: Sessions, manager: Actor
) -> None:
    property_id = await create_property(session_factory, management_mode=UNITS)
    other_id = await create_property(session_factory, management_mode=UNITS)
    unit = await create_unit(session_factory, manager, property_id, "Flat 1")

    with pytest.raises(ValueError, match="cannot move"):
        unit.property_id = other_id
    with pytest.raises(ValidationError, match="Extra inputs"):
        UnitUpdate.model_validate({"version": 1, "property_id": str(other_id)})
    async with session_factory() as db:
        service = UnitService(db)
        with pytest.raises(CatalogNotFoundError):
            await service.get_unit(manager, other_id, unit.id)
        with pytest.raises(CatalogNotFoundError):
            await service.archive_unit(manager, other_id, unit.id)


async def test_property_with_units_cannot_be_deleted(
    session_factory: Sessions, manager: Actor
) -> None:
    property_id = await create_property(session_factory, management_mode=UNITS)
    await create_unit(session_factory, manager, property_id, "Flat 1")

    async with session_factory() as db:
        with pytest.raises(DBAPIError, match="fk_units_property_id_properties"):
            await db.execute(text("DELETE FROM properties WHERE id = :id"), {"id": property_id})


async def test_archived_property_hides_but_preserves_units(
    session_factory: Sessions, manager: Actor
) -> None:
    property_id = await create_property(session_factory, management_mode=UNITS)
    unit = await create_unit(session_factory, manager, property_id, "Flat 1")
    async with session_factory() as db:
        row = await db.get_one(Property, property_id)
        row.status = PropertyStatus.ARCHIVED
        row.archived_at = unit.created_at
        await db.commit()

    async with session_factory() as db:
        service = UnitService(db)
        assert await service.list_units(manager, property_id) == []
        preserved = await service.list_units(manager, property_id, include_archived=True)
        assert [(u.id, u.archived_at) for u in preserved] == [(unit.id, None)]
        assert (await service.get_unit(manager, property_id, unit.id)).id == unit.id
        for change in (
            service.archive_unit(manager, property_id, unit.id),
            service.create_unit(manager, property_id, UnitCreate(identifier="Flat 2")),
            service.update_unit(manager, property_id, unit.id, UnitUpdate(version=1, name="X")),
        ):
            with pytest.raises(ArchivedRecordError):
                await change


async def test_archive_restore_and_stale_updates(session_factory: Sessions, manager: Actor) -> None:
    property_id = await create_property(session_factory, management_mode=UNITS)
    unit = await create_unit(session_factory, manager, property_id, "Flat 1")
    await update_unit(session_factory, manager, property_id, unit, name="First edit")

    with pytest.raises(StaleVersionError):
        await update_unit(session_factory, manager, property_id, unit, name="Stale edit")

    async with session_factory() as db:
        service = UnitService(db)
        archived = await service.archive_unit(manager, property_id, unit.id)
        assert archived.archived_by_id == manager.user_id
        assert (await service.archive_unit(manager, property_id, unit.id)).version == (
            archived.version
        )
        with pytest.raises(ArchivedRecordError):
            await service.update_unit(
                manager, property_id, unit.id, UnitUpdate(version=archived.version, name="X")
            )
        assert await service.list_units(manager, property_id) == []
        restored = await service.restore_unit(manager, property_id, unit.id)
        assert restored.archived_at is None
        assert restored.name == "First edit"

    codes = [e.event_code for e in await audit_events(session_factory)]
    assert [c for c in codes if c.startswith("unit.")] == [
        "unit.created",
        "unit.updated",
        "unit.archived",
        "unit.restored",
    ]
    for audit in await audit_events(session_factory):
        if audit.event_code.startswith("unit."):
            assert audit.details["property_id"] == str(property_id)
            assert "First edit" not in str(audit.details)


# --- Authorization and privacy ----------------------------------------------------------


async def test_unit_permissions_by_role(session_factory: Sessions, manager: Actor) -> None:
    property_id = await create_property(session_factory, management_mode=UNITS)
    unit = await create_unit(session_factory, manager, property_id, "Flat 1")

    for role in ("agent", "accountant"):
        actor = await actor_for(session_factory, role)
        async with session_factory() as db:
            service = UnitService(db)
            assert [u.id for u in await service.list_units(actor, property_id)] == [unit.id]
            with pytest.raises(PermissionDeniedError):
                await service.create_unit(actor, property_id, UnitCreate(identifier="Flat 2"))
            with pytest.raises(PermissionDeniedError):
                await service.archive_unit(actor, property_id, unit.id)


async def test_internal_notes_require_read_internal(
    session_factory: Sessions, manager: Actor
) -> None:
    property_id = await create_property(session_factory, management_mode=UNITS)
    unit = await create_unit(
        session_factory, manager, property_id, "Flat 1", internal_notes="Leaking tap"
    )
    accountant = await actor_for(session_factory, "accountant")

    internal = unit_view(manager, unit)
    restricted = unit_view(accountant, unit)

    assert internal.internal_notes == "Leaking tap"
    assert "internal_notes" not in restricted.model_dump()
    assert "Leaking tap" not in restricted.model_dump_json()


# --- Query shape ------------------------------------------------------------------------


@contextmanager
def count_queries(engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def record(*args: Any) -> None:
        statements.append(args[2])

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)


async def test_property_detail_loads_without_n_plus_one(
    session_factory: Sessions, db_engine: AsyncEngine, manager: Actor
) -> None:
    type_id = await create_property_type(session_factory, "Apartment")
    apartment = await subtype_id(session_factory, type_id, "Apartment")
    async with session_factory() as db:
        amenities = [Amenity(name=f"Amenity {i}") for i in range(3)]
        db.add_all(amenities)
        await db.commit()
    amenity_ids = [a.id for a in amenities]

    async def detail_queries(unit_count: int) -> int:
        property_id = await create_property(
            session_factory, management_mode=UNITS, property_type_id=type_id
        )
        for index in range(unit_count):
            await create_unit(
                session_factory,
                manager,
                property_id,
                f"Flat {index}",
                property_subtype_id=apartment,
                amenity_ids=amenity_ids,
            )
        async with session_factory() as db:
            with count_queries(db_engine) as statements:
                loaded = await PropertyRepository(db).get_detail(property_id)
                assert loaded is not None
                # Touch every loaded relationship: none may issue another query.
                assert len(loaded.units) == unit_count
                for unit in loaded.units:
                    assert unit.property_subtype is not None
                    assert len(unit.amenities) == 3
                _ = (loaded.property_type.name, loaded.amenities, loaded.property_subtype)
            return len(statements)

    assert await detail_queries(1) == await detail_queries(12)
