"""HTTP tests for login, refresh, logout, the identity dependency, and CSRF."""

import logging
from collections.abc import AsyncIterator
from typing import Annotated

import pytest
from auth_support import (
    ACCESS,
    CSRF,
    EMAIL,
    HASH_KEY,
    JWT_KEY,
    PASSWORD,
    REFRESH,
    Clock,
    Sessions,
    access_token_for,
    assert_cleared,
    assert_error,
    bearer,
    cookie_header,
    create_user,
    csrf_header,
    execute,
    login,
    make_settings,
    override,
    set_cookies,
    with_cookies,
)
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from app.auth.constants import CSRF_HEADER_NAME, RevocationReason
from app.auth.dependencies import (
    CurrentIdentity,
    get_current_identity,
)
from app.auth.http import register_auth_exception_handlers
from app.auth.models import RefreshSession
from app.auth.service import AuthConfig
from app.core.config import Settings
from app.core.database import engine
from app.core.errors import register_exception_handlers
from app.core.middleware import RequestIdMiddleware
from app.core.security.access_tokens import create_access_token
from app.main import app
from app.users.constants import UserStatus
from app.users.models import User

# A minimal app exposing the identity dependency, since no protected route exists yet.
protected = FastAPI()
protected.add_middleware(RequestIdMiddleware)
register_exception_handlers(protected)
register_auth_exception_handlers(protected)


Identity = Annotated[CurrentIdentity, Depends(get_current_identity)]


@protected.get("/whoami")
async def whoami(identity: Identity) -> dict[str, str]:
    return {"email": identity.user.email, "method": identity.method}


@protected.post("/whoami")
async def whoami_unsafe(identity: Identity) -> dict[str, str]:
    return {"email": identity.user.email, "method": identity.method}


@pytest.fixture
async def protected_api(
    session_factory: Sessions, settings: Settings, clock: Clock
) -> AsyncIterator[AsyncClient]:
    override(protected, session_factory, settings, clock)
    try:
        transport = ASGITransport(app=protected)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        protected.dependency_overrides.clear()


# --- Login ------------------------------------------------------------------------------


async def test_login_returns_oauth2_tokens_and_sets_cookies(api: AsyncClient, user: User) -> None:
    response = await login(api)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in"}
    assert (body["token_type"], body["expires_in"]) == ("bearer", 900)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"

    cookies = set_cookies(response)
    assert cookies[ACCESS]["value"] == body["access_token"]
    assert str(cookies[REFRESH]["value"]) not in response.text
    assert str(cookies[CSRF]["value"]) not in response.text


async def test_development_cookie_attributes(api: AsyncClient, user: User) -> None:
    cookies = set_cookies(await login(api))

    assert {k: v for k, v in cookies[ACCESS].items() if k not in {"value", "expires"}} == {
        "httponly": True,
        "max-age": "900",
        "path": "/",
        "samesite": "lax",
    }
    assert {k: v for k, v in cookies[REFRESH].items() if k not in {"value", "expires"}} == {
        "httponly": True,
        "max-age": str(7 * 24 * 3600),
        "path": "/api/v1/auth",
        "samesite": "lax",
    }
    assert {k: v for k, v in cookies[CSRF].items() if k not in {"value", "expires"}} == {
        "max-age": str(7 * 24 * 3600),
        "path": "/",
        "samesite": "lax",
    }
    for cookie in cookies.values():
        assert "secure" not in cookie
        assert "domain" not in cookie
        assert "expires" in cookie


async def test_production_cookie_attributes(
    session_factory: Sessions, clock: Clock, user: User
) -> None:
    production = make_settings(
        environment="production",
        cors_origins=["https://estatehub.example"],
        auth_cookie_secure=True,
        auth_cookie_same_site="strict",
        auth_cookie_domain="estatehub.example",
    )
    override(app, session_factory, production, clock)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://estatehub.example") as api:
            response = await login(api)
            logout = await api.post("/api/v1/auth/logout", headers=csrf_header(api))
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    cookies = set_cookies(response)
    for name in (ACCESS, REFRESH, CSRF):
        assert cookies[name]["secure"] is True
        assert cookies[name]["samesite"] == "strict"
        assert cookies[name]["domain"] == "estatehub.example"
    assert cookies[ACCESS]["httponly"] is True
    assert cookies[REFRESH]["httponly"] is True
    assert "httponly" not in cookies[CSRF]

    # Deletion repeats the exact attributes, or browsers would keep the cookies.
    assert logout.status_code == 204
    cleared = set_cookies(logout)
    for name, path in ((ACCESS, "/"), (REFRESH, "/api/v1/auth"), (CSRF, "/")):
        assert (cleared[name]["path"], cleared[name]["domain"]) == (path, "estatehub.example")
        assert cleared[name]["secure"] is True


@pytest.mark.parametrize(
    ("email", "password"),
    [
        (EMAIL, "wrong password entirely"),
        ("nobody@estatehub.example", PASSWORD),
        ("disabled@estatehub.example", PASSWORD),
    ],
)
async def test_login_failures_are_indistinguishable(
    api: AsyncClient, session_factory: Sessions, user: User, email: str, password: str
) -> None:
    await create_user(session_factory, "disabled@estatehub.example", UserStatus.DISABLED)

    response = await login(api, email, password)

    assert_error(response, 401, "invalid_credentials")
    assert response.json()["error"]["message"] == "Incorrect email or password."
    assert response.headers["www-authenticate"] == "Bearer"
    assert "set-cookie" not in response.headers


async def test_login_requires_form_fields(api: AsyncClient) -> None:
    response = await api.post("/api/v1/auth/token", data={"username": EMAIL})

    assert response.status_code == 422
    assert response.json()["error"]["fields"] == {"password": ["Field required"]}


# --- Refresh ----------------------------------------------------------------------------


async def test_refresh_rotates_every_cookie(api: AsyncClient, clock: Clock, user: User) -> None:
    first = set_cookies(await login(api))
    clock.advance(minutes=20)

    response = await api.post("/api/v1/auth/refresh", headers=csrf_header(api))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    second = set_cookies(response)
    for name in (ACCESS, REFRESH, CSRF):
        assert second[name]["value"] != first[name]["value"]
    assert response.json()["access_token"] == second[ACCESS]["value"]
    # The family's absolute expiry is kept, so Max-Age shrinks by the elapsed time.
    assert second[REFRESH]["max-age"] == str(7 * 24 * 3600 - 20 * 60)


async def test_refresh_without_a_session_clears_cookies(api: AsyncClient, user: User) -> None:
    await login(api)
    api.cookies.delete(REFRESH, domain="test.local", path="/api/v1/auth")

    response = await api.post("/api/v1/auth/refresh", headers=csrf_header(api))

    assert_error(response, 401, "invalid_session")
    assert_cleared(response)


async def test_expired_session_is_rejected_and_cleared(
    api: AsyncClient, clock: Clock, user: User
) -> None:
    await login(api)
    clock.advance(days=7)

    response = await api.post("/api/v1/auth/refresh", headers=csrf_header(api))

    assert_error(response, 401, "invalid_session")
    assert_cleared(response)


async def test_reused_refresh_token_revokes_family(
    api: AsyncClient,
    clock: Clock,
    session_factory: Sessions,
    user: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    old_refresh = set_cookies(await login(api))[REFRESH]["value"]
    await api.post("/api/v1/auth/refresh", headers=csrf_header(api))
    clock.advance(minutes=1)
    assert isinstance(old_refresh, str)

    with caplog.at_level(logging.WARNING):
        reused = await api.post(
            "/api/v1/auth/refresh",
            headers=with_cookies(api, csrf_header(api), {REFRESH: old_refresh}),
        )

    assert_error(reused, 401, "invalid_session")
    assert_cleared(reused)
    assert "reuse detected" in caplog.text
    assert old_refresh not in caplog.text
    async with session_factory() as db:
        reasons = set(await db.scalars(select(RefreshSession.revoked_reason)))
    assert reasons == {RevocationReason.ROTATED, RevocationReason.REUSE_DETECTED}


async def test_concurrent_replay_is_a_conflict_that_clears_cookies(
    api: AsyncClient, user: User
) -> None:
    old_refresh = set_cookies(await login(api))[REFRESH]["value"]
    assert isinstance(old_refresh, str)
    await api.post("/api/v1/auth/refresh", headers=csrf_header(api))

    response = await api.post(
        "/api/v1/auth/refresh", headers=with_cookies(api, csrf_header(api), {REFRESH: old_refresh})
    )

    assert_error(response, 401, "invalid_session")
    assert_cleared(response)


# --- CSRF -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {CSRF_HEADER_NAME: ""},
        {CSRF_HEADER_NAME: "x" * 43},
        {CSRF_HEADER_NAME: "not a token"},
    ],
)
async def test_refresh_requires_a_matching_csrf_header(
    api: AsyncClient, user: User, headers: dict[str, str]
) -> None:
    await login(api)

    response = await api.post("/api/v1/auth/refresh", headers=headers)

    assert_error(response, 403, "csrf_failed")
    assert "set-cookie" not in response.headers


async def test_duplicated_csrf_values_are_rejected(api: AsyncClient, user: User) -> None:
    await login(api)
    token = api.cookies[CSRF]

    duplicated_header = await api.post(
        "/api/v1/auth/refresh",
        headers=[(CSRF_HEADER_NAME, token), (CSRF_HEADER_NAME, token)],
    )
    raw_cookies = "; ".join(f"{name}={value}" for name, value in api.cookies.items())
    duplicated_cookie = await api.post(
        "/api/v1/auth/refresh",
        headers={CSRF_HEADER_NAME: token, "cookie": f"{raw_cookies}; {CSRF}={token}"},
    )

    assert_error(duplicated_header, 403, "csrf_failed")
    assert_error(duplicated_cookie, 403, "csrf_failed")


# --- Logout -----------------------------------------------------------------------------


async def test_logout_revokes_and_is_idempotent(
    api: AsyncClient, session_factory: Sessions, user: User
) -> None:
    refresh_token = set_cookies(await login(api))[REFRESH]["value"]
    headers = csrf_header(api)

    first = await api.post("/api/v1/auth/logout", headers=headers)
    second = await api.post("/api/v1/auth/logout", headers=headers)

    assert first.status_code == second.status_code == 204
    assert first.content == second.content == b""
    assert_cleared(first)
    assert_cleared(second)
    async with session_factory() as db:
        revoked = list(await db.scalars(select(RefreshSession.revoked_reason)))
    assert revoked == [RevocationReason.LOGOUT]
    reuse = await api.post(
        "/api/v1/auth/refresh",
        headers=with_cookies(
            api, headers, {REFRESH: str(refresh_token), CSRF: headers[CSRF_HEADER_NAME]}
        ),
    )
    assert_error(reuse, 401, "invalid_session")


async def test_logout_with_a_session_requires_csrf(
    api: AsyncClient, session_factory: Sessions, user: User
) -> None:
    await login(api)

    response = await api.post("/api/v1/auth/logout")

    assert_error(response, 403, "csrf_failed")
    async with session_factory() as db:
        assert list(await db.scalars(select(RefreshSession.revoked_at))) == [None]


async def test_logout_with_unknown_session_reveals_nothing(api: AsyncClient) -> None:
    response = await api.post(
        "/api/v1/auth/logout",
        headers=with_cookies(
            api, {CSRF_HEADER_NAME: "c" * 43}, {REFRESH: "r" * 43, CSRF: "c" * 43}
        ),
    )

    assert response.status_code == 204
    assert_cleared(response)


# --- Identity dependency ---------------------------------------------------------------


async def test_bearer_and_cookie_authentication(
    api: AsyncClient, protected_api: AsyncClient, user: User
) -> None:
    token = await access_token_for(api)

    by_bearer = await protected_api.get("/whoami", headers=bearer(token))
    by_cookie = await protected_api.get("/whoami", headers=cookie_header({ACCESS: token}))

    assert by_bearer.json() == {"email": EMAIL, "method": "bearer"}
    assert by_cookie.json() == {"email": EMAIL, "method": "cookie"}


async def test_authorization_header_takes_precedence_without_fallback(
    api: AsyncClient, protected_api: AsyncClient, user: User
) -> None:
    token = await access_token_for(api)

    bearer_wins = await protected_api.get(
        "/whoami", headers=bearer(token) | cookie_header({ACCESS: "garbage"})
    )
    no_fallback = await protected_api.get(
        "/whoami", headers=bearer("garbage") | cookie_header({ACCESS: token})
    )
    wrong_scheme = await protected_api.get(
        "/whoami",
        headers={"Authorization": f"Basic {token}"} | cookie_header({ACCESS: token}),
    )

    assert bearer_wins.json()["method"] == "bearer"
    assert_error(no_fallback, 401, "invalid_token")
    assert_error(wrong_scheme, 401, "invalid_token")


async def test_missing_credentials(protected_api: AsyncClient) -> None:
    response = await protected_api.get("/whoami")

    assert_error(response, 401, "authentication_required")
    assert response.headers["www-authenticate"] == "Bearer"


async def test_expired_access_token(
    api: AsyncClient, protected_api: AsyncClient, clock: Clock, user: User
) -> None:
    token = await access_token_for(api)
    clock.advance(minutes=15)

    assert_error(await protected_api.get("/whoami", headers=bearer(token)), 401, "token_expired")


async def test_malformed_and_foreign_tokens(
    protected_api: AsyncClient, clock: Clock, user: User
) -> None:
    other = make_settings(jwt_secret_key=SecretStr("another-key-Zx9Cv8Bn7Mq6Wr5Ty4Ui3"))
    foreign = create_access_token(user.id, 0, AuthConfig.from_settings(other).access, now=clock.now)

    for token in ("garbage", "a.b.c", foreign.token):
        assert_error(
            await protected_api.get("/whoami", headers=bearer(token)), 401, "invalid_token"
        )


async def test_token_version_mismatch_and_disabled_user(
    api: AsyncClient, protected_api: AsyncClient, session_factory: Sessions, user: User
) -> None:
    token = await access_token_for(api)
    await execute(session_factory, "UPDATE users SET token_version = 1 WHERE id = :id", id=user.id)
    assert_error(await protected_api.get("/whoami", headers=bearer(token)), 401, "invalid_token")

    fresh = await access_token_for(api)
    await execute(
        session_factory, "UPDATE users SET status = 'disabled' WHERE id = :id", id=user.id
    )
    assert_error(await protected_api.get("/whoami", headers=bearer(fresh)), 401, "invalid_token")


async def test_unsafe_cookie_requests_require_csrf(
    api: AsyncClient, protected_api: AsyncClient, user: User
) -> None:
    await login(api)
    cookies = {ACCESS: api.cookies[ACCESS], CSRF: api.cookies[CSRF]}

    safe = await protected_api.get("/whoami", headers=cookie_header(cookies))
    missing = await protected_api.post("/whoami", headers=cookie_header(cookies))
    mismatched = await protected_api.post(
        "/whoami", headers=cookie_header(cookies) | {CSRF_HEADER_NAME: "x" * 43}
    )
    valid = await protected_api.post(
        "/whoami", headers=cookie_header(cookies) | {CSRF_HEADER_NAME: cookies[CSRF]}
    )
    bearer_exempt = await protected_api.post("/whoami", headers=bearer(cookies[ACCESS]))

    assert safe.status_code == 200
    assert_error(missing, 403, "csrf_failed")
    assert_error(mismatched, 403, "csrf_failed")
    assert valid.json()["method"] == "cookie"
    assert bearer_exempt.json()["method"] == "bearer"


# --- Contract and secrecy ---------------------------------------------------------------


async def test_missing_secrets_return_service_unavailable(
    session_factory: Sessions, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    override(app, session_factory, make_settings(jwt_secret_key=None), clock)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            with caplog.at_level(logging.ERROR):
                response = await login(api)
    finally:
        app.dependency_overrides.clear()

    assert_error(response, 503, "auth_service_unavailable")
    assert "jwt_secret_key_missing" in caplog.text


def test_engine_hides_bound_parameters() -> None:
    assert engine.sync_engine.hide_parameters


def test_openapi_describes_password_flow_and_bearer_auth() -> None:
    login_operation = app.openapi()["paths"]["/api/v1/auth/token"]["post"]
    form = login_operation["requestBody"]["content"]["application/x-www-form-urlencoded"]
    assert form["schema"]["$ref"].endswith("Body_login_api_v1_auth_token_post")

    schemes = protected.openapi()["components"]["securitySchemes"]
    assert schemes["OAuth2PasswordBearer"]["flows"]["password"]["tokenUrl"] == "/api/v1/auth/token"


async def test_secrets_never_leak_into_bodies_or_logs(
    api: AsyncClient, clock: Clock, user: User, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        login_response = await login(api)
        cookies = set_cookies(login_response)
        clock.advance(minutes=1)
        refresh_response = await api.post("/api/v1/auth/refresh", headers=csrf_header(api))
        await api.post("/api/v1/auth/logout", headers=csrf_header(api))
        failed = await login(api, password="wrong password entirely")

    refreshed = set_cookies(refresh_response)
    secrets = [
        PASSWORD,
        "wrong password entirely",
        JWT_KEY,
        HASH_KEY,
        *(str(c["value"]) for c in (*cookies.values(), *refreshed.values())),
    ]
    for secret in secrets:
        assert secret not in caplog.text
    for secret in [PASSWORD, JWT_KEY, HASH_KEY, str(cookies[REFRESH]["value"])]:
        assert secret not in login_response.text
        assert secret not in refresh_response.text
        assert secret not in failed.text
