"""Runs the units migration against a temporary PostgreSQL database."""

import uuid
from collections.abc import Iterator

import pytest
from alembic.config import Config
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

REVISION = "20261104_0005"
PREVIOUS = "20261104_0004"
TABLES = {"units", "unit_amenities", "properties"}
RESIDENTIAL = str(uuid.uuid5(uuid.NAMESPACE_URL, "urn:estatehub:property-type:residential"))


@pytest.fixture
def database_url() -> Iterator[str]:
    with temporary_database("estatehub_units_migration_test") as url:
        yield url


@pytest.fixture
def alembic_config(database_url: str) -> Config:
    return make_alembic_config(database_url)


def scalar(database_url: str, statement: str) -> object:
    async def work(connection: AsyncConnection) -> object:
        return (await connection.execute(text(statement))).scalar()

    return query(database_url, work)


def test_existing_properties_become_whole(alembic_config: Config, database_url: str) -> None:
    command.upgrade(alembic_config, PREVIOUS)
    scalar(
        database_url,
        "INSERT INTO properties (id, name, property_type_id, address_line_1, locality, "
        f"region, country_code) VALUES (gen_random_uuid(), 'Kept', '{RESIDENTIAL}', "
        "'1 High Street', 'Bath', 'Somerset', 'GB') RETURNING id",
    )

    command.upgrade(alembic_config, REVISION)

    assert scalar(database_url, "SELECT management_mode FROM properties") == "whole"
    actual = inspect_schema(database_url)
    assert {name: actual[name] for name in TABLES} == expected_schema(TABLES)


def test_downgrade_removes_units_and_the_mode(alembic_config: Config, database_url: str) -> None:
    command.upgrade(alembic_config, REVISION)

    command.downgrade(alembic_config, PREVIOUS)

    tables = set(inspect_schema(database_url))
    assert not {"units", "unit_amenities"} & tables
    assert (
        scalar(
            database_url,
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'properties' AND column_name = 'management_mode'",
        )
        == 0
    )
    command.upgrade(alembic_config, "head")
