"""HTTP: reference data, contacts, and property ownership routes."""

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from auth_support import (
    assert_error,
    bearer,
    create_staff,
    csrf_header,
    login,
    token_for,
)
from catalog_support import audit_events
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.policy import Actor
from app.catalog.errors import InvalidRelationshipError
from app.catalog.schemas import AmenityCreate, ReferenceCreate
from app.catalog.service import ReferenceDataService
from app.contacts.schemas import ContactCreate, ContactDetail, contact_view
from app.contacts.service import ContactService
from app.main import app
from app.properties.schemas import OwnershipCreate, PropertyCreate
from app.properties.service import PropertyService
from app.users.constants import RoleCode

Sessions = async_sessionmaker[AsyncSession]
API = "/api/v1"
EVERYONE = {"administrator", "manager", "agent", "accountant"}
ADMIN = {"administrator"}
CONTACT_ROLES = {"administrator", "manager", "agent"}
OWNERSHIP_MANAGERS = {"administrator", "manager"}


@dataclass(frozen=True)
class World:
    type_id: uuid.UUID
    subtype_id: uuid.UUID
    amenity_id: uuid.UUID
    contact_id: uuid.UUID
    property_id: uuid.UUID
    ownership_id: uuid.UUID


async def admin_actor(session_factory: Sessions) -> Actor:
    user = await create_staff(session_factory, ["administrator"])
    return Actor(user_id=user.id, role_codes=frozenset({"administrator"}), active=True)


@pytest.fixture
async def world(session_factory: Sessions) -> World:
    actor = await admin_actor(session_factory)
    async with session_factory() as db:
        reference = ReferenceDataService(db)
        house_type = await reference.create_property_type(
            actor, ReferenceCreate(name="Residential")
        )
        subtype = await reference.create_subtype(
            actor, house_type.id, ReferenceCreate(name="House")
        )
        amenity = await reference.create_amenity(actor, AmenityCreate(name="Garden"))
        type_id, subtype_id, amenity_id = house_type.id, subtype.id, amenity.id
    async with session_factory() as db:
        contact = await ContactService(db).create_contact(
            actor,
            ContactCreate(
                kind="person",
                display_name="Olive Owner",
                email="olive@example.com",
                internal_notes="Prefers email",
            ),
        )
    async with session_factory() as db:
        detail = await PropertyService(db).create_property(
            actor,
            PropertyCreate(
                name="Rose Cottage",
                property_type_id=type_id,
                property_subtype_id=subtype_id,
                address_line_1="1 High Street",
                locality="Bath",
                region="Somerset",
                country_code="GB",
                owners=[OwnershipCreate(contact_id=contact.id, share_percentage=50)],
            ),
        )
    assert detail.owners is not None
    return World(type_id, subtype_id, amenity_id, contact.id, detail.id, detail.owners.items[0].id)


Payload = Callable[[World], Any] | None


def _order(ids: Callable[[World], list[uuid.UUID]]) -> Callable[[World], Any]:
    return lambda w: {"ids": [str(i) for i in ids(w)]}


ENDPOINTS: list[tuple[str, str, Payload, int, set[str]]] = [
    ("GET", "/property-types", None, 200, EVERYONE),
    ("GET", "/property-types/{type}", None, 200, EVERYONE),
    ("GET", "/property-types/{type}/subtypes/{subtype}", None, 200, EVERYONE),
    ("GET", "/amenities", None, 200, EVERYONE),
    ("GET", "/amenities/{amenity}", None, 200, EVERYONE),
    ("POST", "/property-types", lambda w: {"name": "Commercial"}, 201, ADMIN),
    ("PATCH", "/property-types/{type}", lambda w: {"display_order": 5}, 200, ADMIN),
    ("POST", "/property-types/{type}/disable", None, 200, ADMIN),
    ("POST", "/property-types/{type}/reactivate", None, 200, ADMIN),
    ("PUT", "/property-types/order", _order(lambda w: [w.type_id]), 200, ADMIN),
    ("POST", "/property-types/{type}/subtypes", lambda w: {"name": "Villa"}, 201, ADMIN),
    (
        "PATCH",
        "/property-types/{type}/subtypes/{subtype}",
        lambda w: {"name": "Detached"},
        200,
        ADMIN,
    ),
    ("POST", "/property-types/{type}/subtypes/{subtype}/disable", None, 200, ADMIN),
    ("POST", "/property-types/{type}/subtypes/{subtype}/reactivate", None, 200, ADMIN),
    ("PUT", "/property-types/{type}/subtypes/order", _order(lambda w: [w.subtype_id]), 200, ADMIN),
    ("POST", "/amenities", lambda w: {"name": "Pool", "category": "outdoor"}, 201, ADMIN),
    ("PATCH", "/amenities/{amenity}", lambda w: {"category": "outdoor"}, 200, ADMIN),
    ("POST", "/amenities/{amenity}/disable", None, 200, ADMIN),
    ("POST", "/amenities/{amenity}/reactivate", None, 200, ADMIN),
    ("PUT", "/amenities/order", _order(lambda w: [w.amenity_id]), 200, ADMIN),
    ("GET", "/contacts", None, 200, CONTACT_ROLES),
    (
        "POST",
        "/contacts",
        lambda w: {"kind": "organization", "display_name": "Acme", "telephone": "+441234567890"},
        201,
        CONTACT_ROLES,
    ),
    ("GET", "/contacts/{contact}", None, 200, CONTACT_ROLES),
    (
        "PATCH",
        "/contacts/{contact}",
        lambda w: {"version": 1, "display_name": "Olive O. Owner"},
        200,
        CONTACT_ROLES,
    ),
    ("POST", "/contacts/{contact}/restore", None, 200, CONTACT_ROLES),
    ("GET", "/properties/{property}/owners", None, 200, CONTACT_ROLES),
    ("GET", "/properties/{property}/owners/{ownership}", None, 200, CONTACT_ROLES),
    (
        "PATCH",
        "/properties/{property}/owners/{ownership}",
        lambda w: {"share_percentage": "60"},
        200,
        OWNERSHIP_MANAGERS,
    ),
    ("DELETE", "/properties/{property}/owners/{ownership}", None, 200, OWNERSHIP_MANAGERS),
]
# Archiving the world's contact conflicts (it owns the property); a fresh one is used.
ARCHIVE_CONTACT = ("DELETE", "/contacts/{contact}", None, 200, CONTACT_ROLES)


def url(path: str, w: World) -> str:
    return API + path.format(
        type=w.type_id,
        subtype=w.subtype_id,
        amenity=w.amenity_id,
        contact=w.contact_id,
        property=w.property_id,
        ownership=w.ownership_id,
    )


async def as_role(api: AsyncClient, session_factory: Sessions, role: str) -> dict[str, str]:
    return bearer(await token_for(api, await create_staff(session_factory, [role])))


def catalog_events(events: list[Any]) -> list[str]:
    return [e.event_code for e in events if not e.event_code.startswith(("auth.", "staff."))]


# --- Matrix -----------------------------------------------------------------------------


@pytest.mark.parametrize("role", [role.value for role in RoleCode])
@pytest.mark.parametrize(("method", "path", "payload", "success", "allowed"), ENDPOINTS)
async def test_every_endpoint_for_every_role(
    api: AsyncClient,
    session_factory: Sessions,
    world: World,
    role: str,
    method: str,
    path: str,
    payload: Payload,
    success: int,
    allowed: set[str],
) -> None:
    before = catalog_events(await audit_events(session_factory))
    headers = await as_role(api, session_factory, role)

    response = await api.request(
        method, url(path, world), json=payload(world) if payload else None, headers=headers
    )

    if role in allowed:
        assert response.status_code == success, response.text
        if success == 201:
            location = response.headers["location"]
            assert (await api.get(location, headers=headers)).status_code == 200
    else:
        assert_error(response, 403, "permission_denied")
        assert catalog_events(await audit_events(session_factory)) == before


@pytest.mark.parametrize("role", [role.value for role in RoleCode])
async def test_archive_contact_for_every_role(
    api: AsyncClient, session_factory: Sessions, world: World, role: str
) -> None:
    async with session_factory() as db:
        spare = await ContactService(db).create_contact(
            await admin_actor(session_factory),
            ContactCreate(kind="person", display_name="Spare", email="spare@example.com"),
        )
    response = await api.delete(
        f"{API}/contacts/{spare.id}", headers=await as_role(api, session_factory, role)
    )

    if role in ARCHIVE_CONTACT[4]:
        assert response.status_code == 200 and response.json()["status"] == "archived"
    else:
        assert_error(response, 403, "permission_denied")


@pytest.mark.parametrize(
    ("method", "path", "payload", "success", "allowed"), [*ENDPOINTS, ARCHIVE_CONTACT]
)
async def test_every_endpoint_requires_authentication(
    api: AsyncClient,
    world: World,
    method: str,
    path: str,
    payload: Payload,
    success: int,
    allowed: set[str],
) -> None:
    response = await api.request(method, url(path, world), json=payload(world) if payload else None)

    assert_error(response, 401, "authentication_required")


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("POST", "/property-types", lambda w: {"name": "Commercial"}),
        (
            "POST",
            "/contacts",
            lambda w: {"kind": "person", "display_name": "X", "email": "x@example.com"},
        ),
        ("PATCH", "/properties/{property}/owners/{ownership}", lambda w: {"notes": "x"}),
        ("DELETE", "/properties/{property}/owners/{ownership}", None),
    ],
)
async def test_cookie_mutations_require_csrf(
    api: AsyncClient,
    session_factory: Sessions,
    world: World,
    method: str,
    path: str,
    payload: Payload,
) -> None:
    admin = await create_staff(session_factory, ["administrator"])
    await login(api, admin.email)
    body = payload(world) if payload else None

    assert_error(await api.request(method, url(path, world), json=body), 403, "csrf_failed")
    accepted = await api.request(method, url(path, world), json=body, headers=csrf_header(api))
    assert accepted.status_code in {200, 201}, accepted.text


def test_openapi_documents_security_and_errors() -> None:
    paths = app.openapi()["paths"]
    for method, path, *_ in [*ENDPOINTS, ARCHIVE_CONTACT]:
        documented = path.format(
            type="{property_type_id}",
            subtype="{property_subtype_id}",
            amenity="{amenity_id}",
            contact="{contact_id}",
            property="{property_id}",
            ownership="{ownership_id}",
        )
        operation = paths[API + documented][method.lower()]
        assert operation["security"] == [{"OAuth2PasswordBearer": []}]
        assert {"401", "403", "422"} <= set(operation["responses"])
        assert operation["summary"]
    assert "409" in paths[API + "/property-types"]["post"]["responses"]
    assert (
        "stale_version"
        in paths[API + "/contacts/{contact_id}"]["patch"]["responses"]["409"]["description"]
    )


# --- Validation, missing records, and conflicts -----------------------------------------


@pytest.fixture
async def admin_headers(api: AsyncClient, session_factory: Sessions) -> dict[str, str]:
    return await as_role(api, session_factory, "administrator")


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/property-types", {"name": "  "}),
        ("POST", "/property-types", {"name": "X", "is_active": False}),
        ("PATCH", "/property-types/{type}", {}),
        ("PUT", "/property-types/order", {"ids": []}),
        ("POST", "/amenities", {"name": "Pool", "category": "Outdoor space"}),
        ("POST", "/contacts", {"kind": "person", "display_name": "No method"}),
        ("POST", "/contacts", {"kind": "robot", "display_name": "X", "email": "x@example.com"}),
        ("PATCH", "/contacts/{contact}", {"region": "Avon"}),
        ("POST", "/properties/{property}/owners", {"contact_id": "not-a-uuid"}),
        (
            "POST",
            "/properties/{property}/owners",
            {"contact_id": "{contact}", "share_percentage": "100.5"},
        ),
        ("PATCH", "/properties/{property}/owners/{ownership}", {"contact_id": "{contact}"}),
        ("GET", "/contacts?sort=price", None),
        ("GET", "/contacts?limit=500", None),
        ("GET", "/property-types?include_inactive=maybe", None),
        ("GET", "/property-types/not-a-uuid", None),
        ("GET", "/properties/not-a-uuid/owners", None),
    ],
)
async def test_invalid_input_is_rejected(
    api: AsyncClient,
    admin_headers: dict[str, str],
    world: World,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    if body is not None:
        body = {k: (str(world.contact_id) if v == "{contact}" else v) for k, v in body.items()}

    response = await api.request(method, url(path, world), json=body, headers=admin_headers)

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error" and error["fields"]
    assert "olive@example.com" not in response.text


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/property-types/{missing}"),
        ("PATCH", "/property-types/{missing}"),
        ("GET", "/property-types/{type}/subtypes/{missing}"),
        ("POST", "/property-types/{missing}/subtypes"),
        ("GET", "/amenities/{missing}"),
        ("POST", "/amenities/{missing}/disable"),
        ("GET", "/contacts/{missing}"),
        ("DELETE", "/contacts/{missing}"),
        ("GET", "/properties/{missing}/owners"),
        ("GET", "/properties/{property}/owners/{missing}"),
        ("DELETE", "/properties/{property}/owners/{missing}"),
    ],
)
async def test_missing_records_are_not_found(
    api: AsyncClient, admin_headers: dict[str, str], world: World, method: str, path: str
) -> None:
    body = {"name": "X"} if method in {"POST", "PATCH"} and "disable" not in path else None

    response = await api.request(
        method,
        url(path.replace("{missing}", str(uuid.uuid4())), world),
        json=body,
        headers=admin_headers,
    )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"


async def test_subtypes_and_links_under_the_wrong_parent_are_not_found(
    api: AsyncClient, admin_headers: dict[str, str], session_factory: Sessions, world: World
) -> None:
    other = await api.post(
        f"{API}/property-types", json={"name": "Commercial"}, headers=admin_headers
    )
    other_type = other.json()["id"]
    async with session_factory() as db:
        other_property = await PropertyService(db).create_property(
            await admin_actor(session_factory),
            PropertyCreate(
                name="Other",
                property_type_id=world.type_id,
                address_line_1="2 High Street",
                locality="Bath",
                region="Somerset",
                country_code="GB",
            ),
        )

    for path in (
        f"/property-types/{other_type}/subtypes/{world.subtype_id}",
        f"/properties/{other_property.id}/owners/{world.ownership_id}",
    ):
        assert (await api.get(API + path, headers=admin_headers)).status_code == 404


async def test_reference_conflicts(
    api: AsyncClient, admin_headers: dict[str, str], world: World
) -> None:
    duplicate = await api.post(
        f"{API}/property-types", json={"name": " RESIDENTIAL "}, headers=admin_headers
    )
    order = await api.put(
        f"{API}/amenities/order", json={"ids": [str(uuid.uuid4())]}, headers=admin_headers
    )

    assert duplicate.status_code == 409
    error = duplicate.json()["error"]
    assert error["code"] == "duplicate_reference"
    assert error["fields"] == {"name": ["Another record in this list already uses this name."]}
    assert order.status_code == 422 and order.json()["error"]["code"] == "invalid_relationship"


async def test_include_inactive_needs_reference_permission(
    api: AsyncClient, session_factory: Sessions, admin_headers: dict[str, str], world: World
) -> None:
    await api.post(f"{API}/amenities/{world.amenity_id}/disable", headers=admin_headers)
    manager = await as_role(api, session_factory, "manager")

    assert (await api.get(f"{API}/amenities", headers=manager)).json() == []
    assert_error(
        await api.get(f"{API}/amenities?include_inactive=true", headers=manager),
        403,
        "permission_denied",
    )
    everything = await api.get(f"{API}/amenities?include_inactive=true", headers=admin_headers)
    assert [(a["name"], a["is_active"]) for a in everything.json()] == [("Garden", False)]


async def test_disabled_references_stay_valid_on_existing_records(
    api: AsyncClient, session_factory: Sessions, admin_headers: dict[str, str], world: World
) -> None:
    for path in (
        f"/property-types/{world.type_id}/disable",
        f"/property-types/{world.type_id}/subtypes/{world.subtype_id}/disable",
    ):
        assert (await api.post(API + path, headers=admin_headers)).status_code == 200

    listed = await api.get(f"{API}/property-types", headers=admin_headers)
    single = await api.get(f"{API}/property-types/{world.type_id}", headers=admin_headers)
    assert listed.json() == []
    assert single.json()["is_active"] is False
    assert [s["is_active"] for s in single.json()["subtypes"]] == [False]

    actor = await admin_actor(session_factory)
    async with session_factory() as db:
        existing = await PropertyService(db).get_property(actor, world.property_id)
        assert existing.property_type.id == world.type_id
        with pytest.raises(InvalidRelationshipError):
            await PropertyService(db).create_property(
                actor,
                PropertyCreate(
                    name="New",
                    property_type_id=world.type_id,
                    address_line_1="3 High Street",
                    locality="Bath",
                    region="Somerset",
                    country_code="GB",
                ),
            )

    reactivated = await api.post(
        f"{API}/property-types/{world.type_id}/reactivate", headers=admin_headers
    )
    assert reactivated.json()["is_active"] is True
    events = [e.event_code for e in await audit_events(session_factory)]
    assert events.count("reference_data.disabled") == 2


async def test_contact_lifecycle_and_stale_versions(
    api: AsyncClient, admin_headers: dict[str, str], world: World
) -> None:
    created = await api.post(
        f"{API}/contacts",
        json={"kind": "person", "display_name": " New  Contact ", "telephone": "+44 7700 900123"},
        headers=admin_headers,
    )
    contact = created.json()
    path = f"{API}/contacts/{contact['id']}"

    first = await api.patch(
        path, json={"version": 1, "organization_name": "Acme"}, headers=admin_headers
    )
    stale = await api.patch(
        path, json={"version": 1, "organization_name": "Stale"}, headers=admin_headers
    )
    archived = await api.delete(path, headers=admin_headers)
    edit_archived = await api.patch(
        path, json={"version": 3, "organization_name": "Late"}, headers=admin_headers
    )
    restored = await api.post(f"{path}/restore", headers=admin_headers)
    blocked = await api.delete(f"{API}/contacts/{world.contact_id}", headers=admin_headers)

    assert (contact["display_name"], contact["telephone"]) == ("New Contact", "+447700900123")
    assert first.json()["version"] == 2
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_version"
    assert archived.json()["status"] == "archived"
    assert edit_archived.json()["error"]["code"] == "archived_record"
    assert restored.json()["status"] == "active"
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "dependency_conflict"


async def test_contact_list_pages_and_hides_notes(
    api: AsyncClient, admin_headers: dict[str, str], world: World
) -> None:
    for name in ("Bea", "Al", "Cy"):
        await api.post(
            f"{API}/contacts",
            json={"kind": "person", "display_name": name, "email": f"{name.lower()}@example.com"},
            headers=admin_headers,
        )

    page = await api.get(f"{API}/contacts?limit=2&offset=1", headers=admin_headers)
    body = page.json()
    assert (body["total"], body["limit"], body["offset"]) == (4, 2, 1)
    assert [row["display_name"] for row in body["items"]] == ["Bea", "Cy"]
    assert "internal_notes" not in body["items"][0] and "address_line_1" not in body["items"][0]


async def test_contact_notes_need_read_internal(session_factory: Sessions, world: World) -> None:
    actor = await admin_actor(session_factory)
    async with session_factory() as db:
        contact = await ContactService(db).get_contact(actor, world.contact_id)
    restricted = Actor(user_id=uuid.uuid4(), role_codes=frozenset(), active=True)

    assert contact_view(actor, contact).internal_notes == "Prefers email"
    hidden = contact_view(restricted, contact).model_dump(mode="json")
    assert "internal_notes" not in hidden
    assert isinstance(contact_view(restricted, contact), ContactDetail)


async def test_owner_responses_follow_field_permissions(
    api: AsyncClient, session_factory: Sessions, world: World
) -> None:
    manager = await as_role(api, session_factory, "manager")
    accountant = await as_role(api, session_factory, "accountant")

    owners = (await api.get(f"{API}/properties/{world.property_id}/owners", headers=manager)).json()

    assert owners["items"][0]["contact"]["email"] == "olive@example.com"
    assert owners["shares"] == {"known_total": "50.00", "unknown_count": 0, "complete": False}
    assert_error(
        await api.get(f"{API}/properties/{world.property_id}/owners", headers=accountant),
        403,
        "permission_denied",
    )


async def test_ownership_shares_and_history_over_http(
    api: AsyncClient, admin_headers: dict[str, str], session_factory: Sessions, world: World
) -> None:
    owners = f"{API}/properties/{world.property_id}/owners"
    second = await api.post(
        f"{API}/contacts",
        json={"kind": "person", "display_name": "Sam", "email": "sam@example.com"},
        headers=admin_headers,
    )
    third = await api.post(
        f"{API}/contacts",
        json={"kind": "person", "display_name": "Tia", "email": "tia@example.com"},
        headers=admin_headers,
    )

    added = await api.post(
        owners,
        json={"contact_id": second.json()["id"], "share_percentage": "50"},
        headers=admin_headers,
    )
    over = await api.post(
        owners,
        json={"contact_id": third.json()["id"], "share_percentage": "0.01"},
        headers=admin_headers,
    )
    duplicate = await api.post(
        owners, json={"contact_id": str(world.contact_id)}, headers=admin_headers
    )
    ended = await api.delete(f"{owners}/{world.ownership_id}", headers=admin_headers)
    edit_ended = await api.patch(
        f"{owners}/{world.ownership_id}", json={"notes": "x"}, headers=admin_headers
    )
    history = await api.get(f"{owners}?include_archived=true", headers=admin_headers)

    assert added.status_code == 201
    assert added.headers["location"].endswith(f"/owners/{added.json()['id']}")
    assert over.status_code == 409 and over.json()["error"]["code"] == "conflict"
    assert over.json()["error"]["fields"] == {
        "share_percentage": ["Known ownership shares in force on the same day would exceed 100%."]
    }
    assert duplicate.json()["error"]["code"] == "duplicate_reference"
    assert ended.json()["archived_at"] is not None
    assert edit_ended.json()["error"]["code"] == "archived_record"
    assert len(history.json()["items"]) == 2


async def test_concurrent_owner_additions_over_http(
    api: AsyncClient, admin_headers: dict[str, str], world: World
) -> None:
    contacts = [
        (
            await api.post(
                f"{API}/contacts",
                json={"kind": "person", "display_name": f"C{i}", "email": f"c{i}@example.com"},
                headers=admin_headers,
            )
        ).json()["id"]
        for i in range(4)
    ]

    responses: list[Response] = await asyncio.gather(
        *(
            api.post(
                f"{API}/properties/{world.property_id}/owners",
                json={"contact_id": contact, "share_percentage": "25"},
                headers=admin_headers,
            )
            for contact in contacts
        )
    )

    # 50% is already taken, so exactly two 25% additions fit.
    assert sorted(r.status_code for r in responses) == [201, 201, 409, 409]


async def test_successful_writes_are_audited_without_personal_data(
    api: AsyncClient, admin_headers: dict[str, str], session_factory: Sessions, world: World
) -> None:
    await api.post(
        f"{API}/contacts",
        json={"kind": "person", "display_name": "Private Person", "email": "private@example.com"},
        headers=admin_headers | {"x-request-id": "req-contact"},
    )

    [event] = [
        e
        for e in await audit_events(session_factory, "contact.created")
        if e.request_id == "req-contact"
    ]
    assert event.details == {"kind": "person"}
    async with session_factory() as db:
        rendered = str(await db.scalar(text("SELECT json_agg(details) FROM audit_events")))
    assert "private@example.com" not in rendered and "Private Person" not in rendered
