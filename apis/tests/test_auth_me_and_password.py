"""HTTP tests for GET /auth/me and POST /auth/change-password."""

import logging
from typing import Any

import pytest
from auth_support import (
    CSRF,
    EMAIL,
    FAST,
    PASSWORD,
    REFRESH,
    Clock,
    access_token_for,
    assert_cleared,
    assert_error,
    bearer,
    csrf_header,
    execute,
    login,
    make_settings,
    set_cookies,
    with_cookies,
)
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.constants import CSRF_HEADER_NAME, RevocationReason
from app.auth.models import RefreshSession
from app.auth.repository import RefreshSessionRepository
from app.auth.service import AuthConfig, AuthService
from app.users.constants import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from app.users.models import User

Sessions = async_sessionmaker[AsyncSession]
NEW_PASSWORD = "a brand new passphrase, with spaces"
ME = "/api/v1/auth/me"
CHANGE = "/api/v1/auth/change-password"


def body(
    current: str = PASSWORD, new: str = NEW_PASSWORD, confirm: str | None = None
) -> dict[str, Any]:
    return {
        "current_password": current,
        "new_password": new,
        "new_password_confirmation": new if confirm is None else confirm,
    }


async def change(api: AsyncClient, payload: dict[str, Any]) -> Response:
    return await api.post(CHANGE, json=payload, headers=csrf_header(api))


async def session_reasons(session_factory: Sessions) -> list[RevocationReason | None]:
    async with session_factory() as db:
        return list(
            await db.scalars(
                select(RefreshSession.revoked_reason).order_by(RefreshSession.issued_at)
            )
        )


async def token_version(session_factory: Sessions) -> int:
    async with session_factory() as db:
        return (await db.scalars(select(User.token_version).where(User.email == EMAIL))).one()


# --- GET /me ----------------------------------------------------------------------------


async def test_me_returns_only_public_fields(
    api: AsyncClient, clock: Clock, session_factory: Sessions, user: User
) -> None:
    login_response = await login(api)

    response = await api.get(ME)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    me = response.json()
    assert set(me) == {
        "id",
        "email",
        "full_name",
        "status",
        "roles",
        "last_login_at",
        "created_at",
        "updated_at",
    }
    assert (me["id"], me["email"], me["status"], me["roles"]) == (
        str(user.id),
        EMAIL,
        "active",
        ["agent"],
    )
    assert me["last_login_at"].startswith(clock.now.strftime("%Y-%m-%dT%H:%M:%S"))

    async with session_factory() as db:
        stored = (await db.scalars(select(RefreshSession))).one()
    for secret in (
        "argon2",
        "token_version",
        str(stored.id),
        str(stored.family_id),
        stored.token_hash,
        str(set_cookies(login_response)[REFRESH]["value"]),
    ):
        assert secret not in response.text


async def test_me_accepts_bearer_tokens(api: AsyncClient, user: User) -> None:
    token = await access_token_for(api)
    api.cookies.clear()

    response = await api.get(ME, headers=bearer(token))

    assert response.json()["email"] == EMAIL


async def test_me_requires_authentication(api: AsyncClient) -> None:
    assert_error(await api.get(ME), 401, "authentication_required")


async def test_me_rejects_expired_tokens(api: AsyncClient, clock: Clock, user: User) -> None:
    await login(api)
    clock.advance(minutes=15)

    assert_error(await api.get(ME), 401, "token_expired")


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE users SET status = 'disabled' WHERE id = :id",
        "UPDATE users SET token_version = token_version + 1 WHERE id = :id",
        "DELETE FROM users WHERE id = :id",
    ],
)
async def test_me_rejects_tokens_for_changed_accounts(
    api: AsyncClient, session_factory: Sessions, user: User, statement: str
) -> None:
    await login(api)
    await execute(session_factory, statement, id=user.id)

    assert_error(await api.get(ME), 401, "invalid_token")


# --- POST /change-password: validation ---------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        (body(confirm="something else entirely"), "new_password_confirmation"),
        (body(new=PASSWORD), "new_password"),
        # Same password after Unicode normalization (fullwidth letters fold to ASCII).
        (body(new="ｃｏｒｒｅｃｔ horse battery staple"), "new_password"),
        (body(new="p" * (PASSWORD_MIN_LENGTH - 1)), "new_password"),
        (body(new="p" * (PASSWORD_MAX_LENGTH + 1)), "new_password"),
        (body(current=""), "current_password"),
    ],
)
async def test_invalid_input_returns_field_errors_without_echoing(
    api: AsyncClient,
    session_factory: Sessions,
    user: User,
    payload: dict[str, Any],
    field: str,
) -> None:
    await login(api)

    response = await change(api, payload)

    assert_error_with_fields(response, "validation_error", field)
    for value in payload.values():
        if value:
            assert value not in response.text
    assert await session_reasons(session_factory) == [None]


def assert_error_with_fields(response: Response, code: str, field: str) -> None:
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == code
    assert error["request_id"] == response.headers["x-request-id"]
    assert list(error["fields"]) == [field]


async def test_unknown_fields_are_rejected(api: AsyncClient, user: User) -> None:
    await login(api)

    response = await change(api, body() | {"token_version": 0})

    assert response.status_code == 422
    assert "token_version" in response.json()["error"]["fields"]


async def test_wrong_current_password_changes_nothing(
    api: AsyncClient, session_factory: Sessions, user: User
) -> None:
    await login(api)

    response = await change(api, body(current="not my password at all"))

    assert_error_with_fields(response, "current_password_incorrect", "current_password")
    assert "set-cookie" not in response.headers
    assert await session_reasons(session_factory) == [None]
    assert await token_version(session_factory) == 0
    assert (await api.get(ME)).status_code == 200


async def test_cookie_authenticated_change_requires_csrf(api: AsyncClient, user: User) -> None:
    await login(api)

    response = await api.post(CHANGE, json=body())

    assert_error(response, 403, "csrf_failed")


# --- POST /change-password: success ------------------------------------------------------


@pytest.mark.parametrize(
    "new_password",
    [
        "p" * PASSWORD_MIN_LENGTH,
        "é" * PASSWORD_MAX_LENGTH,
        "  spaced passphrase  ",
    ],
)
async def test_boundary_passwords_are_accepted_exactly(
    api: AsyncClient, user: User, new_password: str
) -> None:
    await login(api)

    assert (await change(api, body(new=new_password))).status_code == 204

    # Kept exactly as entered: the trimmed form is a different password.
    assert (await login(api, password=new_password)).status_code == 200
    if new_password != new_password.strip():
        assert (await login(api, password=new_password.strip())).status_code == 401


async def test_success_signs_out_everywhere(
    api: AsyncClient, session_factory: Sessions, user: User
) -> None:
    other_device = set_cookies(await login(api))
    old_access = await access_token_for(api)
    current_refresh = api.cookies[REFRESH]

    response = await change(api, body())

    assert response.status_code == 204
    assert response.content == b""
    assert_cleared(response)
    assert await token_version(session_factory) == 1
    assert await session_reasons(session_factory) == [RevocationReason.PASSWORD_CHANGED] * 2

    # Earlier access tokens stop working immediately, including the one just used.
    assert_error(await api.get(ME, headers=bearer(old_access)), 401, "invalid_token")
    for refresh_token in (current_refresh, str(other_device[REFRESH]["value"])):
        csrf = "c" * 43
        stale = await api.post(
            "/api/v1/auth/refresh",
            headers=with_cookies(
                api, {CSRF_HEADER_NAME: csrf}, {REFRESH: refresh_token, CSRF: csrf}
            ),
        )
        assert_error(stale, 401, "invalid_session")

    assert_error(await login(api), 401, "invalid_credentials")
    assert (await login(api, password=NEW_PASSWORD)).status_code == 200


async def test_bearer_change_needs_no_csrf(api: AsyncClient, user: User) -> None:
    token = await access_token_for(api)
    api.cookies.clear()

    response = await api.post(CHANGE, json=body(), headers=bearer(token))

    assert response.status_code == 204


async def test_passwords_never_reach_logs(
    api: AsyncClient, user: User, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        await login(api)
        await change(api, body(current="not my password at all"))
        await change(api, body(confirm="mismatched confirmation"))
        await change(api, body())

    for secret in (PASSWORD, NEW_PASSWORD, "not my password at all", "mismatched confirmation"):
        assert secret not in caplog.text


# --- Transaction ----------------------------------------------------------------------


async def test_failed_revocation_rolls_back_the_password_change(
    api: AsyncClient,
    session_factory: Sessions,
    clock: Clock,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await login(api)

    async def fail(*_: object, **__: object) -> int:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(RefreshSessionRepository, "revoke_all_for_user", fail)
    async with session_factory() as db:
        service = AuthService(
            db, AuthConfig.from_settings(make_settings()), clock=clock, password_hasher=FAST
        )
        with pytest.raises(RuntimeError):
            await service.change_password(user.id, PASSWORD, NEW_PASSWORD)
    monkeypatch.undo()

    assert await token_version(session_factory) == 0
    assert await session_reasons(session_factory) == [None]
    assert (await api.get(ME)).status_code == 200
    assert (await login(api)).status_code == 200
    assert_error(await login(api, password=NEW_PASSWORD), 401, "invalid_credentials")
