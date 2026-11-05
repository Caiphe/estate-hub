"""Milestone checks for the property-catalog API as a whole (prompt 02, stage 12)."""

import inspect
import io
import logging
import pkgutil
import subprocess
import sys
import typing
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from auth_support import bearer, create_staff, token_for
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from httpx import AsyncClient
from migration_support import make_alembic_config, query, temporary_database
from PIL import Image
from route_support import iter_api_routes
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

import app
from alembic import command
from app.api.v1.routes.files import get_storage
from app.auth import policy
from app.auth.dependencies import get_current_identity
from app.catalog import limits
from app.catalog.contracts import CATALOG_ROUTES
from app.catalog.errors import CatalogConflictError
from app.core.config import get_settings
from app.core.database import Base
from app.core.pagination import Page
from app.main import app as application
from app.media.storage import LocalStorage

Sessions = async_sessionmaker[AsyncSession]
PREFIX = get_settings().api_v1_prefix
CATALOG_ROOTS = tuple(
    f"{PREFIX}/{r}" for r in ("property-types", "amenities", "contacts", "properties")
)
# Returned whole because forms and reorder requests need the complete set; each is
# bounded by a cap in app/catalog/limits.py.
CAPPED_WHOLE_LISTS = {
    ("GET", f"{PREFIX}/property-types"): limits.MAX_PROPERTY_TYPES,
    ("PUT", f"{PREFIX}/property-types/order"): limits.MAX_PROPERTY_TYPES,
    (
        "PUT",
        f"{PREFIX}/property-types/{{property_type_id}}/subtypes/order",
    ): limits.MAX_SUBTYPES_PER_TYPE,
    ("GET", f"{PREFIX}/amenities"): limits.MAX_AMENITIES,
    ("PUT", f"{PREFIX}/amenities/order"): limits.MAX_AMENITIES,
    (
        "PUT",
        f"{PREFIX}/properties/{{property_id}}/media/order",
    ): limits.MAX_ACTIVE_IMAGES_PER_PARENT,
    (
        "PUT",
        f"{PREFIX}/properties/{{property_id}}/units/{{unit_id}}/media/order",
    ): limits.MAX_ACTIVE_IMAGES_PER_PARENT,
}


def catalog_routes() -> Iterator[tuple[str, str, APIRoute]]:
    for path, route in iter_api_routes(application):
        if path.startswith(CATALOG_ROOTS):
            for method in (route.methods or set()) - {"HEAD", "OPTIONS"}:
                yield method, path, route


def dependency_calls(dependant: Dependant) -> Iterator[Callable[..., Any]]:
    for child in dependant.dependencies:
        if child.call is not None:
            yield child.call
        yield from dependency_calls(child)


def guard_permissions(route: APIRoute) -> list[tuple[str, frozenset[str]]]:
    """(mode, permissions) for every permission guard in the route's dependency tree."""
    guards = []
    for call in dependency_calls(route.dependant):
        # Some dependencies are class instances (OAuth2PasswordBearer) with no qualname.
        if getattr(call, "__qualname__", "").endswith("_guard.<locals>.dependency"):
            closure = inspect.getclosurevars(call).nonlocals
            mode = "all" if closure["check"] is policy.require_permissions else "any"
            guards.append((mode, frozenset(p.value for p in closure["permissions"])))
    return guards


# --- Authentication, permissions, CSRF --------------------------------------------------


def test_every_catalog_route_has_exactly_its_contract_permission() -> None:
    contracts: dict[tuple[str, str], str] = {
        (r.method, PREFIX + r.path): r.permission.value for r in CATALOG_ROUTES
    }
    seen = 0
    for method, path, route in catalog_routes():
        guards = guard_permissions(route)
        assert guards == [("all", frozenset({contracts[(method, path)]}))], f"{method} {path}"
        seen += 1
    assert seen == len(CATALOG_ROUTES) == 71


def test_every_catalog_route_authenticates_through_the_csrf_checking_identity() -> None:
    # get_current_identity authenticates every request and, for cookie-authenticated
    # unsafe methods, requires the CSRF header. No catalog route may skip it.
    for method, path, route in catalog_routes():
        assert get_current_identity in set(dependency_calls(route.dependant)), f"{method} {path}"


# --- Bounded collections ----------------------------------------------------------------


def test_every_collection_is_paginated_or_capped() -> None:
    whole_lists = set()
    paths = application.openapi()["paths"]
    for method, path, route in catalog_routes():
        model = route.response_model
        if typing.get_origin(model) is list:
            whole_lists.add((method, path))
        elif isinstance(model, type) and issubclass(model, Page):
            parameters = {p["name"] for p in paths[path][method.lower()].get("parameters", [])}
            assert {"limit", "offset"} <= parameters, f"{method} {path}"

    assert whole_lists == set(CAPPED_WHOLE_LISTS)
    assert all(cap <= 200 for cap in CAPPED_WHOLE_LISTS.values())


@pytest.mark.parametrize(
    ("cap", "path", "body"),
    [
        ("MAX_PROPERTY_TYPES", "/property-types", {"name": "Second"}),
        ("MAX_AMENITIES", "/amenities", {"name": "Second"}),
        ("MAX_SUBTYPES_PER_TYPE", "/property-types/{type}/subtypes", {"name": "Second"}),
        ("MAX_ACTIVE_UNITS_PER_PROPERTY", "/properties/{property}/units", {"identifier": "B"}),
        ("MAX_CURRENT_OWNERS_PER_PROPERTY", "/properties/{property}/owners", "owner"),
        ("MAX_ACTIVE_IMAGES_PER_PARENT", "/properties/{property}/media", "image"),
    ],
)
async def test_caps_are_enforced(
    api: AsyncClient,
    session_factory: Sessions,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cap: str,
    path: str,
    body: Any,
) -> None:
    headers = bearer(await token_for(api, await create_staff(session_factory, ["administrator"])))
    application.dependency_overrides[get_storage] = lambda: LocalStorage(tmp_path)
    world = await _one_of_each(api, headers)
    # Each module imported its cap by name; lower it where it is used.
    for module in (
        "app.catalog.service",
        "app.properties.units",
        "app.properties.ownership",
        "app.media.service",
    ):
        if hasattr(sys.modules[module], cap):
            monkeypatch.setattr(sys.modules[module], cap, 1)

    url = PREFIX + path.format(**world)
    if body == "image":
        response = await api.post(
            url, files={"file": ("b.png", _png(), "image/png")}, headers=headers
        )
    elif body == "owner":
        contact = await api.post(
            f"{PREFIX}/contacts",
            json={"kind": "person", "display_name": "Second", "email": "second@example.com"},
            headers=headers,
        )
        response = await api.post(url, json={"contact_id": contact.json()["id"]}, headers=headers)
    else:
        response = await api.post(url, json=body, headers=headers)

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == CatalogConflictError.code.value
    assert "reached its limit of 1" in str(response.json()["error"]["fields"])


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, format="PNG")
    return buffer.getvalue()


async def _one_of_each(api: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    """One record in every capped list, so the next one reaches a cap of 1."""
    kind = (
        await api.post(f"{PREFIX}/property-types", json={"name": "First"}, headers=headers)
    ).json()
    await api.post(
        f"{PREFIX}/property-types/{kind['id']}/subtypes", json={"name": "First"}, headers=headers
    )
    await api.post(f"{PREFIX}/amenities", json={"name": "First"}, headers=headers)
    contact = await api.post(
        f"{PREFIX}/contacts",
        json={"kind": "person", "display_name": "First", "email": "first@example.com"},
        headers=headers,
    )
    created = await api.post(
        f"{PREFIX}/properties",
        json={
            "name": "Rose Court",
            "property_type_id": kind["id"],
            "management_mode": "units",
            "address_line_1": "1 High Street",
            "locality": "Bath",
            "region": "Somerset",
            "country_code": "GB",
            "units": [{"identifier": "A"}],
            "owners": [{"contact_id": contact.json()["id"]}],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    property_id = created.json()["id"]
    image = await api.post(
        f"{PREFIX}/properties/{property_id}/media",
        files={"file": ("a.png", _png(), "image/png")},
        headers=headers,
    )
    assert image.status_code == 201, image.text
    return {"type": kind["id"], "property": property_id}


# --- Models and imports -----------------------------------------------------------------


def test_every_table_is_registered_once() -> None:
    import app.models as registry

    names = [table.name for table in Base.metadata.sorted_tables]
    assert len(names) == len(set(names))
    assert {
        "property_types",
        "property_subtypes",
        "amenities",
        "properties",
        "property_amenities",
        "contacts",
        "property_ownerships",
        "units",
        "unit_amenities",
        "media_assets",
        "documents",
    } <= set(names)
    assert len(registry.__all__) == len(set(registry.__all__))


def test_every_module_imports_on_its_own() -> None:
    """Each module in a fresh interpreter, so an import cycle cannot hide behind an
    earlier import that happened to load things in a working order."""
    modules = [m.name for m in pkgutil.walk_packages(app.__path__, "app.")]
    script = (
        "import importlib, sys\n"
        "for name in sys.argv[1:]:\n"
        "    for loaded in [m for m in sys.modules if m == 'app' or m.startswith('app.')]:\n"
        "        del sys.modules[loaded]\n"
        "    importlib.import_module(name)\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", script, *modules],
        capture_output=True,
        text=True,
        cwd=Path(app.__path__[0]).parent,
        check=False,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert len(modules) > 60


# --- Upgrading an existing authentication database --------------------------------------


def test_authentication_database_upgrades_without_data_loss() -> None:
    with temporary_database("estatehub_milestone_upgrade") as url:
        config = make_alembic_config(url)
        command.upgrade(config, "20261103_0001")
        user_id = uuid.uuid4()

        async def seed(connection: AsyncConnection) -> None:
            await connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash) "
                    "VALUES (:id, 'kept@estatehub.example', 'Kept User', 'hash')"
                ),
                {"id": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO user_roles (user_id, role_id) SELECT :id, id FROM roles "
                    "WHERE code = 'manager'"
                ),
                {"id": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO audit_events (id, actor_id, event_code) "
                    "VALUES (gen_random_uuid(), :id, 'auth.login_succeeded')"
                ),
                {"id": user_id},
            )

        async def snapshot(connection: AsyncConnection) -> tuple[Any, ...]:
            row = await connection.execute(
                text(
                    "SELECT u.email, u.full_name, r.code, "
                    "(SELECT count(*) FROM audit_events WHERE actor_id = u.id), "
                    "(SELECT count(*) FROM roles) "
                    "FROM users u JOIN user_roles ur ON ur.user_id = u.id "
                    "JOIN roles r ON r.id = ur.role_id WHERE u.id = :id"
                ),
                {"id": user_id},
            )
            return tuple(row.one())

        query(url, seed)
        before = query(url, snapshot)

        command.upgrade(config, "head")

        assert (
            query(url, snapshot)
            == before
            == ("kept@estatehub.example", "Kept User", "manager", 1, 4)
        )
        command.check(config)


# --- Logs -------------------------------------------------------------------------------


async def test_logs_never_contain_contact_details_files_or_tokens(
    api: AsyncClient, session_factory: Sessions, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    token = await token_for(api, await create_staff(session_factory, ["administrator"]))
    headers = bearer(token)
    application.dependency_overrides[get_storage] = lambda: LocalStorage(tmp_path)
    world = await _one_of_each(api, headers)
    contact = await api.post(
        f"{PREFIX}/contacts",
        json={
            "kind": "person",
            "display_name": "Private Person",
            "email": "private.person@example.com",
            "telephone": "+447700900321",
            "internal_notes": "Secret note",
        },
        headers=headers,
    )
    media = await api.post(
        f"{PREFIX}/properties/{world['property']}/media",
        files={"file": ("private-photo.png", _png(), "image/png")},
        headers=headers,
    )
    await api.get(media.headers["location"], headers=headers)
    # Denials and failures log too.
    await api.delete(f"{PREFIX}/contacts/{contact.json()['id']}", headers={})
    await api.get(f"{PREFIX}/properties/{uuid.uuid4()}", headers=headers)

    logged = "\n".join(f"{record.getMessage()} {vars(record)}" for record in caplog.records)
    for private in (
        "private.person@example.com",
        "+447700900321",
        "Private Person",
        "Secret note",
        "private-photo",
        str(tmp_path),
        token,
    ):
        assert private not in logged


# --- Archive and restore are consistent across resources --------------------------------

RESTORABLE = {"property", "unit", "contact"}


async def _archivable(api: AsyncClient, headers: dict[str, str]) -> dict[str, tuple[str, str]]:
    """One record of every archivable kind: (item URL, collection URL)."""
    world = await _one_of_each(api, headers)
    base = f"{PREFIX}/properties/{world['property']}"
    contact = await api.post(
        f"{PREFIX}/contacts",
        json={"kind": "person", "display_name": "Spare", "email": "spare@example.com"},
        headers=headers,
    )
    owner_contact = await api.post(
        f"{PREFIX}/contacts",
        json={"kind": "person", "display_name": "Owner", "email": "owner2@example.com"},
        headers=headers,
    )
    owner = await api.post(
        f"{base}/owners", json={"contact_id": owner_contact.json()["id"]}, headers=headers
    )
    unit = await api.post(f"{base}/units", json={"identifier": "Z"}, headers=headers)
    media = await api.get(f"{base}/media", headers=headers)
    document = await api.post(
        f"{base}/documents",
        files={"file": ("deed.pdf", b"%PDF-1.7\n%%EOF\n", "application/pdf")},
        data={"category": "title_deed", "title": "Deed"},
        headers=headers,
    )
    return {
        "contact": (f"{PREFIX}/contacts/{contact.json()['id']}", f"{PREFIX}/contacts"),
        "owner": (f"{base}/owners/{owner.json()['id']}", f"{base}/owners"),
        "unit": (f"{base}/units/{unit.json()['id']}", f"{base}/units"),
        "media": (f"{base}/media/{media.json()['items'][0]['id']}", f"{base}/media"),
        "document": (f"{base}/documents/{document.json()['id']}", f"{base}/documents"),
        # Last, so archiving it does not block changes to its children above.
        "property": (base, f"{PREFIX}/properties"),
    }


async def test_archive_and_restore_behave_the_same_everywhere(
    api: AsyncClient, session_factory: Sessions, tmp_path: Path
) -> None:
    headers = bearer(await token_for(api, await create_staff(session_factory, ["administrator"])))
    application.dependency_overrides[get_storage] = lambda: LocalStorage(tmp_path)
    records = await _archivable(api, headers)

    async def listed(collection: str, record_id: str, include_archived: bool) -> bool:
        flag = "true" if include_archived else "false"
        page = await api.get(f"{collection}?include_archived={flag}", headers=headers)
        assert page.status_code == 200, page.text
        return record_id in {item["id"] for item in page.json()["items"]}

    for kind, (item, collection) in records.items():
        record_id = item.rsplit("/", 1)[-1]
        first = await api.delete(item, headers=headers)
        again = await api.delete(item, headers=headers)

        # DELETE archives and returns the record; repeating it changes nothing.
        assert first.status_code == 200, (kind, first.text)
        assert first.json()["archived_at"] is not None, kind
        assert (
            again.status_code == 200 and again.json()["archived_at"] == first.json()["archived_at"]
        ), kind
        # Archived records leave normal lists but stay in history.
        assert not await listed(collection, record_id, False), kind
        assert await listed(collection, record_id, True), kind

        restore = await api.post(f"{item}/restore", headers=headers)
        if kind in RESTORABLE:
            assert restore.status_code == 200 and restore.json()["archived_at"] is None, kind
            assert await listed(collection, record_id, False), kind
        else:
            # Ending a link and archiving a file are final: there is no restore route.
            assert restore.status_code in {404, 405}, kind


# --- OpenAPI matches the contract -------------------------------------------------------


def test_openapi_matches_the_route_contract() -> None:
    paths = application.openapi()["paths"]
    for contract in CATALOG_ROUTES:
        operation = paths[PREFIX + contract.path][contract.method.lower()]
        assert operation["summary"] == contract.summary, contract.path
        assert str(contract.success_status) in operation["responses"], contract.path
        assert operation["security"] == [{"OAuth2PasswordBearer": []}], contract.path
        assert {"401", "403"} <= set(operation["responses"]), contract.path
        uploads = operation.get("requestBody", {}).get("content", {})
        if contract.method in {"POST", "PUT"} and contract.path.endswith(
            ("/media", "/documents", "/content")
        ):
            assert "multipart/form-data" in uploads, contract.path
