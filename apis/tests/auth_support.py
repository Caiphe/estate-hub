"""Shared constants and helpers for HTTP authentication tests. Fixtures live in conftest."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient, Response
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.constants import CSRF_HEADER_NAME
from app.auth.dependencies import (
    AuthConfigDep,
    ClockDep,
    DbDep,
    get_auth_service,
    get_clock,
)
from app.auth.service import AuthService
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.core.security.passwords import hash_password
from app.users.constants import RoleCode, UserStatus
from app.users.models import Role, User

FAST = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8_192, parallelism=1),))
PASSWORD = "correct horse battery staple"
EMAIL = "ada.agent@estatehub.example"
ACCESS, REFRESH, CSRF = "estatehub_access", "estatehub_refresh", "estatehub_csrf"
JWT_KEY = "test-only-jwt-key-Q8z3Vn0Lr5Tx2Wm7Kp4Hs9Jd6"
HASH_KEY = "test-only-refresh-key-Yb1Nc8Fe3Gh6Uj9Ik2Ol5Pa7"

Sessions = async_sessionmaker[AsyncSession]


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "cors_origins": ["http://localhost:3001"],
        "jwt_secret_key": SecretStr(JWT_KEY),
        "refresh_token_hash_secret": SecretStr(HASH_KEY),
        "auth_cookie_secure": False,
    }
    return Settings(_env_file=None, **(values | overrides))


@dataclass
class Clock:
    """Starts at real time (so the client cookie jar keeps cookies) and can move forward."""

    now: datetime = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0))

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def override(target: FastAPI, session_factory: Sessions, settings: Settings, clock: Clock) -> None:
    async def db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    def service(db: DbDep, config: AuthConfigDep, clock: ClockDep) -> AuthService:
        return AuthService(db, config, clock=clock, password_hasher=FAST)

    target.dependency_overrides.update(
        {
            get_db_session: db,
            get_settings: lambda: settings,
            get_clock: lambda: clock,
            get_auth_service: service,
        }
    )


async def create_user(
    session_factory: Sessions, email: str, status: UserStatus = UserStatus.ACTIVE
) -> User:
    async with session_factory() as db:
        agent = (await db.scalars(select(Role).where(Role.code == RoleCode.AGENT))).one()
        created = User(
            email=email,
            full_name="Ada Agent",
            password_hash=hash_password(PASSWORD, FAST),
            status=status,
        )
        created.roles = [agent]
        db.add(created)
        await db.commit()
        return created


async def execute(session_factory: Sessions, statement: str, **params: Any) -> None:
    async with session_factory() as db:
        await db.execute(text(statement), params)
        await db.commit()


def set_cookies(response: Response) -> dict[str, dict[str, str | bool]]:
    """Parse every Set-Cookie header into {name: {attribute: value}}."""
    parsed: dict[str, dict[str, str | bool]] = {}
    for header in response.headers.get_list("set-cookie"):
        name, _, rest = header.partition("=")
        value, *attributes = rest.split(";")
        cookie: dict[str, str | bool] = {"value": value}
        for attribute in attributes:
            key, sep, attr_value = attribute.strip().partition("=")
            cookie[key.lower()] = attr_value if sep else True
        parsed[name] = cookie
    return parsed


def assert_cleared(response: Response) -> None:
    cookies = set_cookies(response)
    assert set(cookies) == {ACCESS, REFRESH, CSRF}
    for cookie in cookies.values():
        assert cookie["max-age"] == "0"
        assert cookie["value"] in {"", '""'}


async def login(api: AsyncClient, email: str = EMAIL, password: str = PASSWORD) -> Response:
    return await api.post("/api/v1/auth/token", data={"username": email, "password": password})


def cookie_header(cookies: dict[str, str]) -> dict[str, str]:
    """An explicit Cookie header; httpx then ignores its own cookie jar for the request."""
    return {"cookie": "; ".join(f"{name}={value}" for name, value in cookies.items())}


def with_cookies(
    api: AsyncClient, headers: dict[str, str], replacements: dict[str, str]
) -> dict[str, str]:
    """The client's current cookies with some values replaced, plus extra headers."""
    return headers | cookie_header(dict(api.cookies.items()) | replacements)


def csrf_header(api: AsyncClient) -> dict[str, str]:
    return {CSRF_HEADER_NAME: api.cookies[CSRF]}


def assert_error(response: Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    assert error["request_id"] == response.headers["x-request-id"]
    assert error["fields"] == {}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def access_token_for(api: AsyncClient) -> str:
    token: str = (await login(api)).json()["access_token"]
    return token


async def create_staff(
    session_factory: Sessions,
    roles: list[str],
    status: UserStatus = UserStatus.ACTIVE,
) -> User:
    async with session_factory() as db:
        role_rows = list(await db.scalars(select(Role).where(Role.code.in_(roles))))
        assert len(role_rows) == len(roles)
        user = User(
            email=f"{'-'.join(roles) or 'none'}-{uuid.uuid4().hex[:6]}@estatehub.example",
            full_name="Staff Member",
            password_hash=hash_password(PASSWORD, FAST),
            status=status,
        )
        user.roles = role_rows
        db.add(user)
        await db.commit()
        return user


async def token_for(api: AsyncClient, user: User) -> str:
    token = (await login(api, user.email)).json()["access_token"]
    assert isinstance(token, str)
    return token
