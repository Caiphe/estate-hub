"""Reference-data service: options, admin CRUD, disable/reactivate, ordering, uniqueness."""

import asyncio
import uuid

import pytest
from auth_support import Sessions
from catalog_support import actor_for, audit_events

from app.auth.errors import PermissionDeniedError
from app.auth.policy import Actor
from app.catalog.errors import (
    CatalogNotFoundError,
    DuplicateReferenceError,
    InvalidRelationshipError,
)
from app.catalog.schemas import (
    AmenityCreate,
    AmenityUpdate,
    ReferenceCreate,
    ReferenceOrder,
    ReferenceUpdate,
)
from app.catalog.service import ReferenceDataService


@pytest.fixture
async def admin(session_factory: Sessions) -> Actor:
    return await actor_for(session_factory, "administrator")


def named(name: str, order: int = 0) -> ReferenceCreate:
    return ReferenceCreate(name=name, display_order=order)


async def test_default_lists_offer_only_active_records_in_order(
    session_factory: Sessions, admin: Actor
) -> None:
    async with session_factory() as db:
        service = ReferenceDataService(db)
        commercial = await service.create_property_type(admin, named("Commercial", 20))
        residential = await service.create_property_type(admin, named("Residential", 10))
        retired = await service.create_property_type(admin, named("Retired", 0))
        await service.create_subtype(admin, residential.id, named("Villa", 20))
        await service.create_subtype(admin, residential.id, named("house", 10))
        old = await service.create_subtype(admin, residential.id, named("Bungalow", 0))
        await service.set_subtype_active(admin, residential.id, old.id, False)
        await service.set_property_type_active(admin, retired.id, False)
        await service.create_amenity(admin, AmenityCreate(name="Pool", category="outdoor"))
        gone = await service.create_amenity(admin, AmenityCreate(name="Sauna"))
        await service.set_amenity_active(admin, gone.id, False)

    agent = await actor_for(session_factory, "agent")
    async with session_factory() as db:
        service = ReferenceDataService(db)
        types = await service.list_property_types(agent)
        amenities = await service.list_amenities(agent)

    assert [(t.name, [s.name for s in t.subtypes]) for t in types] == [
        ("Residential", ["house", "Villa"]),
        ("Commercial", []),
    ]
    assert [a.name for a in amenities] == ["Pool"]
    assert commercial.id in {t.id for t in types}

    async with session_factory() as db:
        everything = await ReferenceDataService(db).list_property_types(
            admin, include_inactive=True
        )
    assert [t.name for t in everything] == ["Retired", "Residential", "Commercial"]
    assert [s.name for s in everything[1].subtypes] == ["Bungalow", "house", "Villa"]


async def test_names_are_unique_ignoring_case_within_their_list(
    session_factory: Sessions, admin: Actor
) -> None:
    async with session_factory() as db:
        service = ReferenceDataService(db)
        residential = await service.create_property_type(admin, named("Residential"))
        commercial = await service.create_property_type(admin, named("Commercial"))
        await service.create_subtype(admin, residential.id, named("Studio"))
        await service.create_subtype(admin, commercial.id, named("studio"))  # Other parent.
        await service.create_amenity(admin, AmenityCreate(name="Swimming pool"))
        # A failed attempt rolls back and expires loaded objects; keep plain IDs.
        residential_id, commercial_id = residential.id, commercial.id

        for attempt in (
            service.create_property_type(admin, named("  RESIDENTIAL ")),
            service.create_subtype(admin, residential_id, named("STUDIO")),
            service.create_amenity(admin, AmenityCreate(name="swimming  POOL")),
            service.update_property_type(admin, commercial_id, ReferenceUpdate(name="residential")),
        ):
            with pytest.raises(DuplicateReferenceError) as error:
                await attempt
            assert error.value.fields == {
                "name": ["Another record in this list already uses this name."]
            }

        # Renaming to a new case of its own name is allowed.
        renamed = await service.update_property_type(
            admin, commercial_id, ReferenceUpdate(name="COMMERCIAL")
        )
        assert renamed.name == "COMMERCIAL"


async def test_concurrent_duplicate_creates_resolve_to_one(
    session_factory: Sessions, admin: Actor
) -> None:
    async def create(name: str) -> object:
        async with session_factory() as db:
            return await ReferenceDataService(db).create_amenity(admin, AmenityCreate(name=name))

    results = await asyncio.gather(
        *(create(name) for name in ("Gym", "GYM", "gym", " Gym ")), return_exceptions=True
    )

    assert sum(not isinstance(r, BaseException) for r in results) == 1
    assert all(
        isinstance(r, DuplicateReferenceError) for r in results if isinstance(r, BaseException)
    )


async def test_updates_disable_and_reactivate_are_audited_without_names(
    session_factory: Sessions, admin: Actor
) -> None:
    async with session_factory() as db:
        service = ReferenceDataService(db)
        pool = await service.create_amenity(admin, AmenityCreate(name="Pool"))
        await service.update_amenity(
            admin, pool.id, AmenityUpdate(name="Heated pool", category="outdoor")
        )
        await service.update_amenity(admin, pool.id, AmenityUpdate(name="Heated pool"))  # No-op.
        await service.set_amenity_active(admin, pool.id, False)
        await service.set_amenity_active(admin, pool.id, False)  # Idempotent.
        reactivated = await service.set_amenity_active(admin, pool.id, True)

    assert reactivated.is_active
    events = [e for e in await audit_events(session_factory) if e.event_code.startswith("ref")]
    assert [e.event_code for e in events] == [
        "reference_data.created",
        "reference_data.updated",
        "reference_data.disabled",
        "reference_data.reactivated",
    ]
    assert events[1].details == {"changed_fields": ["category", "name"]}
    assert all(e.entity_type == "amenity" and e.entity_id == pool.id for e in events)
    assert "pool" not in str([e.details for e in events]).lower()


async def test_subtypes_are_addressed_through_their_own_type(
    session_factory: Sessions, admin: Actor
) -> None:
    async with session_factory() as db:
        service = ReferenceDataService(db)
        residential = await service.create_property_type(admin, named("Residential"))
        commercial = await service.create_property_type(admin, named("Commercial"))
        villa = await service.create_subtype(admin, residential.id, named("Villa"))
        residential_id, commercial_id, villa_id = residential.id, commercial.id, villa.id

        for attempt in (
            service.update_subtype(admin, commercial_id, villa_id, ReferenceUpdate(name="X")),
            service.set_subtype_active(admin, commercial_id, villa_id, False),
            service.create_subtype(admin, uuid.uuid4(), named("Orphan")),
        ):
            with pytest.raises(CatalogNotFoundError):
                await attempt

    created_events = await audit_events(session_factory, "reference_data.created")
    [created] = [e for e in created_events if e.entity_type == "property_subtype"]
    assert created.details == {"property_type_id": str(residential_id)}


async def test_reorder_requires_the_complete_list(session_factory: Sessions, admin: Actor) -> None:
    async with session_factory() as db:
        service = ReferenceDataService(db)
        residential = await service.create_property_type(admin, named("Residential"))
        a, b, c = [
            await service.create_subtype(admin, residential.id, named(name))
            for name in ("Apartment", "Bungalow", "Cottage")
        ]
        ordered = await service.reorder_subtypes(
            admin, residential.id, ReferenceOrder(ids=[c.id, a.id, b.id])
        )
        assert [(s.name, s.display_order) for s in ordered] == [
            ("Cottage", 0),
            ("Apartment", 10),
            ("Bungalow", 20),
        ]
        type_id, (a_id, b_id, c_id) = residential.id, (a.id, b.id, c.id)
        for ids in ([c_id, a_id], [c_id, a_id, b_id, uuid.uuid4()], [c_id, a_id, type_id]):
            with pytest.raises(InvalidRelationshipError):
                await service.reorder_subtypes(admin, type_id, ReferenceOrder(ids=ids))

    [event] = await audit_events(session_factory, "reference_data.reordered")
    assert event.details == {
        "record_type": "property_subtype",
        "property_type_id": str(type_id),
        "ids": [str(c_id), str(a_id), str(b_id)],
    }


async def test_reorder_types_and_amenities(session_factory: Sessions, admin: Actor) -> None:
    async with session_factory() as db:
        service = ReferenceDataService(db)
        x = await service.create_property_type(admin, named("X"))
        y = await service.create_property_type(admin, named("Y"))
        pool = await service.create_amenity(admin, AmenityCreate(name="Pool"))
        gym = await service.create_amenity(admin, AmenityCreate(name="Gym"))

        assert [
            t.id
            for t in await service.reorder_property_types(admin, ReferenceOrder(ids=[y.id, x.id]))
        ] == [y.id, x.id]
        assert [
            a.id
            for a in await service.reorder_amenities(admin, ReferenceOrder(ids=[pool.id, gym.id]))
        ] == [pool.id, gym.id]


@pytest.mark.parametrize("role", ["manager", "agent", "accountant"])
async def test_only_administrators_manage_reference_data(
    session_factory: Sessions, admin: Actor, role: str
) -> None:
    actor = await actor_for(session_factory, role)
    async with session_factory() as db:
        service = ReferenceDataService(db)
        residential = await service.create_property_type(admin, named("Residential"))
        for attempt in (
            service.create_property_type(actor, named("Commercial")),
            service.update_property_type(actor, residential.id, ReferenceUpdate(name="X")),
            service.set_property_type_active(actor, residential.id, False),
            service.reorder_property_types(actor, ReferenceOrder(ids=[residential.id])),
            service.create_amenity(actor, AmenityCreate(name="Pool")),
            service.list_property_types(actor, include_inactive=True),
            service.list_amenities(actor, include_inactive=True),
        ):
            with pytest.raises(PermissionDeniedError):
                await attempt
        # Every catalog reader can load the active lists that property forms use.
        types = await service.list_property_types(actor)
        assert [t.name for t in types] == ["Residential"]
