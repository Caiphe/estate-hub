import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from auth_support import (
    EMAIL,
    TEST_KEY_PREFIX,
    Clock,
    create_user,
    make_redis,
    make_settings,
    override,
)
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from alembic import command
from app.core.config import Settings
from app.core.config import settings as app_settings
from app.main import app
from app.users.models import User

API_ROOT = Path(__file__).resolve().parents[1]
# Seeded role rows are kept between tests; everything else is cleared. Seeded reference
# data is cleared too, so no test depends on rows another test may have changed; tests
# create the reference rows they need, and the migration tests check the seed.
_TRUNCATE = (
    "TRUNCATE documents, media_assets, unit_amenities, units, property_ownerships, contacts, "
    "property_amenities, properties, amenities, property_subtypes, property_types, "
    "audit_events, refresh_sessions, user_roles, users"
)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


async def _admin(statement: str) -> None:
    engine = create_async_engine(app_settings.database_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def migrated_database_url() -> Iterator[str]:
    """A temporary PostgreSQL database upgraded to the latest migration."""
    name = f"estatehub_test_{uuid.uuid4().hex[:12]}"
    try:
        asyncio.run(_admin(f"CREATE DATABASE {name}"))
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not reachable: {exc}")
    url = app_settings.database_url.rsplit("/", 1)[0] + f"/{name}"
    try:
        # No ini file: loading one would reconfigure logging for the whole test session.
        config = Config()
        config.set_main_option("script_location", str(API_ROOT / "alembic"))
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "head")
        # Start from the same empty state that every test leaves behind.
        asyncio.run(_clear(url))
        yield url
    finally:
        asyncio.run(_admin(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))


async def _clear(url: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(_TRUNCATE))
    finally:
        await engine.dispose()


@pytest.fixture
async def db_engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_database_url, poolclass=NullPool)
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(_TRUNCATE))
        await engine.dispose()


@pytest.fixture
def session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db_engine, expire_on_commit=False)


# --- HTTP authentication fixtures (helpers in auth_support.py) --------------------------


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture(scope="session", autouse=True)
def _clean_test_redis_keys() -> Iterator[None]:
    yield

    async def clean() -> None:
        redis = make_redis()
        try:
            keys = [key async for key in redis.scan_iter(f"{TEST_KEY_PREFIX}:*")]
            if keys:
                await redis.delete(*keys)
        except OSError:
            pass
        finally:
            await redis.aclose()

    asyncio.run(clean())


@pytest.fixture
async def test_redis() -> AsyncIterator[Redis]:
    redis = make_redis()
    try:
        yield redis
    finally:
        await redis.aclose()


@pytest.fixture
async def api(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    clock: Clock,
    test_redis: Redis,
) -> AsyncIterator[AsyncClient]:
    """Client for the real app, wired to the test database, Redis, settings, and clock."""
    override(app, session_factory, settings, clock, test_redis)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
async def user(session_factory: async_sessionmaker[AsyncSession]) -> User:
    return await create_user(session_factory, EMAIL)
