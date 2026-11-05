"""Runs the media and documents migration against a temporary PostgreSQL database."""

from collections.abc import Iterator

import pytest
from alembic.config import Config
from migration_support import (
    expected_schema,
    inspect_schema,
    make_alembic_config,
    temporary_database,
)

from alembic import command

REVISION = "20261104_0006"
PREVIOUS = "20261104_0005"
TABLES = {"media_assets", "documents"}


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with temporary_database("estatehub_media_migration_test") as url:
        yield url


@pytest.fixture
def alembic_config(database_url: str) -> Config:
    return make_alembic_config(database_url)


def test_upgrade_creates_declared_schema(alembic_config: Config, database_url: str) -> None:
    command.upgrade(alembic_config, REVISION)

    actual = inspect_schema(database_url)
    assert {name: actual[name] for name in TABLES} == expected_schema(TABLES)


def test_downgrade_removes_file_metadata_only(alembic_config: Config, database_url: str) -> None:
    command.upgrade(alembic_config, REVISION)

    command.downgrade(alembic_config, PREVIOUS)

    tables = set(inspect_schema(database_url))
    assert not TABLES & tables
    assert {"properties", "units"} <= tables
    command.upgrade(alembic_config, "head")
