"""RBAC: the reviewed permission matrix, the policy layer, HTTP guards, and service guards."""

import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

import jwt
import pytest
from auth_support import (
    PASSWORD,
    Clock,
    assert_error,
    bearer,
    create_staff,
    execute,
    login,
    make_settings,
    override,
    token_for,
)
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.constants import RevocationReason
from app.auth.dependencies import CurrentIdentity, require_any_permission, require_permissions
from app.auth.errors import PermissionDeniedError
from app.auth.http import register_auth_exception_handlers
from app.auth.models import RefreshSession
from app.auth.permissions import ROLE_PERMISSIONS, Permission, render_matrix_markdown
from app.auth.policy import (
    Actor,
    has_any_permission,
    has_permissions,
    validate_permissions,
)
from app.auth.policy import (
    require_any_permission as policy_require_any,
)
from app.auth.policy import (
    require_permissions as policy_require,
)
from app.auth.service import AuthConfig, AuthService
from app.core.config import Settings
from app.core.errors import register_exception_handlers
from app.core.middleware import RequestIdMiddleware
from app.main import app
from app.users.constants import RoleCode
from app.users.models import Role, User

Sessions = async_sessionmaker[AsyncSession]
API_ROOT = Path(__file__).resolve().parents[1]

# The reviewed matrix, written out independently of app/auth/permissions.py. Changing a
# role's permissions means changing this table in the same reviewed commit.
EXPECTED: dict[str, set[str]] = {
    "administrator": {permission.value for permission in Permission},
    "manager": {
        "staff:read",
        "properties:read",
        "properties:manage",
        "listings:read",
        "listings:manage",
        "listings:publish",
        "contacts:read",
        "contacts:manage",
        "deals:read",
        "deals:manage",
        "rentals:read",
        "rentals:manage",
        "payments:read",
        "expenses:read",
        "maintenance:read",
        "maintenance:manage",
        "reports:operational",
        "reports:financial",
    },
    "agent": {
        "properties:read",
        "listings:read",
        "listings:manage",
        "contacts:read",
        "contacts:manage",
        "deals:read",
        "deals:manage",
    },
    "accountant": {
        "properties:read",
        "rentals:read",
        "payments:read",
        "payments:manage",
        "expenses:read",
        "expenses:manage",
        "reports:financial",
    },
}
ALL_CODES = {
    "staff:read",
    "staff:create",
    "staff:update",
    "staff:disable",
    "staff:reactivate",
    "staff:assign_roles",
    "staff:revoke_sessions",
    "audit:read",
    "properties:read",
    "properties:manage",
    "listings:read",
    "listings:manage",
    "listings:publish",
    "contacts:read",
    "contacts:manage",
    "deals:read",
    "deals:manage",
    "rentals:read",
    "rentals:manage",
    "payments:read",
    "payments:manage",
    "expenses:read",
    "expenses:manage",
    "maintenance:read",
    "maintenance:manage",
    "reports:operational",
    "reports:financial",
    "configuration:manage",
}
STAFF_ADMINISTRATION = {
    "staff:create",
    "staff:update",
    "staff:disable",
    "staff:reactivate",
    "staff:assign_roles",
    "staff:revoke_sessions",
}


def actor(*roles: str, active: bool = True) -> Actor:
    return Actor(user_id=uuid.uuid4(), role_codes=frozenset(roles), active=active)


# --- Matrix -----------------------------------------------------------------------------


def test_permission_codes_are_stable() -> None:
    assert {permission.value for permission in Permission} == ALL_CODES


@pytest.mark.parametrize("role", list(RoleCode))
@pytest.mark.parametrize("permission", list(Permission))
def test_every_role_and_permission(role: RoleCode, permission: Permission) -> None:
    granted = permission in ROLE_PERMISSIONS[role]

    assert granted == (permission.value in EXPECTED[role.value])
    assert has_permissions(actor(role), permission) == granted


def test_only_administrators_administer_staff() -> None:
    for role in RoleCode:
        administers = STAFF_ADMINISTRATION <= {p.value for p in ROLE_PERMISSIONS[role]}
        overlap = STAFF_ADMINISTRATION & {p.value for p in ROLE_PERMISSIONS[role]}
        assert administers == (role == RoleCode.ADMINISTRATOR)
        assert bool(overlap) == (role == RoleCode.ADMINISTRATOR)


def test_matrix_is_immutable() -> None:
    with pytest.raises(TypeError):
        ROLE_PERMISSIONS[RoleCode.AGENT] = frozenset(Permission)  # type: ignore[index]
    with pytest.raises(AttributeError):
        ROLE_PERMISSIONS[RoleCode.AGENT].add(Permission.STAFF_CREATE)  # type: ignore[attr-defined]


def test_readme_documents_the_current_matrix() -> None:
    assert render_matrix_markdown() in (API_ROOT / "README.md").read_text()


# --- Policy -----------------------------------------------------------------------------


def test_no_roles_grant_nothing() -> None:
    assert actor().permissions == frozenset()
    assert not has_any_permission(actor(), *Permission)


def test_unknown_roles_fail_closed() -> None:
    assert actor("owner", "superuser", "ADMINISTRATOR").permissions == frozenset()
    assert actor("owner", "agent").permissions == ROLE_PERMISSIONS[RoleCode.AGENT]


def test_disabled_actor_has_no_permissions() -> None:
    assert actor("administrator", active=False).permissions == frozenset()


def test_multiple_roles_combine() -> None:
    combined = actor("agent", "accountant")

    assert has_permissions(combined, Permission.DEALS_MANAGE, Permission.PAYMENTS_MANAGE)
    assert not has_permissions(combined, Permission.STAFF_READ)
    assert combined.permissions == (
        ROLE_PERMISSIONS[RoleCode.AGENT] | ROLE_PERMISSIONS[RoleCode.ACCOUNTANT]
    )


def test_all_versus_any() -> None:
    agent = actor("agent")

    assert not has_permissions(agent, Permission.DEALS_READ, Permission.PAYMENTS_READ)
    assert has_any_permission(agent, Permission.DEALS_READ, Permission.PAYMENTS_READ)
    with pytest.raises(PermissionDeniedError) as denied:
        policy_require(agent, Permission.DEALS_READ, Permission.PAYMENTS_READ)
    assert (denied.value.required, denied.value.mode) == (("deals:read", "payments:read"), "all")
    policy_require_any(agent, Permission.DEALS_READ, Permission.PAYMENTS_READ)


def test_requirements_must_be_explicit_permissions() -> None:
    with pytest.raises(ValueError):
        validate_permissions([])
    with pytest.raises(TypeError):
        validate_permissions(["staff:read"])  # type: ignore[list-item]
    with pytest.raises(ValueError):
        require_permissions()
    with pytest.raises(TypeError):
        require_any_permission("staff:read")  # type: ignore[arg-type]


# --- HTTP guards ------------------------------------------------------------------------


guarded = FastAPI()
guarded.add_middleware(RequestIdMiddleware)
register_exception_handlers(guarded)
register_auth_exception_handlers(guarded)

StaffReader = Annotated[CurrentIdentity, Depends(require_permissions(Permission.STAFF_READ))]
SessionRevoker = Annotated[
    CurrentIdentity, Depends(require_permissions(Permission.STAFF_REVOKE_SESSIONS))
]
AuditOrStaff = Annotated[
    CurrentIdentity,
    Depends(require_any_permission(Permission.AUDIT_READ, Permission.STAFF_UPDATE)),
]


@guarded.get("/staff")
async def list_staff(identity: StaffReader) -> dict[str, str]:
    return {"email": identity.user.email}


@guarded.post("/staff/sessions")
async def revoke_sessions(identity: SessionRevoker) -> dict[str, str]:
    return {"email": identity.user.email}


@guarded.get("/audit")
async def audit(identity: AuditOrStaff) -> dict[str, str]:
    return {"email": identity.user.email}


@pytest.fixture
async def guarded_api(
    session_factory: Sessions, settings: Settings, clock: Clock
) -> AsyncIterator[AsyncClient]:
    override(guarded, session_factory, settings, clock)
    try:
        transport = ASGITransport(app=guarded)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        guarded.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("role", "staff", "revoke", "audit_or_staff"),
    [
        ("administrator", 200, 200, 200),
        ("manager", 200, 403, 403),
        ("agent", 403, 403, 403),
        ("accountant", 403, 403, 403),
    ],
)
async def test_each_role_against_guarded_routes(
    api: AsyncClient,
    guarded_api: AsyncClient,
    session_factory: Sessions,
    role: str,
    staff: int,
    revoke: int,
    audit_or_staff: int,
) -> None:
    headers = bearer(await token_for(api, await create_staff(session_factory, [role])))

    assert (await guarded_api.get("/staff", headers=headers)).status_code == staff
    assert (await guarded_api.post("/staff/sessions", headers=headers)).status_code == revoke
    assert (await guarded_api.get("/audit", headers=headers)).status_code == audit_or_staff


async def test_unauthenticated_is_401_and_forbidden_is_403(
    api: AsyncClient, guarded_api: AsyncClient, session_factory: Sessions
) -> None:
    agent = bearer(await token_for(api, await create_staff(session_factory, ["agent"])))

    assert_error(await guarded_api.get("/staff"), 401, "authentication_required")
    assert_error(await guarded_api.get("/staff", headers=bearer("garbage")), 401, "invalid_token")
    forbidden = await guarded_api.get("/staff", headers=agent)
    assert_error(forbidden, 403, "permission_denied")
    assert "www-authenticate" not in forbidden.headers


async def test_user_without_roles_is_forbidden(
    api: AsyncClient, guarded_api: AsyncClient, session_factory: Sessions
) -> None:
    headers = bearer(await token_for(api, await create_staff(session_factory, [])))

    assert_error(await guarded_api.get("/staff", headers=headers), 403, "permission_denied")


async def test_unknown_role_in_database_grants_nothing(
    api: AsyncClient, guarded_api: AsyncClient, session_factory: Sessions
) -> None:
    async with session_factory() as db:
        db.add(Role(code="auditor", name="Auditor"))
        await db.commit()
    try:
        headers = bearer(await token_for(api, await create_staff(session_factory, ["auditor"])))

        assert_error(await guarded_api.get("/audit", headers=headers), 403, "permission_denied")
    finally:
        await execute(session_factory, "DELETE FROM user_roles")
        await execute(session_factory, "DELETE FROM roles WHERE code = 'auditor'")


async def test_multi_role_user_gets_the_union(
    api: AsyncClient, guarded_api: AsyncClient, session_factory: Sessions
) -> None:
    headers = bearer(
        await token_for(api, await create_staff(session_factory, ["agent", "manager"]))
    )

    assert (await guarded_api.get("/staff", headers=headers)).status_code == 200
    assert (await guarded_api.post("/staff/sessions", headers=headers)).status_code == 403


async def test_database_roles_are_authoritative(
    api: AsyncClient, guarded_api: AsyncClient, session_factory: Sessions
) -> None:
    admin = await create_staff(session_factory, ["administrator"])
    headers = bearer(await token_for(api, admin))
    assert (await guarded_api.get("/staff", headers=headers)).status_code == 200

    # The same access token, after the role is removed in the database.
    await execute(session_factory, "DELETE FROM user_roles WHERE user_id = :id", id=admin.id)
    assert_error(await guarded_api.get("/staff", headers=headers), 403, "permission_denied")

    # Disabling is authentication, not authorization: the token stops working.
    await execute(
        session_factory, "UPDATE users SET status = 'disabled' WHERE id = :id", id=admin.id
    )
    assert_error(await guarded_api.get("/staff", headers=headers), 401, "invalid_token")


async def test_client_supplied_roles_are_ignored(
    api: AsyncClient, guarded_api: AsyncClient, session_factory: Sessions
) -> None:
    headers = bearer(await token_for(api, await create_staff(session_factory, ["agent"])))

    response = await guarded_api.post(
        "/staff/sessions?roles=administrator",
        headers=headers | {"X-Roles": "administrator", "X-Permissions": "staff:revoke_sessions"},
        json={"roles": ["administrator"], "permissions": ["staff:revoke_sessions"]},
    )

    assert_error(response, 403, "permission_denied")


async def test_denials_are_logged_without_credentials(
    api: AsyncClient,
    guarded_api: AsyncClient,
    session_factory: Sessions,
    caplog: pytest.LogCaptureFixture,
) -> None:
    agent = await create_staff(session_factory, ["agent"])
    token = await token_for(api, agent)

    with caplog.at_level(logging.INFO, logger="app.auth.dependencies"):
        await guarded_api.post("/staff/sessions", headers=bearer(token))

    (record,) = [r for r in caplog.records if r.message == "Permission denied"]
    assert record.__dict__["user_id"] == str(agent.id)
    assert record.__dict__["required_permissions"] == ["staff:revoke_sessions"]
    assert record.__dict__["path"] == "/staff/sessions"
    assert token not in caplog.text
    assert PASSWORD not in caplog.text


def test_openapi_lists_security_on_protected_routes() -> None:
    guarded_paths = guarded.openapi()["paths"]
    for path, method in (("/staff", "get"), ("/staff/sessions", "post"), ("/audit", "get")):
        assert guarded_paths[path][method]["security"] == [{"OAuth2PasswordBearer": []}]

    app_paths = app.openapi()["paths"]
    for path, method in (
        ("/api/v1/auth/me", "get"),
        ("/api/v1/auth/me/permissions", "get"),
        ("/api/v1/auth/change-password", "post"),
    ):
        assert app_paths[path][method]["security"] == [{"OAuth2PasswordBearer": []}]
    assert "security" not in app_paths["/api/v1/auth/token"]["post"]


# --- Effective permissions endpoint -----------------------------------------------------


async def test_effective_permissions_endpoint(api: AsyncClient, session_factory: Sessions) -> None:
    user = await create_staff(session_factory, ["agent", "accountant"])
    token = await token_for(api, user)

    response = await api.get("/api/v1/auth/me/permissions", headers=bearer(token))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "roles": ["accountant", "agent"],
        "permissions": sorted(EXPECTED["agent"] | EXPECTED["accountant"]),
    }
    assert_error(
        await api.get("/api/v1/auth/me/permissions", headers=bearer("x")), 401, "invalid_token"
    )


# --- Service guard ----------------------------------------------------------------------


async def active_sessions(session_factory: Sessions, user: User) -> int:
    async with session_factory() as db:
        result = await db.scalars(
            select(RefreshSession).where(
                RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None)
            )
        )
        return len(list(result))


@pytest.mark.parametrize(
    ("actor_roles", "allowed"),
    [(["administrator"], True), (["manager"], False), (["agent"], False), ([], False)],
)
async def test_service_guards_revoking_other_users_sessions(
    api: AsyncClient,
    session_factory: Sessions,
    clock: Clock,
    actor_roles: list[str],
    allowed: bool,
) -> None:
    target = await create_staff(session_factory, ["agent"])
    await login(api, target.email)
    acting_user = await create_staff(session_factory, actor_roles)

    async with session_factory() as db:
        service = AuthService(db, AuthConfig.from_settings(make_settings()), clock=clock)
        call = service.revoke_all_sessions(
            Actor.from_user(acting_user), target.id, RevocationReason.ADMIN_REVOKED
        )
        if allowed:
            assert await call == 1
        else:
            with pytest.raises(PermissionDeniedError):
                await call

    assert await active_sessions(session_factory, target) == (0 if allowed else 1)


async def test_anyone_may_revoke_their_own_sessions_unless_disabled(
    api: AsyncClient, session_factory: Sessions, clock: Clock
) -> None:
    user = await create_staff(session_factory, [])
    await login(api, user.email)
    config = AuthConfig.from_settings(make_settings())

    async with session_factory() as db:
        service = AuthService(db, config, clock=clock)
        disabled_self = Actor(user_id=user.id, role_codes=frozenset(), active=False)
        with pytest.raises(PermissionDeniedError):
            await service.revoke_all_sessions(disabled_self, user.id, RevocationReason.LOGOUT)
        assert (
            await service.revoke_all_sessions(
                Actor.from_user(user), user.id, RevocationReason.LOGOUT
            )
            == 1
        )


async def test_access_token_carries_no_role_claims(
    api: AsyncClient, session_factory: Sessions
) -> None:
    token = await token_for(api, await create_staff(session_factory, ["administrator"]))

    claims = jwt.decode(token, options={"verify_signature": False})
    assert not {"roles", "role", "permissions", "scope", "scopes"} & set(claims)
