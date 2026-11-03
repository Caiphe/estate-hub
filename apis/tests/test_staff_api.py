"""Staff management API: permissions, business rules, audit events, and listing."""

import asyncio
import uuid
from typing import Any

import pytest
from auth_support import (
    CSRF,
    FAST,
    PASSWORD,
    REFRESH,
    Clock,
    assert_error,
    bearer,
    create_staff,
    csrf_header,
    execute,
    login,
    set_cookies,
    token_for,
    with_cookies,
)
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditEvent
from app.auth.policy import Actor
from app.main import app
from app.users.constants import RoleCode, UserStatus
from app.users.errors import LastAdministratorError
from app.users.models import User
from app.users.schemas import StaffListQuery
from app.users.service import StaffService

Sessions = async_sessionmaker[AsyncSession]
STAFF = "/api/v1/staff"
NEW_PASSWORD = "initial passphrase for staff"


@pytest.fixture
async def admin(session_factory: Sessions) -> User:
    return await create_staff(session_factory, ["administrator"])


@pytest.fixture
async def admin_headers(api: AsyncClient, admin: User) -> dict[str, str]:
    return bearer(await token_for(api, admin))


async def audit_events(session_factory: Sessions) -> list[AuditEvent]:
    """Staff-administration events only; sign-ins in these tests write auth.* events."""
    async with session_factory() as db:
        return list(
            await db.scalars(
                select(AuditEvent)
                .where(AuditEvent.event_code.startswith("staff."))
                .order_by(AuditEvent.occurred_at)
            )
        )


async def only_event(session_factory: Sessions, code: str) -> AuditEvent:
    events = await audit_events(session_factory)
    assert [event.event_code for event in events] == [code]
    return events[0]


def new_staff(**overrides: Any) -> dict[str, Any]:
    return {
        "email": f"new-{uuid.uuid4().hex[:8]}@estatehub.example",
        "full_name": "New Staff",
        "password": NEW_PASSWORD,
        "roles": ["agent"],
    } | overrides


def assert_no_secrets(response: Response) -> None:
    for secret in (
        "password_hash",
        "argon2",
        "token_version",
        "token_hash",
        NEW_PASSWORD,
        PASSWORD,
    ):
        assert secret not in response.text


# --- Permissions --------------------------------------------------------------------------

READS = {"administrator", "manager"}
WRITES = {"administrator"}
ENDPOINTS: list[tuple[str, str, Any, int, set[str]]] = [
    ("GET", STAFF, None, 200, READS),
    ("GET", STAFF + "/{id}", None, 200, READS),
    ("POST", STAFF, "create", 201, WRITES),
    ("PATCH", STAFF + "/{id}", {"full_name": "Renamed"}, 200, WRITES),
    ("PUT", STAFF + "/{id}/roles", {"roles": ["accountant"]}, 200, WRITES),
    ("POST", STAFF + "/{id}/disable", None, 200, WRITES),
    ("POST", STAFF + "/{id}/reactivate", None, 200, WRITES),
    ("POST", STAFF + "/{id}/revoke-sessions", None, 204, WRITES),
]


@pytest.mark.parametrize("role", [role.value for role in RoleCode])
@pytest.mark.parametrize(("method", "path", "payload", "success", "allowed"), ENDPOINTS)
async def test_every_endpoint_for_every_role(
    api: AsyncClient,
    session_factory: Sessions,
    role: str,
    method: str,
    path: str,
    payload: Any,
    success: int,
    allowed: set[str],
) -> None:
    caller = await create_staff(session_factory, [role])
    target = await create_staff(session_factory, ["agent"])
    body = new_staff() if payload == "create" else payload

    response = await api.request(
        method,
        path.format(id=target.id),
        json=body,
        headers=bearer(await token_for(api, caller)),
    )

    if role in allowed:
        assert response.status_code == success, response.text
    else:
        assert_error(response, 403, "permission_denied")
        assert await audit_events(session_factory) == []


@pytest.mark.parametrize(("method", "path", "payload", "success", "allowed"), ENDPOINTS)
async def test_every_endpoint_requires_authentication(
    api: AsyncClient, method: str, path: str, payload: Any, success: int, allowed: set[str]
) -> None:
    body = new_staff() if payload == "create" else payload

    response = await api.request(method, path.format(id=uuid.uuid4()), json=body)

    assert_error(response, 401, "authentication_required")


async def test_cookie_authenticated_mutations_require_csrf(
    api: AsyncClient, session_factory: Sessions, admin: User
) -> None:
    await login(api, admin.email)

    assert_error(await api.post(STAFF, json=new_staff()), 403, "csrf_failed")
    created = await api.post(STAFF, json=new_staff(), headers=csrf_header(api))
    assert created.status_code == 201


def test_openapi_documents_security_and_errors() -> None:
    paths = app.openapi()["paths"]
    for method, path, *_ in ENDPOINTS:
        operation = paths[path.replace("{id}", "{user_id}")][method.lower()]
        assert operation["security"] == [{"OAuth2PasswordBearer": []}]
        assert {"401", "403", "422"} <= set(operation["responses"])
    assert "409" in paths[STAFF]["post"]["responses"]
    assert "409" in paths[STAFF + "/{user_id}/disable"]["post"]["responses"]


# --- Create -------------------------------------------------------------------------------


async def test_create_staff(
    api: AsyncClient, session_factory: Sessions, admin: User, admin_headers: dict[str, str]
) -> None:
    payload = new_staff(email="  New.Agent@EstateHub.Example ", roles=["manager", "agent"])

    response = await api.post(STAFF, json=payload, headers=admin_headers)

    assert response.status_code == 201
    created = response.json()
    assert created["email"] == "new.agent@estatehub.example"
    assert created["roles"] == ["agent", "manager"]
    assert created["status"] == "active"
    assert response.headers["location"].endswith(f"{STAFF}/{created['id']}")
    assert_no_secrets(response)

    event = await only_event(session_factory, "staff.created")
    assert (event.actor_id, str(event.entity_id)) == (admin.id, created["id"])
    assert event.request_id == response.headers["x-request-id"]
    assert event.details == {"roles": ["agent", "manager"]}
    assert (await login(api, created["email"], NEW_PASSWORD)).status_code == 200


async def test_duplicate_normalized_email_conflicts(
    api: AsyncClient, session_factory: Sessions, admin: User, admin_headers: dict[str, str]
) -> None:
    response = await api.post(
        STAFF, json=new_staff(email=f"  {admin.email.upper()} "), headers=admin_headers
    )

    assert_error_fields(response, 409, "email_already_exists", ["email"])
    assert await audit_events(session_factory) == []


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"roles": ["owner"]}, "roles.0"),
        ({"roles": []}, "roles"),
        ({"roles": None}, "roles"),
        ({"password": "p" * 11}, "password"),
        ({"password": "p" * 129}, "password"),
        ({"status": "disabled"}, "status"),
    ],
)
async def test_create_validation(
    api: AsyncClient,
    session_factory: Sessions,
    admin_headers: dict[str, str],
    overrides: dict[str, Any],
    field: str,
) -> None:
    payload = new_staff(**overrides)
    if overrides.get("roles", "") is None:
        del payload["roles"]

    response = await api.post(STAFF, json=payload, headers=admin_headers)

    assert_error_fields(response, 422, "validation_error", [field])
    assert_no_secrets(response)
    assert str(payload.get("password")) not in response.text
    assert await audit_events(session_factory) == []


@pytest.mark.parametrize("password", ["p" * 12, "é" * 128])
async def test_create_accepts_password_boundaries(
    api: AsyncClient, admin_headers: dict[str, str], password: str
) -> None:
    response = await api.post(STAFF, json=new_staff(password=password), headers=admin_headers)

    assert response.status_code == 201
    assert (await login(api, response.json()["email"], password)).status_code == 200


def assert_error_fields(response: Response, status: int, code: str, fields: list[str]) -> None:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    assert sorted(error["fields"]) == sorted(fields)


# --- Read ---------------------------------------------------------------------------------


async def test_get_staff(
    api: AsyncClient, session_factory: Sessions, admin_headers: dict[str, str]
) -> None:
    target = await create_staff(session_factory, ["accountant"])

    found = await api.get(f"{STAFF}/{target.id}", headers=admin_headers)

    assert found.json()["roles"] == ["accountant"]
    assert_no_secrets(found)
    assert_error(await api.get(f"{STAFF}/{uuid.uuid4()}", headers=admin_headers), 404, "not_found")
    malformed = await api.get(f"{STAFF}/not-a-uuid", headers=admin_headers)
    assert_error_fields(malformed, 422, "validation_error", ["user_id"])


# --- Update profile -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "disabled"},
        {"roles": ["administrator"]},
        {"password": NEW_PASSWORD},
        {"token_version": 0},
        {"full_name": "Ok", "nickname": "x"},
        {},
    ],
)
async def test_patch_rejects_everything_but_name_and_email(
    api: AsyncClient,
    session_factory: Sessions,
    admin_headers: dict[str, str],
    payload: dict[str, Any],
) -> None:
    target = await create_staff(session_factory, ["agent"])

    response = await api.patch(f"{STAFF}/{target.id}", json=payload, headers=admin_headers)

    assert response.status_code == 422
    assert await audit_events(session_factory) == []
    assert (await api.get(f"{STAFF}/{target.id}", headers=admin_headers)).json()["roles"] == [
        "agent"
    ]


async def test_patch_updates_profile(
    api: AsyncClient, session_factory: Sessions, admin: User, admin_headers: dict[str, str]
) -> None:
    target = await create_staff(session_factory, ["agent"])

    response = await api.patch(
        f"{STAFF}/{target.id}",
        json={"email": " Renamed@EstateHub.Example", "full_name": " Renamed Person "},
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert (response.json()["email"], response.json()["full_name"]) == (
        "renamed@estatehub.example",
        "Renamed Person",
    )
    event = await only_event(session_factory, "staff.profile_updated")
    assert event.details == {"changed_fields": ["email", "full_name"]}
    assert event.actor_id == admin.id

    unchanged = await api.patch(
        f"{STAFF}/{target.id}", json={"full_name": "Renamed Person"}, headers=admin_headers
    )
    assert unchanged.status_code == 200
    assert len(await audit_events(session_factory)) == 1


async def test_patch_email_conflict(
    api: AsyncClient, session_factory: Sessions, admin: User, admin_headers: dict[str, str]
) -> None:
    target = await create_staff(session_factory, ["agent"])

    response = await api.patch(
        f"{STAFF}/{target.id}", json={"email": admin.email.upper()}, headers=admin_headers
    )

    assert_error_fields(response, 409, "email_already_exists", ["email"])
    assert await audit_events(session_factory) == []


# --- Roles --------------------------------------------------------------------------------


async def test_role_replacement_applies_immediately(
    api: AsyncClient, session_factory: Sessions, admin: User, admin_headers: dict[str, str]
) -> None:
    target = await create_staff(session_factory, ["agent"])
    target_token = await token_for(api, target)
    assert_error(await api.get(STAFF, headers=bearer(target_token)), 403, "permission_denied")

    response = await api.put(
        f"{STAFF}/{target.id}/roles", json={"roles": ["manager"]}, headers=admin_headers
    )

    assert response.json()["roles"] == ["manager"]
    event = await only_event(session_factory, "staff.roles_changed")
    assert event.details == {"before": ["agent"], "after": ["manager"]}
    # The old access token is rejected; a fresh sign-in carries the new permissions.
    assert_error(await api.get(STAFF, headers=bearer(target_token)), 401, "invalid_token")
    assert (await api.get(STAFF, headers=bearer(await token_for(api, target)))).status_code == 200

    unchanged = await api.put(
        f"{STAFF}/{target.id}/roles", json={"roles": ["manager"]}, headers=admin_headers
    )
    assert unchanged.status_code == 200
    assert len(await audit_events(session_factory)) == 1


@pytest.mark.parametrize("roles", [[], ["owner"], ["Administrator"]])
async def test_role_replacement_validation(
    api: AsyncClient, session_factory: Sessions, admin_headers: dict[str, str], roles: list[str]
) -> None:
    target = await create_staff(session_factory, ["agent"])

    response = await api.put(
        f"{STAFF}/{target.id}/roles", json={"roles": roles}, headers=admin_headers
    )

    assert response.status_code == 422
    assert await audit_events(session_factory) == []


# --- Disable, reactivate, revoke --------------------------------------------------------


async def test_disable_and_reactivate(
    api: AsyncClient, session_factory: Sessions, admin_headers: dict[str, str]
) -> None:
    target = await create_staff(session_factory, ["agent"])
    login_response = await login(api, target.email)
    access = login_response.json()["access_token"]
    old_refresh = str(set_cookies(login_response)[REFRESH]["value"])
    csrf = api.cookies[CSRF]

    disabled = await api.post(f"{STAFF}/{target.id}/disable", headers=admin_headers)

    assert disabled.json()["status"] == "disabled"
    event = await only_event(session_factory, "staff.disabled")
    assert event.details == {"revoked_sessions": 1}
    assert_error(await api.get("/api/v1/auth/me", headers=bearer(access)), 401, "invalid_token")
    refresh = await api.post(
        "/api/v1/auth/refresh",
        headers=with_cookies(api, {"X-CSRF-Token": csrf}, {REFRESH: old_refresh, CSRF: csrf}),
    )
    assert_error(refresh, 401, "invalid_session")
    assert_error(await login(api, target.email), 401, "invalid_credentials")

    again = await api.post(f"{STAFF}/{target.id}/disable", headers=admin_headers)
    assert again.json()["status"] == "disabled"
    assert len(await audit_events(session_factory)) == 1

    reactivated = await api.post(f"{STAFF}/{target.id}/reactivate", headers=admin_headers)
    assert reactivated.json()["status"] == "active"
    assert [e.event_code for e in await audit_events(session_factory)] == [
        "staff.disabled",
        "staff.reactivated",
    ]
    stale = await api.post(
        "/api/v1/auth/refresh",
        headers=with_cookies(api, {"X-CSRF-Token": csrf}, {REFRESH: old_refresh, CSRF: csrf}),
    )
    assert_error(stale, 401, "invalid_session")
    assert (await login(api, target.email)).status_code == 200

    await api.post(f"{STAFF}/{target.id}/reactivate", headers=admin_headers)
    assert len(await audit_events(session_factory)) == 2


async def test_revoke_sessions(
    api: AsyncClient, session_factory: Sessions, admin_headers: dict[str, str]
) -> None:
    target = await create_staff(session_factory, ["agent"])
    access = await token_for(api, target)
    await login(api, target.email)

    response = await api.post(f"{STAFF}/{target.id}/revoke-sessions", headers=admin_headers)

    assert response.status_code == 204
    event = await only_event(session_factory, "staff.sessions_revoked")
    assert event.details == {"revoked_sessions": 2}
    assert_error(await api.get("/api/v1/auth/me", headers=bearer(access)), 401, "invalid_token")
    detail = await api.get(f"{STAFF}/{target.id}", headers=admin_headers)
    assert detail.json()["status"] == "active"
    assert (await login(api, target.email)).status_code == 200


# --- Administrator safeguards -------------------------------------------------------------


async def test_administrators_cannot_lock_themselves_out(
    api: AsyncClient, session_factory: Sessions, admin: User, admin_headers: dict[str, str]
) -> None:
    disable_self = await api.post(f"{STAFF}/{admin.id}/disable", headers=admin_headers)
    demote_self = await api.put(
        f"{STAFF}/{admin.id}/roles", json={"roles": ["manager"]}, headers=admin_headers
    )

    assert_error(disable_self, 409, "self_lockout")
    assert_error(demote_self, 409, "self_lockout")
    assert await audit_events(session_factory) == []

    keep_admin = await api.put(
        f"{STAFF}/{admin.id}/roles",
        json={"roles": ["administrator", "manager"]},
        headers=admin_headers,
    )
    assert keep_admin.json()["roles"] == ["administrator", "manager"]


async def test_other_administrators_can_be_demoted_and_disabled(
    api: AsyncClient, session_factory: Sessions, admin_headers: dict[str, str]
) -> None:
    other = await create_staff(session_factory, ["administrator"])

    demoted = await api.put(
        f"{STAFF}/{other.id}/roles", json={"roles": ["manager"]}, headers=admin_headers
    )
    disabled = await api.post(f"{STAFF}/{other.id}/disable", headers=admin_headers)

    assert demoted.status_code == disabled.status_code == 200


def service_for(db: AsyncSession, clock: Clock) -> StaffService:
    return StaffService(db, clock=clock, password_hasher=FAST)


async def test_last_active_administrator_is_protected(
    session_factory: Sessions, clock: Clock, admin: User
) -> None:
    # A caller that is not itself an administrator in the database (for example a
    # future system job) must still be unable to remove the last one.
    system = Actor(user_id=uuid.uuid4(), role_codes=frozenset({"administrator"}), active=True)

    async with session_factory() as db:
        with pytest.raises(LastAdministratorError):
            await service_for(db, clock).disable(system, admin.id)
        with pytest.raises(LastAdministratorError):
            await service_for(db, clock).replace_roles(system, admin.id, [RoleCode.MANAGER])

    assert await audit_events(session_factory) == []


@pytest.mark.parametrize("operation", ["disable", "demote"])
async def test_concurrent_requests_cannot_remove_both_administrators(
    session_factory: Sessions, clock: Clock, admin: User, operation: str
) -> None:
    other = await create_staff(session_factory, ["administrator"])
    first, second = Actor.from_user(admin), Actor.from_user(other)

    async def act(actor: Actor, target: User) -> object:
        async with session_factory() as db:
            service = service_for(db, clock)
            try:
                if operation == "disable":
                    return await service.disable(actor, target.id)
                return await service.replace_roles(actor, target.id, [RoleCode.MANAGER])
            except LastAdministratorError as exc:
                return exc

    results = await asyncio.gather(act(first, other), act(second, admin))

    assert sum(isinstance(result, LastAdministratorError) for result in results) == 1
    async with session_factory() as db:
        service = service_for(db, clock)
        system = Actor(user_id=uuid.uuid4(), role_codes=frozenset({"administrator"}), active=True)
        remaining = await service.list_staff(
            system, StaffListQuery(role=RoleCode.ADMINISTRATOR, status=UserStatus.ACTIVE)
        )
    assert remaining[1] == 1
    assert len(await audit_events(session_factory)) == 1


# --- Listing ------------------------------------------------------------------------------


async def test_pagination_is_stable_and_complete(
    api: AsyncClient, session_factory: Sessions, admin: User, admin_headers: dict[str, str]
) -> None:
    for index in range(12):
        member = await create_staff(session_factory, ["agent"])
        # Every third name repeats, so the ID tie-breaker decides their order.
        name = "Same Name" if index % 3 == 0 else f"Person {index:02d}"
        await execute(
            session_factory,
            "UPDATE users SET full_name = :name WHERE id = :id",
            name=name,
            id=member.id,
        )
    async with session_factory() as db:
        expected = [
            str(user_id)
            for user_id in await db.scalars(select(User.id).order_by(User.full_name, User.id))
        ]

    seen: list[str] = []
    offset = 0
    while True:
        page = (
            await api.get(STAFF, params={"limit": 5, "offset": offset}, headers=admin_headers)
        ).json()
        assert page["limit"] == 5
        assert page["total"] == len(expected)
        seen += [item["id"] for item in page["items"]]
        offset += 5
        if offset >= page["total"]:
            break

    assert seen == expected


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"sort": "password"}, {"unknown": "x"}],
)
async def test_list_rejects_invalid_parameters(
    api: AsyncClient, admin_headers: dict[str, str], params: dict[str, Any]
) -> None:
    response = await api.get(STAFF, params=params, headers=admin_headers)

    assert response.status_code == 422


async def test_list_filters_and_sorting(
    api: AsyncClient, session_factory: Sessions, admin: User, admin_headers: dict[str, str]
) -> None:
    accountant = await create_staff(session_factory, ["accountant"])
    disabled = await create_staff(session_factory, ["agent"])
    percent = await create_staff(session_factory, ["agent"])
    await execute(
        session_factory, "UPDATE users SET status = 'disabled' WHERE id = :id", id=disabled.id
    )
    await execute(
        session_factory, "UPDATE users SET full_name = '100% Closer' WHERE id = :id", id=percent.id
    )

    async def ids(**params: Any) -> list[str]:
        response = await api.get(STAFF, params=params, headers=admin_headers)
        assert response.status_code == 200, response.text
        return [item["id"] for item in response.json()["items"]]

    assert await ids(status="disabled") == [str(disabled.id)]
    assert await ids(role="accountant") == [str(accountant.id)]
    assert await ids(q="ACCOUNTANT-") == [str(accountant.id)]
    assert await ids(q="100%") == [str(percent.id)]
    assert await ids(q="%") == [str(percent.id)]
    assert await ids(q="closer") == [str(percent.id)]
    assert await ids(role="agent", status="active") == [str(percent.id)]

    by_email = await ids(sort="email")
    assert await ids(sort="-email") == list(reversed(by_email))
