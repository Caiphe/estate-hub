"""Runs the properties migration against a temporary PostgreSQL database."""

import uuid
from collections.abc import Iterator

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from migration_support import (
    expected_schema,
    inspect_schema,
    make_alembic_config,
    query,
    temporary_database,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from alembic import command

REVISION = "20261104_0003"
PREVIOUS = "20261104_0002"
TABLES = {"properties", "property_amenities"}
RESIDENTIAL = str(uuid.uuid5(uuid.NAMESPACE_URL, "urn:estatehub:property-type:residential"))
HOUSE = str(uuid.uuid5(uuid.NAMESPACE_URL, "urn:estatehub:property-subtype:residential/house"))
PARKING = str(uuid.uuid5(uuid.NAMESPACE_URL, "urn:estatehub:amenity:parking"))


@pytest.fixture
def database_url() -> Iterator[str]:
    # A fresh database per test: these tests walk the revision history themselves.
    with temporary_database("estatehub_property_migration_test") as url:
        yield url


@pytest.fixture
def alembic_config(database_url: str) -> Config:
    return make_alembic_config(database_url)


def scalar(database_url: str, statement: str) -> object:
    async def work(connection: AsyncConnection) -> object:
        return (await connection.execute(text(statement))).scalar()

    return query(database_url, work)


def execute(database_url: str, *statements: str) -> None:
    async def work(connection: AsyncConnection) -> None:
        for statement in statements:
            await connection.execute(text(statement))

    query(database_url, work)


def insert_property(database_url: str, name: str) -> None:
    execute(
        database_url,
        "INSERT INTO properties (id, name, property_type_id, property_subtype_id, "
        "address_line_1, locality, region, country_code) VALUES (gen_random_uuid(), "
        f"'{name}', '{RESIDENTIAL}', '{HOUSE}', '1 High Street', 'Bath', 'Somerset', 'GB')",
    )


def test_every_revision_upgrades_in_order(alembic_config: Config, database_url: str) -> None:
    revisions = [
        script.revision
        for script in reversed(list(ScriptDirectory.from_config(alembic_config).walk_revisions()))
    ]
    assert REVISION in revisions

    for revision in revisions:
        command.upgrade(alembic_config, revision)

    actual = inspect_schema(database_url)
    assert {name: actual[name] for name in TABLES} == expected_schema(TABLES)
    command.check(alembic_config)


def test_upgrade_keeps_existing_data(alembic_config: Config, database_url: str) -> None:
    command.upgrade(alembic_config, PREVIOUS)
    execute(
        database_url,
        "INSERT INTO users (id, email, full_name, password_hash) "
        "VALUES (gen_random_uuid(), 'kept@estatehub.example', 'Kept', 'h')",
        f"UPDATE property_types SET name = 'Homes' WHERE id = '{RESIDENTIAL}'",
    )

    command.upgrade(alembic_config, REVISION)

    assert scalar(database_url, "SELECT count(*) FROM users") == 1
    assert scalar(database_url, f"SELECT name FROM property_types WHERE id = '{RESIDENTIAL}'") == (
        "Homes"
    )
    assert scalar(database_url, "SELECT count(*) FROM properties") == 0


def test_references_are_sequential_and_unique(alembic_config: Config, database_url: str) -> None:
    command.upgrade(alembic_config, REVISION)

    for name in ("First", "Second"):
        insert_property(database_url, name)

    assert query(database_url, _fetch_references) == ["PR-100001", "PR-100002"]


async def _fetch_references(connection: AsyncConnection) -> list[str]:
    result = await connection.execute(text("SELECT reference FROM properties ORDER BY reference"))
    return [row[0] for row in result]


def test_search_index_uses_trigrams(alembic_config: Config, database_url: str) -> None:
    command.upgrade(alembic_config, REVISION)

    definition = scalar(
        database_url,
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_properties_search_trgm'",
    )
    assert isinstance(definition, str)
    assert "USING gin" in definition
    assert definition.count("gin_trgm_ops") == 4


def test_downgrade_removes_properties_and_keeps_reference_data(
    alembic_config: Config, database_url: str
) -> None:
    command.upgrade(alembic_config, REVISION)
    insert_property(database_url, "Doomed")
    execute(
        database_url,
        f"INSERT INTO property_amenities (property_id, amenity_id) "
        f"SELECT id, '{PARKING}' FROM properties",
    )

    command.downgrade(alembic_config, PREVIOUS)

    tables = set(inspect_schema(database_url))
    assert not TABLES & tables
    assert {"property_types", "property_subtypes", "amenities"} <= tables
    assert scalar(database_url, "SELECT to_regclass('property_reference_seq')") is None
    assert scalar(database_url, "SELECT count(*) FROM amenities") == 14

    command.upgrade(alembic_config, REVISION)
    insert_property(database_url, "Fresh")
    assert scalar(database_url, "SELECT reference FROM properties") == "PR-100001"
