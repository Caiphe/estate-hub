"""HTTP: property create, directory, detail, update, archive, and restore."""

import copy
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pytest
from auth_support import assert_error, bearer, create_staff, csrf_header, login, token_for
from catalog_support import audit_events
from httpx import AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.v1.routes.properties import CREATE_EXAMPLES
from app.auth.policy import Actor
from app.catalog.models import Amenity, PropertySubtype, PropertyType
from app.contacts.schemas import ContactCreate
from app.contacts.service import ContactService
from app.main import app
from app.properties.schemas import PropertySort
from app.users.constants import RoleCode

Sessions = async_sessionmaker[AsyncSession]
PROPERTIES = "/api/v1/properties"
EVERYONE = {"administrator", "manager", "agent", "accountant"}
WRITERS = {"administrator", "manager"}


@dataclass(frozen=True)
class Ref:
    residential: uuid.UUID
    house: uuid.UUID
    apartment: uuid.UUID
    commercial: uuid.UUID
    shop: uuid.UUID
    garden: uuid.UUID
    pool: uuid.UUID
    owner: uuid.UUID


@pytest.fixture
async def ref(session_factory: Sessions) -> Ref:
    async with session_factory() as db:
        residential = PropertyType(name="Residential")
        residential.subtypes = [PropertySubtype(name="House"), PropertySubtype(name="Apartment")]
        commercial = PropertyType(name="Commercial")
        commercial.subtypes = [PropertySubtype(name="Shop")]
        garden, pool = Amenity(name="Garden"), Amenity(name="Pool")
        db.add_all([residential, commercial, garden, pool])
        await db.commit()
        ids = (
            residential.id,
            residential.subtypes[0].id,
            residential.subtypes[1].id,
            commercial.id,
            commercial.subtypes[0].id,
            garden.id,
            pool.id,
        )
    admin = await create_staff(session_factory, ["administrator"])
    actor = Actor(user_id=admin.id, role_codes=frozenset({"administrator"}), active=True)
    async with session_factory() as db:
        owner = await ContactService(db).create_contact(
            actor,
            ContactCreate(
                kind="person", display_name="Olive Proprietor", email="olive@example.com"
            ),
        )
    return Ref(*ids, owner.id)


def body(ref: Ref, **overrides: Any) -> dict[str, Any]:
    return {
        "name": "Rose Cottage",
        "property_type_id": str(ref.residential),
        "property_subtype_id": str(ref.house),
        "address_line_1": "1 High Street",
        "locality": "Bath",
        "region": "Somerset",
        "country_code": "GB",
    } | overrides


async def headers_for(api: AsyncClient, session_factory: Sessions, role: str) -> dict[str, str]:
    return bearer(await token_for(api, await create_staff(session_factory, [role])))


@pytest.fixture
async def admin(api: AsyncClient, session_factory: Sessions) -> dict[str, str]:
    return await headers_for(api, session_factory, "administrator")


async def create(
    api: AsyncClient, headers: dict[str, str], payload: dict[str, Any]
) -> dict[str, Any]:
    response = await api.post(PROPERTIES, json=payload, headers=headers)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


# --- Create -----------------------------------------------------------------------------


async def test_openapi_examples_create_standalone_and_multi_unit_properties(
    api: AsyncClient, admin: dict[str, str], ref: Ref
) -> None:
    standalone = copy.deepcopy(CREATE_EXAMPLES["standalone"]["value"])
    standalone |= {
        "property_type_id": str(ref.residential),
        "property_subtype_id": str(ref.house),
        "amenity_ids": [str(ref.garden)],
        "owners": [{"contact_id": str(ref.owner), "share_percentage": "100.00"}],
    }
    multi = copy.deepcopy(CREATE_EXAMPLES["multi_unit"]["value"])
    multi["property_type_id"] = str(ref.residential)
    for unit in multi["units"]:
        unit["property_subtype_id"] = str(ref.apartment)

    house = await api.post(PROPERTIES, json=standalone, headers=admin)
    court = await api.post(PROPERTIES, json=multi, headers=admin)

    assert house.status_code == 201 and court.status_code == 201
    assert house.headers["location"].endswith(f"/properties/{house.json()['id']}")
    fetched = (await api.get(house.headers["location"], headers=admin)).json()
    assert fetched == house.json()
    assert fetched["reference"].startswith("PR-") and fetched["version"] == 1
    assert (fetched["latitude"], fetched["bathrooms"]) == ("51.381072", "1.5")
    assert fetched["owners"]["shares"]["complete"] is True
    assert [u["identifier"] for u in court.json()["units"]] == ["Flat 1", "Flat 2"]
    assert court.json()["management_mode"] == "units"


@pytest.mark.parametrize(
    ("overrides", "status", "code"),
    [
        ({"property_type_id": "commercial"}, 422, "invalid_relationship"),
        ({"property_subtype_id": "shop"}, 422, "invalid_relationship"),
        ({"amenity_ids": ["disabled"]}, 422, "invalid_relationship"),
        ({"property_type_id": str(uuid.uuid4())}, 422, "invalid_relationship"),
        ({"latitude": "51.5"}, 422, "validation_error"),
        ({"reference": "PR-000001"}, 422, "validation_error"),
        ({"status": "archived"}, 422, "validation_error"),
        ({"owners": [{"contact_id": "owner", "share_percentage": "101"}]}, 422, "validation_error"),
    ],
)
async def test_create_rejects_invalid_and_inactive_references(
    api: AsyncClient,
    session_factory: Sessions,
    admin: dict[str, str],
    ref: Ref,
    overrides: dict[str, Any],
    status: int,
    code: str,
) -> None:
    async with session_factory() as db:
        await db.execute(
            text("UPDATE property_types SET is_active = false WHERE name = 'Commercial'")
        )
        await db.execute(text("UPDATE amenities SET is_active = false WHERE name = 'Pool'"))
        await db.commit()
    names = {
        "commercial": str(ref.commercial),
        "shop": str(ref.shop),
        "disabled": str(ref.pool),
        "owner": str(ref.owner),
    }

    def resolve(value: Any) -> Any:
        if isinstance(value, str):
            return names.get(value, value)
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if isinstance(value, dict):
            return {key: resolve(item) for key, item in value.items()}
        return value

    response = await api.post(PROPERTIES, json=body(ref, **resolve(overrides)), headers=admin)

    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    async with session_factory() as db:
        assert await db.scalar(text("SELECT count(*) FROM properties")) == 0


# --- Permissions, authentication, CSRF --------------------------------------------------

ROUTES: list[tuple[str, str, dict[str, Any] | None, int, set[str]]] = [
    ("GET", "", None, 200, EVERYONE),
    ("POST", "", {}, 201, WRITERS),
    ("GET", "/{id}", None, 200, EVERYONE),
    ("PATCH", "/{id}", {"version": 1, "bedrooms": 4}, 200, WRITERS),
    ("DELETE", "/{id}", None, 200, WRITERS),
    ("POST", "/{id}/restore", None, 200, WRITERS),
]


async def catalog_event_count(session_factory: Sessions) -> int:
    """Business events only; signing in writes auth.* events."""
    return len(
        [e for e in await audit_events(session_factory) if not e.event_code.startswith("auth.")]
    )


@pytest.mark.parametrize("role", [role.value for role in RoleCode])
@pytest.mark.parametrize(("method", "path", "payload", "success", "allowed"), ROUTES)
async def test_every_route_for_every_role(
    api: AsyncClient,
    session_factory: Sessions,
    admin: dict[str, str],
    ref: Ref,
    role: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    success: int,
    allowed: set[str],
) -> None:
    existing = await create(api, admin, body(ref))
    before = await catalog_event_count(session_factory)
    json = body(ref, name="New") if payload == {} else payload

    response = await api.request(
        method,
        PROPERTIES + path.format(id=existing["id"]),
        json=json,
        headers=await headers_for(api, session_factory, role),
    )

    if role in allowed:
        assert response.status_code == success, response.text
    else:
        assert_error(response, 403, "permission_denied")
        assert await catalog_event_count(session_factory) == before


@pytest.mark.parametrize(("method", "path", "payload", "success", "allowed"), ROUTES)
async def test_every_route_requires_authentication(
    api: AsyncClient,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    success: int,
    allowed: set[str],
) -> None:
    response = await api.request(method, PROPERTIES + path.format(id=uuid.uuid4()), json=payload)

    assert_error(response, 401, "authentication_required")


async def test_permission_is_checked_before_existence(
    api: AsyncClient, session_factory: Sessions, admin: dict[str, str]
) -> None:
    accountant = await headers_for(api, session_factory, "accountant")
    missing = f"{PROPERTIES}/{uuid.uuid4()}"

    # Without the route's permission, a missing ID and an existing one look the same.
    assert_error(
        await api.patch(missing, json={"version": 1, "name": "X"}, headers=accountant),
        403,
        "permission_denied",
    )
    assert_error(await api.delete(missing, headers=accountant), 403, "permission_denied")
    for method in ("GET", "DELETE"):
        response = await api.request(method, missing, headers=admin)
        assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"
    assert (await api.get(f"{PROPERTIES}/not-a-uuid", headers=admin)).status_code == 422


async def test_cookie_mutations_require_csrf(
    api: AsyncClient, session_factory: Sessions, ref: Ref
) -> None:
    user = await create_staff(session_factory, ["manager"])
    await login(api, user.email)

    assert_error(await api.post(PROPERTIES, json=body(ref)), 403, "csrf_failed")
    created = await api.post(PROPERTIES, json=body(ref), headers=csrf_header(api))
    path = f"{PROPERTIES}/{created.json()['id']}"
    assert_error(await api.patch(path, json={"version": 1, "name": "X"}), 403, "csrf_failed")
    assert_error(await api.delete(path), 403, "csrf_failed")
    assert (await api.get(path)).status_code == 200  # Safe methods need no token.
    assert (await api.delete(path, headers=csrf_header(api))).status_code == 200


# --- Detail privacy ---------------------------------------------------------------------


async def test_private_fields_follow_permissions(
    api: AsyncClient, session_factory: Sessions, admin: dict[str, str], ref: Ref
) -> None:
    created = await create(
        api,
        admin,
        body(
            ref,
            internal_notes="Alarm code 1234",
            owners=[{"contact_id": str(ref.owner), "notes": "Pays late"}],
        ),
    )
    path = f"{PROPERTIES}/{created['id']}"

    agent = (await api.get(path, headers=await headers_for(api, session_factory, "agent"))).json()
    accountant_response = await api.get(
        path, headers=await headers_for(api, session_factory, "accountant")
    )
    accountant = accountant_response.json()

    assert agent["internal_notes"] == "Alarm code 1234"
    assert agent["owners"]["items"][0]["contact"]["email"] == "olive@example.com"
    assert "internal_notes" not in accountant and "owners" not in accountant
    for private in ("Alarm code", "olive@example.com", "Olive Proprietor", "Pays late", "storage"):
        assert private not in accountant_response.text


# --- Update, archive, restore -----------------------------------------------------------


async def test_partial_update_stale_version_and_conflicts(
    api: AsyncClient, admin: dict[str, str], ref: Ref
) -> None:
    created = await create(
        api,
        admin,
        body(
            ref, property_subtype_id=None, management_mode="mixed", units=[{"identifier": "Flat 1"}]
        ),
    )
    path = f"{PROPERTIES}/{created['id']}"

    updated = await api.patch(
        path, json={"version": 1, "bedrooms": 4, "postal_code": "ba1 1aa"}, headers=admin
    )
    stale = await api.patch(path, json={"version": 1, "name": "Stale"}, headers=admin)
    cleared = await api.patch(path, json={"version": 2, "postal_code": None}, headers=admin)
    whole = await api.patch(path, json={"version": 3, "management_mode": "whole"}, headers=admin)
    nulled = await api.patch(path, json={"version": 3, "name": None}, headers=admin)

    assert (
        updated.json()["bedrooms"],
        updated.json()["postal_code"],
        updated.json()["version"],
    ) == (4, "BA1 1AA", 2)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_version"
    assert (cleared.json()["postal_code"], cleared.json()["name"]) == (None, "Rose Cottage")
    assert whole.status_code == 409 and whole.json()["error"]["code"] == "dependency_conflict"
    assert nulled.status_code == 422


async def test_archive_and_restore_cycle(
    api: AsyncClient, session_factory: Sessions, admin: dict[str, str], ref: Ref
) -> None:
    created = await create(api, admin, body(ref, name="Gone Cottage", status="active"))
    path = f"{PROPERTIES}/{created['id']}"
    agent = await headers_for(api, session_factory, "agent")

    archived = await api.delete(path, headers=admin)
    listed = await api.get(PROPERTIES, headers=admin)
    with_archived = await api.get(f"{PROPERTIES}?include_archived=true", headers=admin)
    agent_archived = await api.get(f"{PROPERTIES}?include_archived=true", headers=agent)
    still_readable = await api.get(path, headers=agent)
    edit = await api.patch(
        path, json={"version": archived.json()["version"], "name": "X"}, headers=admin
    )
    restored = await api.post(f"{path}/restore", headers=admin)

    assert archived.json()["status"] == "archived"
    assert listed.json()["total"] == 0
    assert [p["id"] for p in with_archived.json()["items"]] == [created["id"]]
    assert_error(agent_archived, 403, "permission_denied")
    assert still_readable.json()["status"] == "archived"
    assert edit.json()["error"]["code"] == "archived_record"
    assert restored.json()["status"] == "inactive" and restored.json()["archived_at"] is None
    assert (await api.get(PROPERTIES, headers=admin)).json()["total"] == 1


# --- Directory --------------------------------------------------------------------------


@pytest.fixture
async def directory(api: AsyncClient, admin: dict[str, str], ref: Ref) -> dict[str, str]:
    rows = [
        body(
            ref,
            name="Alpha House",
            status="active",
            amenity_ids=[str(ref.garden), str(ref.pool)],
            owners=[{"contact_id": str(ref.owner)}],
        ),
        body(
            ref,
            name="beta flat",
            property_subtype_id=str(ref.apartment),
            locality="Bristol",
            region="Avon",
            status="draft",
            amenity_ids=[str(ref.pool)],
        ),
        body(
            ref,
            name="Corner Shop",
            property_type_id=str(ref.commercial),
            property_subtype_id=str(ref.shop),
            country_code="IE",
            status="inactive",
            management_mode="units",
            units=[{"identifier": "A"}, {"identifier": "B"}],
        ),
    ]
    return {row["name"]: (await create(api, admin, row))["id"] for row in rows}


async def names(api: AsyncClient, headers: dict[str, str], query: str) -> tuple[list[str], int]:
    response = await api.get(f"{PROPERTIES}?sort=name&{query}", headers=headers)
    assert response.status_code == 200, response.text
    page = response.json()
    return [row["name"] for row in page["items"]], page["total"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("", ["Alpha House", "beta flat", "Corner Shop"]),
        ("status=active&status=draft", ["Alpha House", "beta flat"]),
        ("property_type_id={commercial}", ["Corner Shop"]),
        (
            "property_subtype_id={apartment}&property_subtype_id={shop}",
            ["beta flat", "Corner Shop"],
        ),
        ("amenity_id={pool}", ["Alpha House", "beta flat"]),
        ("amenity_id={pool}&amenity_id={garden}", ["Alpha House"]),
        ("management_mode=units", ["Corner Shop"]),
        ("locality=BRISTOL", ["beta flat"]),
        ("region=avon", ["beta flat"]),
        ("country_code=ie", ["Corner Shop"]),
        ("q=FLAT", ["beta flat"]),
        ("q=PR-", ["Alpha House", "beta flat", "Corner Shop"]),
        ("q=proprietor", ["Alpha House"]),
        ("q=%25", []),
    ],
)
async def test_every_filter(
    api: AsyncClient,
    admin: dict[str, str],
    ref: Ref,
    directory: dict[str, str],
    query: str,
    expected: list[str],
) -> None:
    filled = query.format(
        commercial=ref.commercial,
        apartment=ref.apartment,
        shop=ref.shop,
        pool=ref.pool,
        garden=ref.garden,
    )

    assert await names(api, admin, filled) == (expected, len(expected))


async def test_summary_rows(
    api: AsyncClient, admin: dict[str, str], directory: dict[str, str]
) -> None:
    rows = (await api.get(f"{PROPERTIES}?q=Corner", headers=admin)).json()["items"]

    assert rows[0]["unit_count"] == 2 and rows[0]["property_type"]["name"] == "Commercial"
    assert rows[0]["cover_media_id"] is None
    assert not {"address_line_1", "internal_notes", "owners", "postal_code"} & set(rows[0])


@pytest.mark.parametrize("sort", list(PropertySort), ids=str)
async def test_every_sort_key_and_direction(
    api: AsyncClient, admin: dict[str, str], directory: dict[str, str], sort: PropertySort
) -> None:
    response = await api.get(f"{PROPERTIES}?sort={sort.value}", headers=admin)
    rows = response.json()["items"]

    assert response.status_code == 200 and len(rows) == 3
    # created_at is not part of a summary row; every other key can be checked directly.
    field = sort.value.lstrip("-")
    if field != "created_at":
        values = [str(row[field]).lower() for row in rows]
        assert values == sorted(values, reverse=sort.value.startswith("-"))


async def test_pagination_boundaries(
    api: AsyncClient, admin: dict[str, str], directory: dict[str, str]
) -> None:
    first = (await api.get(f"{PROPERTIES}?sort=name&limit=1", headers=admin)).json()
    last = (await api.get(f"{PROPERTIES}?sort=name&limit=1&offset=2", headers=admin)).json()
    beyond = (await api.get(f"{PROPERTIES}?offset=50", headers=admin)).json()
    largest = await api.get(f"{PROPERTIES}?limit=100", headers=admin)

    assert ([r["name"] for r in first["items"]], first["total"]) == (["Alpha House"], 3)
    assert [r["name"] for r in last["items"]] == ["Corner Shop"]
    assert (beyond["items"], beyond["total"], beyond["offset"]) == ([], 3, 50)
    assert largest.status_code == 200


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "offset=-1",
        "sort=price",
        "sort=name%20desc",
        "status=sold",
        "status=archived",
        "management_mode=partial",
        "property_type_id=not-a-uuid",
        "country_code=GBR",
        "q=",
        "colour=red",
    ],
)
async def test_invalid_filters_are_rejected(
    api: AsyncClient, admin: dict[str, str], query: str
) -> None:
    response = await api.get(f"{PROPERTIES}?{query}", headers=admin)

    assert response.status_code == 422, query
    assert response.json()["error"]["code"] == "validation_error"


async def test_owner_name_search_needs_ownership_read(
    api: AsyncClient, session_factory: Sessions, directory: dict[str, str]
) -> None:
    accountant = await headers_for(api, session_factory, "accountant")

    assert await names(api, accountant, "q=proprietor") == ([], 0)


# --- Query shape ------------------------------------------------------------------------


@contextmanager
def statements(engine: AsyncEngine) -> Iterator[list[str]]:
    seen: list[str] = []

    def record(*args: Any) -> None:
        seen.append(args[2])

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)


async def test_detail_and_list_queries_do_not_grow_with_rows(
    api: AsyncClient,
    db_engine: AsyncEngine,
    admin: dict[str, str],
    ref: Ref,
    session_factory: Sessions,
) -> None:
    contacts = []
    actor_user = await create_staff(session_factory, ["administrator"])
    actor = Actor(user_id=actor_user.id, role_codes=frozenset({"administrator"}), active=True)
    for index in range(6):
        async with session_factory() as db:
            contact = await ContactService(db).create_contact(
                actor,
                ContactCreate(
                    kind="person", display_name=f"C{index}", email=f"c{index}@example.com"
                ),
            )
            contacts.append(str(contact.id))

    async def detail_queries(units: int, owners: int) -> int:
        created = await create(
            api,
            admin,
            body(
                ref,
                management_mode="units",
                amenity_ids=[str(ref.garden), str(ref.pool)],
                units=[
                    {
                        "identifier": f"U{i}",
                        "amenity_ids": [str(ref.garden)],
                        "property_subtype_id": str(ref.apartment),
                    }
                    for i in range(units)
                ],
                owners=[{"contact_id": contact} for contact in contacts[:owners]],
            ),
        )
        with statements(db_engine) as seen:
            response = await api.get(f"{PROPERTIES}/{created['id']}", headers=admin)
        assert len(response.json()["units"]) == units
        return len(seen)

    async def list_queries(limit: int) -> int:
        with statements(db_engine) as seen:
            response = await api.get(f"{PROPERTIES}?limit={limit}", headers=admin)
        assert len(response.json()["items"]) == limit
        return len(seen)

    small_detail, large_detail = await detail_queries(1, 1), await detail_queries(10, 6)
    small_list, large_list = await list_queries(1), await list_queries(2)
    assert small_detail == large_detail and small_detail >= 5  # The listener really counts.
    assert small_list == large_list and small_list >= 3


def test_openapi_documents_routes_examples_and_errors() -> None:
    spec = app.openapi()
    create_operation = spec["paths"][PROPERTIES]["post"]
    examples = create_operation["requestBody"]["content"]["application/json"]["examples"]

    assert set(examples) == {"standalone", "multi_unit"}
    assert {"201", "401", "403", "409", "422"} <= set(create_operation["responses"])
    for method, path, *_ in ROUTES:
        operation = spec["paths"][PROPERTIES + path.replace("{id}", "{property_id}")][
            method.lower()
        ]
        assert operation["security"] == [{"OAuth2PasswordBearer": []}]
        assert {"401", "403", "422"} <= set(operation["responses"])
    parameters = {p["name"] for p in spec["paths"][PROPERTIES]["get"]["parameters"]}
    assert {"status", "amenity_id", "sort", "include_archived", "limit", "offset"} <= parameters
