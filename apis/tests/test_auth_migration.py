"""Runs the authentication migration against a temporary PostgreSQL database."""

import asyncio
import importlib.util
import uuid
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import Connection, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from alembic import command
from app.core.config import settings
from app.core.database import Base
from app.users.constants import INITIAL_ROLES

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = API_ROOT / "alembic" / "versions" / "20261103_0001_authentication.py"
AUTH_TABLES = {"users", "roles", "user_roles", "refresh_sessions", "audit_events"}


def run[T](factory: Callable[[], Awaitable[T]]) -> T:
    async def main() -> T:
        return await factory()

    return asyncio.run(main())


async def _admin(statement: str) -> None:
    engine = create_async_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    name = f"estatehub_migration_test_{uuid.uuid4().hex[:12]}"
    try:
        run(lambda: _admin(f"CREATE DATABASE {name}"))
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not reachable: {exc}")
    try:
        yield settings.database_url.rsplit("/", 1)[0] + f"/{name}"
    finally:
        run(lambda: _admin(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))


@pytest.fixture
def alembic_config(database_url: str) -> Config:
    # No ini file: loading one would reconfigure logging for the whole test session.
    config = Config()
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def query[T](database_url: str, work: Callable[[AsyncConnection], Awaitable[T]]) -> T:
    async def main() -> T:
        engine = create_async_engine(database_url)
        try:
            async with engine.begin() as connection:
                return await work(connection)
        finally:
            await engine.dispose()

    return asyncio.run(main())


def inspect_schema(database_url: str) -> dict[str, dict[str, set[str]]]:
    def collect(connection: Connection) -> dict[str, dict[str, set[str]]]:
        inspector = inspect(connection)
        schema: dict[str, dict[str, set[str]]] = {}
        for table in inspector.get_table_names():
            primary_key = inspector.get_pk_constraint(table)["name"]
            schema[table] = {
                "pk": {primary_key} if primary_key else set(),
                "fk": {str(fk["name"]) for fk in inspector.get_foreign_keys(table)},
                "uq": {str(uq["name"]) for uq in inspector.get_unique_constraints(table)},
                "ck": {str(ck["name"]) for ck in inspector.get_check_constraints(table)},
                # Unique constraints are backed by indexes; count those only as constraints.
                "ix": {
                    str(ix["name"])
                    for ix in inspector.get_indexes(table)
                    if "duplicates_constraint" not in ix
                },
            }
        return schema

    async def work(connection: AsyncConnection) -> dict[str, dict[str, set[str]]]:
        return await connection.run_sync(collect)

    return query(database_url, work)


def expected_schema() -> dict[str, dict[str, set[str]]]:
    """Constraint and index names declared on the ORM models."""
    import app.models  # noqa: F401

    schema: dict[str, dict[str, set[str]]] = {}
    for name in AUTH_TABLES:
        table = Base.metadata.tables[name]
        by_kind: dict[str, set[str]] = {kind: set() for kind in ("pk", "fk", "uq", "ck", "ix")}
        for constraint in table.constraints:
            kind = {
                "PrimaryKeyConstraint": "pk",
                "ForeignKeyConstraint": "fk",
                "UniqueConstraint": "uq",
                "CheckConstraint": "ck",
            }[type(constraint).__name__]
            by_kind[kind].add(str(constraint.name))
        by_kind["ix"] = {str(index.name) for index in table.indexes}
        schema[name] = by_kind
    return schema


def role_rows(database_url: str) -> list[tuple[Any, ...]]:
    async def work(connection: AsyncConnection) -> list[tuple[Any, ...]]:
        result = await connection.execute(
            text("SELECT id, code, name, description FROM roles ORDER BY code")
        )
        return [tuple(row) for row in result]

    return query(database_url, work)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("auth_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_matches_application_roles() -> None:
    migration = load_migration()

    seeded = {
        code: (role_id, name, description)
        for role_id, code, name, description in migration.INITIAL_ROLES
    }
    assert set(seeded) == {role.code.value for role in INITIAL_ROLES}
    for role in INITIAL_ROLES:
        role_id, name, description = seeded[role.code]
        assert role_id == str(uuid.uuid5(uuid.NAMESPACE_URL, f"urn:estatehub:role:{role.code}"))
        assert (name, description) == (role.name, role.description)


def test_upgrade_creates_declared_schema_and_roles(
    alembic_config: Config, database_url: str
) -> None:
    command.upgrade(alembic_config, "head")

    actual = inspect_schema(database_url)
    assert AUTH_TABLES <= set(actual)
    assert {name: actual[name] for name in AUTH_TABLES} == expected_schema()

    assert [row[1] for row in role_rows(database_url)] == [
        "accountant",
        "administrator",
        "agent",
        "manager",
    ]


def test_models_match_migration(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")

    command.check(alembic_config)


@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        (
            "INSERT INTO users (id, email, full_name, password_hash) "
            "VALUES (gen_random_uuid(), 'dup@estatehub.example', 'Dup', 'h')",
            "uq_users_email",
        ),
        (
            "INSERT INTO users (id, email, full_name, password_hash) "
            "VALUES (gen_random_uuid(), 'Dup@EstateHub.example', 'Dup', 'h')",
            "ck_users_email_normalized",
        ),
        (
            "INSERT INTO user_roles (user_id, role_id) "
            "SELECT id, '310c740e-80f6-53c6-a5cf-44594700712f' FROM users "
            "WHERE email = 'dup@estatehub.example'",
            "pk_user_roles",
        ),
    ],
)
def test_database_rejects_duplicates(
    alembic_config: Config, database_url: str, statement: str, constraint: str
) -> None:
    command.upgrade(alembic_config, "head")

    async def setup(connection: AsyncConnection) -> None:
        await connection.execute(
            text(
                "INSERT INTO users (id, email, full_name, password_hash) "
                "VALUES (gen_random_uuid(), 'dup@estatehub.example', 'Dup', 'h') "
                "ON CONFLICT DO NOTHING"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO user_roles (user_id, role_id) "
                "SELECT id, '310c740e-80f6-53c6-a5cf-44594700712f' FROM users "
                "WHERE email = 'dup@estatehub.example' ON CONFLICT DO NOTHING"
            )
        )

    async def duplicate(connection: AsyncConnection) -> None:
        await connection.execute(text(statement))

    query(database_url, setup)
    with pytest.raises(IntegrityError) as error:
        query(database_url, duplicate)

    assert error.value.orig is not None
    assert constraint in str(error.value.orig)


def test_downgrade_and_upgrade_preserve_unrelated_data(
    alembic_config: Config, database_url: str
) -> None:
    command.upgrade(alembic_config, "head")

    async def create_unrelated(connection: AsyncConnection) -> None:
        await connection.execute(text("CREATE TABLE IF NOT EXISTS unrelated_notes (note text)"))
        await connection.execute(text("INSERT INTO unrelated_notes VALUES ('keep me')"))

    async def unrelated_notes(connection: AsyncConnection) -> list[str]:
        result = await connection.execute(text("SELECT note FROM unrelated_notes"))
        return [row[0] for row in result]

    query(database_url, create_unrelated)

    command.downgrade(alembic_config, "base")
    tables = set(inspect_schema(database_url))
    assert not AUTH_TABLES & tables
    assert {"alembic_version", "unrelated_notes"} == tables
    assert query(database_url, unrelated_notes) == ["keep me"]

    command.upgrade(alembic_config, "head")
    assert len(role_rows(database_url)) == 4
    assert query(database_url, unrelated_notes) == ["keep me"]
