"""Runs the authentication migration against a temporary PostgreSQL database."""

import uuid
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import pytest
from alembic.config import Config
from migration_support import (
    expected_schema as declared_schema,
)
from migration_support import (
    inspect_schema,
    make_alembic_config,
    query,
    temporary_database,
)
from migration_support import (
    load_migration as load_revision,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from alembic import command
from app.users.constants import INITIAL_ROLES

AUTH_TABLES = {"users", "roles", "user_roles", "refresh_sessions", "audit_events"}


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with temporary_database("estatehub_migration_test") as url:
        yield url


@pytest.fixture
def alembic_config(database_url: str) -> Config:
    return make_alembic_config(database_url)


def expected_schema() -> dict[str, dict[str, set[str]]]:
    return declared_schema(AUTH_TABLES)


def role_rows(database_url: str) -> list[tuple[Any, ...]]:
    async def work(connection: AsyncConnection) -> list[tuple[Any, ...]]:
        result = await connection.execute(
            text("SELECT id, code, name, description FROM roles ORDER BY code")
        )
        return [tuple(row) for row in result]

    return query(database_url, work)


def load_migration() -> ModuleType:
    return load_revision("20261103_0001_authentication.py")


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
