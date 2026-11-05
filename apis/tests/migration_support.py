"""Helpers for tests that run Alembic migrations against a temporary PostgreSQL database."""

import asyncio
import importlib.util
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import pytest
from alembic.config import Config
from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.config import settings
from app.core.database import Base

API_ROOT = Path(__file__).resolve().parents[1]
VERSIONS = API_ROOT / "alembic" / "versions"

Schema = dict[str, dict[str, set[str]]]


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


@contextmanager
def temporary_database(prefix: str) -> Iterator[str]:
    """Create an empty database and yield its URL; skip when PostgreSQL is unreachable."""
    name = f"{prefix}_{uuid.uuid4().hex[:12]}"
    try:
        run(lambda: _admin(f"CREATE DATABASE {name}"))
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not reachable: {exc}")
    try:
        yield settings.database_url.rsplit("/", 1)[0] + f"/{name}"
    finally:
        run(lambda: _admin(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))


def make_alembic_config(database_url: str) -> Config:
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


def inspect_schema(database_url: str) -> Schema:
    def collect(connection: Connection) -> Schema:
        inspector = inspect(connection)
        schema: Schema = {}
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

    async def work(connection: AsyncConnection) -> Schema:
        return await connection.run_sync(collect)

    return query(database_url, work)


def expected_schema(tables: set[str]) -> Schema:
    """Constraint and index names declared on the ORM models."""
    import app.models  # noqa: F401

    schema: Schema = {}
    for name in tables:
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


def load_migration(filename: str) -> ModuleType:
    path = VERSIONS / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
