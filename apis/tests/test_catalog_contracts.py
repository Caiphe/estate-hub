"""Property-catalog contracts: error codes, the route inventory, and its permission map."""

import re
from pathlib import Path
from typing import cast

import pytest
from fastapi import status
from route_support import iter_api_routes

from app.auth.constants import AUTH_ERRORS, AuthErrorCode
from app.auth.permissions import ROLE_PERMISSIONS, Permission
from app.catalog.contracts import (
    ACTION_SEGMENTS,
    CATALOG_PERMISSIONS,
    CATALOG_ROUTES,
    FIELD_LEVEL_PERMISSIONS,
    ID_PARAMETERS,
    UNCOUNTABLE_COLLECTIONS,
    Method,
    RouteContract,
    render_routes_markdown,
)
from app.catalog.errors import (
    CATALOG_ERRORS,
    CatalogError,
    CatalogErrorCode,
)
from app.core.config import get_settings
from app.main import app
from app.users.constants import RoleCode

API_ROOT = Path(__file__).resolve().parents[1]
_SEGMENT = re.compile(r"^[a-z]+(-[a-z]+)*$")
_PARAMETER = re.compile(r"^\{([a-z_]+)\}$")


def _segments(route: RouteContract) -> list[str]:
    return route.path.strip("/").split("/")


def _routes_allowed(role: RoleCode) -> set[tuple[str, str]]:
    granted = ROLE_PERMISSIONS[role]
    return {(r.method, r.path) for r in CATALOG_ROUTES if r.permission in granted}


# --- Error codes ------------------------------------------------------------------------


def test_every_catalog_error_code_has_a_public_contract() -> None:
    assert set(CATALOG_ERRORS) == set(CatalogErrorCode)
    assert len({code.value for code in CatalogErrorCode}) == len(CatalogErrorCode)


def test_catalog_error_codes_are_client_errors() -> None:
    for spec in CATALOG_ERRORS.values():
        assert 400 <= spec.status_code < 500
        assert spec.message.endswith(".")
        assert "{" not in spec.message


def test_permission_denial_shares_the_authentication_contract() -> None:
    shared = AuthErrorCode.PERMISSION_DENIED
    assert CatalogErrorCode.PERMISSION_DENIED.value == shared.value
    assert CATALOG_ERRORS[CatalogErrorCode.PERMISSION_DENIED].status_code == (
        AUTH_ERRORS[shared].status_code
    )
    # No other catalog code reuses an authentication code with a different meaning.
    others = {code.value for code in CatalogErrorCode} - {shared.value}
    assert not others & {code.value for code in AuthErrorCode}


def test_each_raisable_code_has_one_exception_class() -> None:
    raisable = {cls.code for cls in CatalogError.__subclasses__()}

    # Denials are raised as app.auth.errors.PermissionDeniedError, like every other route.
    assert raisable == set(CatalogErrorCode) - {CatalogErrorCode.PERMISSION_DENIED}
    assert len(CatalogError.__subclasses__()) == len(raisable)


@pytest.mark.parametrize("error_class", CatalogError.__subclasses__())
def test_catalog_errors_carry_their_public_status(error_class: type[CatalogError]) -> None:
    error = error_class(fields={"subtype_id": ["Choose a subtype of the selected type."]})

    assert str(error) == error.code.value
    assert error.status_code == CATALOG_ERRORS[error.code].status_code
    assert error.message == CATALOG_ERRORS[error.code].message
    assert error.fields == {"subtype_id": ["Choose a subtype of the selected type."]}


def test_relationship_and_upload_errors_are_validation_failures() -> None:
    for code in (CatalogErrorCode.INVALID_RELATIONSHIP, CatalogErrorCode.INVALID_UPLOAD):
        assert CATALOG_ERRORS[code].status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    for code in (
        CatalogErrorCode.DUPLICATE_REFERENCE,
        CatalogErrorCode.ARCHIVED_RECORD,
        CatalogErrorCode.CONFLICT,
        CatalogErrorCode.DEPENDENCY_CONFLICT,
        CatalogErrorCode.STALE_VERSION,
    ):
        assert CATALOG_ERRORS[code].status_code == status.HTTP_409_CONFLICT


# --- Route naming -----------------------------------------------------------------------


def test_routes_are_unique() -> None:
    keys = [(r.method, r.path) for r in CATALOG_ROUTES]
    assert len(keys) == len(set(keys))
    assert len({r.summary for r in CATALOG_ROUTES}) == len(CATALOG_ROUTES)


@pytest.mark.parametrize("route", CATALOG_ROUTES, ids=lambda r: f"{r.method} {r.path}")
def test_route_paths_follow_rest_conventions(route: RouteContract) -> None:
    segments = _segments(route)
    assert route.path.startswith("/") and not route.path.endswith("/")

    previous: str | None = None
    for segment in segments:
        parameter = _PARAMETER.match(segment)
        if parameter:
            # An ID always follows its own collection and is named after it.
            assert previous in ID_PARAMETERS, route.path
            assert parameter.group(1) == ID_PARAMETERS[previous], route.path
        else:
            assert _SEGMENT.match(segment), route.path
            if segment not in ACTION_SEGMENTS:
                assert segment.endswith("s") or segment in UNCOUNTABLE_COLLECTIONS, route.path
                assert segment in ID_PARAMETERS, route.path
        previous = segment


@pytest.mark.parametrize("route", CATALOG_ROUTES, ids=lambda r: f"{r.method} {r.path}")
def test_route_statuses_follow_the_method(route: RouteContract) -> None:
    last = _segments(route)[-1]
    is_item = bool(_PARAMETER.match(last))

    if route.method == "POST" and last not in ACTION_SEGMENTS:
        assert route.success_status == status.HTTP_201_CREATED
        assert not is_item
    else:
        assert route.success_status == status.HTTP_200_OK
    if route.method in {"PATCH", "DELETE"}:
        assert is_item, "PATCH and DELETE address one record"
    if route.method == "PUT":
        assert last in {"order", "content"}


@pytest.mark.parametrize("route", CATALOG_ROUTES, ids=lambda r: f"{r.method} {r.path}")
def test_reads_need_read_permissions_and_writes_do_not(route: RouteContract) -> None:
    is_read_permission = route.permission.value.endswith(":read")
    assert is_read_permission == (route.method == "GET")


def test_delete_archives_and_restore_is_explicit() -> None:
    deletes = {r.path for r in CATALOG_ROUTES if r.method == "DELETE"}
    restores = {r.path.removesuffix("/restore") for r in CATALOG_ROUTES if "restore" in r.path}

    # Restorable resources: properties, units, and contacts. Everything restorable is
    # archived through DELETE, and nothing else is ever removed except through archival.
    assert restores == {
        "/properties/{property_id}",
        "/properties/{property_id}/units/{unit_id}",
        "/contacts/{contact_id}",
    }
    assert restores <= deletes
    assert all(r.method == "POST" for r in CATALOG_ROUTES if r.path.endswith("/restore"))
    for route in CATALOG_ROUTES:
        if route.path in restores and route.method == "DELETE":
            restore = next(r for r in CATALOG_ROUTES if r.path == f"{route.path}/restore")
            assert restore.permission == route.permission


def test_reference_data_is_disabled_not_deleted() -> None:
    reference = [r for r in CATALOG_ROUTES if r.path.startswith(("/property-types", "/amenities"))]

    assert reference
    assert not [r for r in reference if r.method == "DELETE"]
    assert {r.path.rsplit("/", 1)[-1] for r in reference} >= {"disable", "reactivate", "order"}
    writes = {r.permission for r in reference if r.method != "GET"}
    assert writes == {Permission.REFERENCE_DATA_MANAGE}


def test_property_crud_routes_match_the_milestone() -> None:
    expected = {
        ("GET", "/properties"),
        ("POST", "/properties"),
        ("GET", "/properties/{property_id}"),
        ("PATCH", "/properties/{property_id}"),
        ("DELETE", "/properties/{property_id}"),
        ("POST", "/properties/{property_id}/restore"),
    }

    assert expected <= {(r.method, r.path) for r in CATALOG_ROUTES}


def test_registered_catalog_routes_match_the_inventory() -> None:
    """Every registered catalog route is in the inventory with the same status, and every
    inventory route is registered. (This test once walked ``app.routes`` directly and,
    under FastAPI 0.162, silently checked nothing; ``iter_api_routes`` fails instead.)"""
    prefix = get_settings().api_v1_prefix
    roots = tuple(
        f"{prefix}/{root}" for root in ("property-types", "amenities", "contacts", "properties")
    )
    contracts = {(r.method, prefix + r.path): r for r in CATALOG_ROUTES}
    registered: set[tuple[str, str]] = set()

    for path, route in iter_api_routes(app):
        if not path.startswith(roots):
            continue
        for method in (route.methods or set()) - {"HEAD", "OPTIONS"}:
            contract = contracts.get((cast(Method, method), path))
            assert contract is not None, f"{method} {path} is not in the inventory"
            # FastAPI leaves status_code unset for its default 200.
            assert (route.status_code or 200) == contract.success_status, f"{method} {path}"
            registered.add((method, path))

    assert registered == set(contracts), sorted(set(contracts) - registered)


# --- Permission map ---------------------------------------------------------------------


def test_every_catalog_permission_is_used() -> None:
    route_permissions = {r.permission for r in CATALOG_ROUTES}

    assert route_permissions | set(FIELD_LEVEL_PERMISSIONS) == CATALOG_PERMISSIONS
    assert {r.permission for r in CATALOG_ROUTES} <= CATALOG_PERMISSIONS
    # Internal notes never guard a whole route.
    assert Permission.PROPERTIES_READ_INTERNAL not in route_permissions


def test_catalog_permissions_are_the_catalog_namespace() -> None:
    namespaces = ("properties:", "property_", "contacts:", "reference_data:")
    in_namespace = {p for p in Permission if p.value.startswith(namespaces)}

    assert in_namespace == CATALOG_PERMISSIONS


def test_administrators_can_call_every_catalog_route() -> None:
    assert _routes_allowed(RoleCode.ADMINISTRATOR) == {(r.method, r.path) for r in CATALOG_ROUTES}


def test_managers_can_call_everything_but_reference_data_administration() -> None:
    denied = {(r.method, r.path) for r in CATALOG_ROUTES} - _routes_allowed(RoleCode.MANAGER)

    assert denied
    assert {r.permission for r in CATALOG_ROUTES if (r.method, r.path) in denied} == {
        Permission.REFERENCE_DATA_MANAGE
    }


def test_agents_read_the_catalog_and_manage_only_contacts() -> None:
    allowed = [r for r in CATALOG_ROUTES if (r.method, r.path) in _routes_allowed(RoleCode.AGENT)]
    writes = {r.permission for r in allowed if r.method != "GET"}

    assert writes == {Permission.CONTACTS_MANAGE}
    assert ("GET", "/properties/{property_id}/owners") in {(r.method, r.path) for r in allowed}
    assert not [r for r in allowed if "/documents" in r.path]


def test_accountants_only_read_property_context() -> None:
    allowed = [
        r for r in CATALOG_ROUTES if (r.method, r.path) in _routes_allowed(RoleCode.ACCOUNTANT)
    ]

    assert allowed
    assert {r.method for r in allowed} == {"GET"}
    assert {r.permission for r in allowed} == {Permission.PROPERTIES_READ}
    assert not [r for r in allowed if "/documents" in r.path or "/owners" in r.path]
    assert not [r for r in allowed if r.path.startswith("/contacts")]


def test_readme_documents_the_current_route_inventory() -> None:
    assert render_routes_markdown() in (API_ROOT / "README.md").read_text()
