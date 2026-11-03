"""Rate limits, client IP resolution, security audit events, and the audit-events API."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from auth_support import (
    CSRF,
    EMAIL,
    PASSWORD,
    REFRESH,
    Clock,
    assert_error,
    bearer,
    cookie_header,
    create_staff,
    csrf_header,
    login,
    make_settings,
    override,
    set_cookies,
    token_for,
    with_cookies,
)
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient, Response
from pydantic import IPvAnyNetwork, TypeAdapter
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from app.api.v1.routes.auth import router as auth_router
from app.audit.events import AuditEventCode
from app.audit.models import AuditEvent
from app.core.client_ip import client_ip
from app.main import app
from app.users.models import User

Sessions = async_sessionmaker[AsyncSession]
ApiFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]
NETWORKS = TypeAdapter(list[IPvAnyNetwork])


@pytest.fixture
def make_api(session_factory: Sessions, clock: Clock, test_redis: Redis) -> ApiFactory:
    """A client for the real app with specific settings, such as low limits."""

    @asynccontextmanager
    async def build(redis: Redis | None = None, **settings: Any) -> AsyncIterator[AsyncClient]:
        override(app, session_factory, make_settings(**settings), clock, redis or test_redis)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
        finally:
            app.dependency_overrides.clear()

    return build


async def events(session_factory: Sessions, code: str | None = None) -> list[AuditEvent]:
    async with session_factory() as db:
        statement = select(AuditEvent).order_by(AuditEvent.occurred_at, AuditEvent.id)
        if code:
            statement = statement.where(AuditEvent.event_code == code)
        return list(await db.scalars(statement))


def comparable(response: Response) -> tuple[int, dict[str, Any], str | None]:
    error = dict(response.json()["error"])
    error.pop("request_id")
    return response.status_code, error, response.headers.get("retry-after")


# --- Login limits -----------------------------------------------------------------------


async def test_login_is_limited_per_ip(make_api: ApiFactory, user: User) -> None:
    async with make_api(auth_login_max_attempts_per_ip=3) as api:
        for index in range(3):
            response = await login(api, f"user{index}@estatehub.example", "wrong password!")
            assert response.status_code == 401
        limited = await login(api, "another@estatehub.example", "wrong password!")
        correct = await login(api)

    assert_error(limited, 429, "auth_rate_limited")
    assert 0 < int(limited.headers["retry-after"]) <= 900
    # A correct password does not bypass the limit.
    assert_error(correct, 429, "auth_rate_limited")


async def test_login_is_limited_per_email(make_api: ApiFactory, user: User) -> None:
    async with make_api(auth_login_max_attempts_per_email=2) as api:
        first = await login(api, password="wrong password!")
        second = await login(api, password="wrong password!")
        limited = await login(api)
        other = await login(api, "other@estatehub.example", "wrong password!")
        normalized = await login(api, f"  {EMAIL.upper()} ")

    assert first.status_code == second.status_code == 401
    assert_error(limited, 429, "auth_rate_limited")
    assert other.status_code == 401
    assert_error(normalized, 429, "auth_rate_limited")


async def test_known_and_unknown_emails_are_limited_identically(
    make_api: ApiFactory, user: User
) -> None:
    async with make_api(auth_login_max_attempts_per_email=1) as api:
        known = [await login(api, password="wrong password!") for _ in range(2)]
        unknown = [
            await login(api, "nobody@estatehub.example", "wrong password!") for _ in range(2)
        ]

    assert comparable(known[0]) == comparable(unknown[0])
    assert comparable(known[1]) == comparable(unknown[1])
    assert known[1].status_code == 429


async def test_limit_resets_after_the_window(make_api: ApiFactory, user: User) -> None:
    async with make_api(auth_login_max_attempts_per_email=1, auth_login_window_seconds=1) as api:
        assert (await login(api)).status_code == 200
        limited = await login(api)
        assert_error(limited, 429, "auth_rate_limited")
        assert limited.headers["retry-after"] == "1"
        await asyncio.sleep(1.2)
        assert (await login(api)).status_code == 200


async def test_rate_limit_keys_never_contain_raw_values(
    make_api: ApiFactory, test_redis: Redis, user: User
) -> None:
    async with make_api() as api:
        await login(api)

    keys = [key async for key in test_redis.scan_iter("*")]
    assert keys
    for key in keys:
        assert EMAIL not in key
        assert "127.0.0.1" not in key


# --- Other endpoints --------------------------------------------------------------------


async def test_refresh_is_limited_per_ip(make_api: ApiFactory, user: User) -> None:
    async with make_api(auth_refresh_max_attempts_per_ip=2) as api:
        await login(api)
        assert (await api.post("/api/v1/auth/refresh", headers=csrf_header(api))).status_code == 200
        assert (await api.post("/api/v1/auth/refresh", headers=csrf_header(api))).status_code == 200
        limited = await api.post("/api/v1/auth/refresh", headers=csrf_header(api))

    assert_error(limited, 429, "auth_rate_limited")
    assert "set-cookie" not in limited.headers


async def test_password_change_is_limited_per_user(make_api: ApiFactory, user: User) -> None:
    payload = {
        "current_password": "not my password at all",
        "new_password": "a brand new passphrase",
        "new_password_confirmation": "a brand new passphrase",
    }
    async with make_api(auth_password_change_max_attempts=2) as api:
        token = (await login(api)).json()["access_token"]
        for _ in range(2):
            response = await api.post(
                "/api/v1/auth/change-password", json=payload, headers=bearer(token)
            )
            assert response.status_code == 422
        limited = await api.post(
            "/api/v1/auth/change-password",
            json=payload | {"current_password": PASSWORD},
            headers=bearer(token),
        )

    assert_error(limited, 429, "auth_rate_limited")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/auth/logout"),
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/auth/me/permissions"),
    ],
)
async def test_session_endpoints_are_limited(
    make_api: ApiFactory, user: User, method: str, path: str
) -> None:
    async with make_api(auth_session_max_requests_per_ip=1) as api:
        await api.request(method, path)
        limited = await api.request(method, path)

    assert_error(limited, 429, "auth_rate_limited")


def test_every_auth_endpoint_is_rate_limited() -> None:
    # The application router includes sub-routers lazily, so walk the auth router itself.
    limiters = {"limit_login", "limit_refresh", "limit_session", "limit_password_change"}
    routes = [route for route in auth_router.routes if isinstance(route, APIRoute)]
    assert {route.path for route in routes} == {
        "/token",
        "/refresh",
        "/logout",
        "/me",
        "/me/permissions",
        "/change-password",
    }
    for route in routes:
        names = {
            getattr(dependency.call, "__name__", "")
            for dependency in _flatten(route.dependant)
            if dependency.call is not None
        }
        assert names & limiters, route.path


def _flatten(dependant: Any) -> list[Any]:
    found = []
    for dependency in dependant.dependencies:
        found.append(dependency)
        found.extend(_flatten(dependency))
    return found


# --- Redis unavailable ------------------------------------------------------------------


@pytest.fixture
async def broken_redis() -> AsyncIterator[Redis]:
    redis = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    yield redis
    await redis.aclose()


async def test_redis_outage_fails_closed_for_login_and_password_change(
    make_api: ApiFactory, broken_redis: Redis, user: User
) -> None:
    async with make_api() as healthy:
        token = (await login(healthy)).json()["access_token"]

    async with make_api(redis=broken_redis) as api:
        login_response = await login(api)
        change = await api.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": PASSWORD,
                "new_password": "a brand new passphrase",
                "new_password_confirmation": "a brand new passphrase",
            },
            headers=bearer(token),
        )
        me = await api.get("/api/v1/auth/me", headers=bearer(token))

    assert_error(login_response, 503, "auth_service_unavailable")
    assert_error(change, 503, "auth_service_unavailable")
    # Endpoints that already require a valid token or session fail open.
    assert me.status_code == 200


async def test_redis_outage_fails_open_for_refresh_and_logout(
    make_api: ApiFactory, broken_redis: Redis, user: User
) -> None:
    async with make_api() as healthy:
        cookies = {name: str(c["value"]) for name, c in set_cookies(await login(healthy)).items()}

    async with make_api(redis=broken_redis) as api:
        refreshed = await api.post(
            "/api/v1/auth/refresh",
            headers=cookie_header(cookies) | {"X-CSRF-Token": cookies[CSRF]},
        )
        rotated = {name: str(c["value"]) for name, c in set_cookies(refreshed).items()}
        logout = await api.post(
            "/api/v1/auth/logout",
            headers=cookie_header(rotated) | {"X-CSRF-Token": rotated[CSRF]},
        )

    assert refreshed.status_code == 200
    assert logout.status_code == 204


# --- Client IP and proxies ----------------------------------------------------------------


def request_from(peer: str, forwarded: list[str] | None = None) -> Request:
    headers = [(b"x-forwarded-for", value.encode()) for value in forwarded or []]
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


@pytest.mark.parametrize(
    ("peer", "forwarded", "trusted", "expected"),
    [
        # Untrusted peers: forwarded headers are ignored entirely.
        ("203.0.113.9", ["198.51.100.1"], [], "203.0.113.9"),
        ("10.0.0.5", ["198.51.100.1"], [], "10.0.0.5"),
        # A trusted proxy: the rightmost untrusted hop is the client.
        ("10.0.0.5", ["198.51.100.1"], ["10.0.0.0/8"], "198.51.100.1"),
        ("10.0.0.5", ["6.6.6.6, 198.51.100.1, 10.0.0.7"], ["10.0.0.0/8"], "198.51.100.1"),
        ("10.0.0.5", ["6.6.6.6", "198.51.100.1"], ["10.0.0.0/8"], "198.51.100.1"),
        # Trusted proxy without a usable header: fall back sensibly.
        ("10.0.0.5", [], ["10.0.0.0/8"], "10.0.0.5"),
        ("10.0.0.5", ["garbage"], ["10.0.0.0/8"], "10.0.0.5"),
        ("10.0.0.5", ["10.0.0.9"], ["10.0.0.0/8"], "10.0.0.9"),
        ("::ffff:203.0.113.9", [], [], "203.0.113.9"),
    ],
)
def test_client_ip_resolution(
    peer: str, forwarded: list[str], trusted: list[str], expected: str
) -> None:
    assert client_ip(request_from(peer, forwarded), NETWORKS.validate_python(trusted)) == expected


async def test_spoofed_forwarded_headers_cannot_evade_ip_limits(
    make_api: ApiFactory, user: User
) -> None:
    async with make_api(auth_login_max_attempts_per_ip=2) as api:
        responses = [
            await api.post(
                "/api/v1/auth/token",
                data={"username": f"u{index}@estatehub.example", "password": "wrong password!"},
                headers={"X-Forwarded-For": f"198.51.100.{index}"},
            )
            for index in range(3)
        ]

    assert [r.status_code for r in responses] == [401, 401, 429]


async def test_trusted_proxy_forwarded_address_is_used(
    make_api: ApiFactory, session_factory: Sessions, user: User
) -> None:
    async with make_api(auth_login_max_attempts_per_ip=1, trusted_proxies=["127.0.0.1/32"]) as api:
        statuses = [
            (
                await api.post(
                    "/api/v1/auth/token",
                    data={"username": EMAIL, "password": PASSWORD},
                    headers={"X-Forwarded-For": f"198.51.100.{index}"},
                )
            ).status_code
            for index in range(2)
        ]

    assert statuses == [200, 200]
    succeeded = await events(session_factory, AuditEventCode.AUTH_LOGIN_SUCCEEDED)
    assert [e.details["client_ip_prefix"] for e in succeeded] == ["198.51.100.0/24"] * 2


# --- Security audit events --------------------------------------------------------------


async def test_login_success_and_failure_events(
    api: AsyncClient, session_factory: Sessions, user: User
) -> None:
    success = await login(api)
    wrong = await login(api, password="wrong password!")
    unknown = await login(api, "nobody@estatehub.example", "wrong password!")

    (succeeded,) = await events(session_factory, AuditEventCode.AUTH_LOGIN_SUCCEEDED)
    assert (succeeded.actor_id, succeeded.entity_id) == (user.id, user.id)
    assert succeeded.request_id == success.headers["x-request-id"]
    assert set(succeeded.details) == {"session_family_id", "client_ip_prefix"}

    failed = await events(session_factory, AuditEventCode.AUTH_LOGIN_FAILED)
    assert [e.details["reason"] for e in failed] == ["wrong_password", "unknown_email"]
    assert [e.request_id for e in failed] == [
        wrong.headers["x-request-id"],
        unknown.headers["x-request-id"],
    ]
    for event in failed:
        assert event.actor_id is None
        assert len(event.details["email_fingerprint"]) == 64
        assert "nobody" not in str(event.details)
        assert EMAIL not in str(event.details)
        assert "wrong password" not in str(event.details)
    assert failed[0].details["email_fingerprint"] != failed[1].details["email_fingerprint"]
    repeat = await login(api, password="wrong password!")
    assert repeat.status_code == 401
    latest = (await events(session_factory, AuditEventCode.AUTH_LOGIN_FAILED))[-1]
    assert latest.details["email_fingerprint"] == failed[0].details["email_fingerprint"]


async def test_rate_limit_exceeded_is_audited_once_per_window(
    make_api: ApiFactory, session_factory: Sessions, user: User
) -> None:
    async with make_api(auth_login_max_attempts_per_email=1) as api:
        await login(api)
        for _ in range(3):
            await login(api)

    (limited,) = await events(session_factory, AuditEventCode.AUTH_RATE_LIMITED)
    assert limited.details["rule"] == "login:email"
    assert len(limited.details["email_fingerprint"]) == 64
    assert EMAIL not in str(limited.details)


async def test_refresh_reuse_logout_and_password_change_events(
    api: AsyncClient, clock: Clock, session_factory: Sessions, user: User
) -> None:
    old_refresh = str(set_cookies(await login(api))[REFRESH]["value"])
    await api.post("/api/v1/auth/refresh", headers=csrf_header(api))
    clock.advance(minutes=1)
    csrf = api.cookies[CSRF]
    await api.post(
        "/api/v1/auth/refresh",
        headers=with_cookies(api, {"X-CSRF-Token": csrf}, {REFRESH: old_refresh, CSRF: csrf}),
    )

    (reused,) = await events(session_factory, AuditEventCode.AUTH_REFRESH_TOKEN_REUSED)
    assert (reused.actor_id, reused.entity_id) == (None, user.id)
    assert reused.details["revoked_sessions"] == 1

    api.cookies.clear()
    await login(api)
    headers = csrf_header(api)
    await api.post("/api/v1/auth/logout", headers=headers)
    await api.post("/api/v1/auth/logout", headers=headers)
    (logout,) = await events(session_factory, AuditEventCode.AUTH_LOGOUT)
    assert logout.actor_id == user.id

    token = (await login(api)).json()["access_token"]
    await api.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": PASSWORD,
            "new_password": "a brand new passphrase",
            "new_password_confirmation": "a brand new passphrase",
        },
        headers=bearer(token),
    )
    (changed,) = await events(session_factory, AuditEventCode.AUTH_PASSWORD_CHANGED)
    assert changed.actor_id == user.id
    assert changed.details == {"revoked_sessions": 1}
    assert "brand new" not in str(changed.details)


async def test_permission_denials_are_audited(api: AsyncClient, session_factory: Sessions) -> None:
    agent = await create_staff(session_factory, ["agent"])

    response = await api.get("/api/v1/staff", headers=bearer(await token_for(api, agent)))

    assert response.status_code == 403
    (denied,) = await events(session_factory, AuditEventCode.AUTH_PERMISSION_DENIED)
    assert denied.actor_id == agent.id
    assert denied.request_id == response.headers["x-request-id"]
    assert denied.details == {
        "required_permissions": ["staff:read"],
        "permission_mode": "all",
        "method": "GET",
        "path": "/api/v1/staff",
    }


# --- Audit events API -------------------------------------------------------------------

AUDIT = "/api/v1/audit-events"


@pytest.mark.parametrize(
    ("role", "status"),
    [("administrator", 200), ("manager", 403), ("agent", 403), ("accountant", 403)],
)
async def test_audit_api_permissions(
    api: AsyncClient, session_factory: Sessions, role: str, status: int
) -> None:
    caller = await create_staff(session_factory, [role])

    response = await api.get(AUDIT, headers=bearer(await token_for(api, caller)))

    assert response.status_code == status
    api.cookies.clear()
    assert_error(await api.get(AUDIT), 401, "authentication_required")


async def seed(session_factory: Sessions, actor: User) -> list[AuditEvent]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    entity = uuid.uuid4()
    rows = [
        AuditEvent(
            id=uuid.uuid4(),
            event_code=code,
            actor_id=actor_id,
            entity_type="user" if with_entity else None,
            entity_id=entity if with_entity else None,
            occurred_at=base + timedelta(hours=hour),
            details={},
        )
        for hour, code, actor_id, with_entity in [
            (0, "staff.created", actor.id, True),
            (1, "staff.disabled", actor.id, True),
            (2, "auth.login_failed", None, False),
            (3, "staff.reactivated", actor.id, True),
        ]
    ]
    async with session_factory() as db:
        db.add_all(rows)
        await db.commit()
    return rows


async def test_audit_api_filters_and_pagination(
    api: AsyncClient, session_factory: Sessions
) -> None:
    admin = await create_staff(session_factory, ["administrator"])
    headers = bearer(await token_for(api, admin))
    rows = await seed(session_factory, admin)
    seeded = {"occurred_to": "2026-01-02T00:00:00Z"}

    async def ids(**params: Any) -> list[str]:
        response = await api.get(AUDIT, params=seeded | params, headers=headers)
        assert response.status_code == 200, response.text
        return [item["id"] for item in response.json()["items"]]

    newest_first = [str(row.id) for row in reversed(rows)]
    assert await ids() == newest_first
    assert await ids(limit=2) + await ids(limit=2, offset=2) == newest_first
    assert await ids(event_code="staff.disabled") == [str(rows[1].id)]
    assert await ids(actor_id=str(admin.id)) == [str(rows[3].id), str(rows[1].id), str(rows[0].id)]
    assert await ids(entity_type="user", entity_id=str(rows[0].entity_id)) == [
        str(rows[3].id),
        str(rows[1].id),
        str(rows[0].id),
    ]
    assert await ids(occurred_from="2026-01-01T01:00:00Z", occurred_to="2026-01-01T03:00:00Z") == [
        str(rows[2].id),
        str(rows[1].id),
    ]

    page = (await api.get(AUDIT, params=seeded | {"limit": 1}, headers=headers)).json()
    assert (page["total"], page["limit"], page["offset"]) == (4, 1, 0)
    assert set(page["items"][0]) == {
        "id",
        "event_code",
        "actor_id",
        "entity_type",
        "entity_id",
        "occurred_at",
        "request_id",
        "metadata",
    }


@pytest.mark.parametrize(
    "params",
    [
        {"occurred_from": "2026-01-02T00:00:00Z", "occurred_to": "2026-01-01T00:00:00Z"},
        {"occurred_from": "2026-01-01T00:00:00"},
        {"limit": 101},
        {"event_code": "NotACode"},
        {"unknown": "x"},
    ],
)
async def test_audit_api_rejects_invalid_filters(
    api: AsyncClient, session_factory: Sessions, params: dict[str, Any]
) -> None:
    admin = await create_staff(session_factory, ["administrator"])

    response = await api.get(AUDIT, params=params, headers=bearer(await token_for(api, admin)))

    assert response.status_code == 422


def test_audit_api_is_read_only() -> None:
    paths = {path: set(operations) for path, operations in app.openapi()["paths"].items()}
    assert {path for path in paths if path.startswith(AUDIT)} == {AUDIT}
    assert paths[AUDIT] == {"get"}
