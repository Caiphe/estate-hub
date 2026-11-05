"""Runs the reference-data migration against a temporary PostgreSQL database."""

import uuid
from collections.abc import Iterator
from types import ModuleType

import pytest
from alembic.config import Config
from migration_support import (
    expected_schema,
    inspect_schema,
    load_migration,
    make_alembic_config,
    query,
    temporary_database,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from alembic import command
from app.catalog.text import normalize_label

REVISION = "20261104_0002"
PREVIOUS = "20261103_0001"
TABLES = {"property_types", "property_subtypes", "amenities"}
RESIDENTIAL = str(uuid.uuid5(uuid.NAMESPACE_URL, "urn:estatehub:property-type:residential"))
COMMERCIAL = str(uuid.uuid5(uuid.NAMESPACE_URL, "urn:estatehub:property-type:commercial"))
HOUSE = str(uuid.uuid5(uuid.NAMESPACE_URL, "urn:estatehub:property-subtype:residential/house"))


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with temporary_database("estatehub_catalog_migration_test") as url:
        yield url


@pytest.fixture
def alembic_config(database_url: str) -> Config:
    config = make_alembic_config(database_url)
    command.upgrade(config, "head")
    return config


@pytest.fixture(scope="module")
def migration() -> ModuleType:
    return load_migration("20261104_0002_catalog_reference_data.py")


def counts(database_url: str) -> dict[str, int]:
    async def work(connection: AsyncConnection) -> dict[str, int]:
        return {
            table: (await connection.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            for table in sorted(TABLES)
        }

    return query(database_url, work)


def execute(database_url: str, *statements: str) -> None:
    async def work(connection: AsyncConnection) -> None:
        for statement in statements:
            await connection.execute(text(statement))

    query(database_url, work)


def reseed(database_url: str, migration: ModuleType) -> None:
    async def work(connection: AsyncConnection) -> None:
        for statement in migration.seed_statements():
            await connection.execute(statement)

    query(database_url, work)


# --- Seed content -----------------------------------------------------------------------


def test_seed_covers_each_inventory_family(migration: ModuleType) -> None:
    subtypes = {
        name.lower() for _, _, _, children in migration.PROPERTY_TYPES for _, name in children
    }
    types = {name.lower() for _, name, _, _ in migration.PROPERTY_TYPES}

    assert {"residential", "student accommodation", "commercial", "land"} == types
    assert {
        "house",
        "apartment",
        "villa",
        "cottage",
        "student residence",
        "student room",
        "office",
        "shop",
        "warehouse",
        "residential plot",
    } <= subtypes
    assert all(children for _, _, _, children in migration.PROPERTY_TYPES)


def test_seed_labels_are_normalized_and_unique(migration: ModuleType) -> None:
    type_names = [name for _, name, _, _ in migration.PROPERTY_TYPES]
    amenity_names = [name for _, name, _ in migration.AMENITIES]
    for names in (type_names, amenity_names):
        assert all(normalize_label(name) == name for name in names)
        assert len({name.lower() for name in names}) == len(names)
    for _, _, _, children in migration.PROPERTY_TYPES:
        assert len({name.lower() for _, name in children}) == len(children)
    assert all(category.isidentifier() for _, _, category in migration.AMENITIES)


def test_seed_ids_are_deterministic(migration: ModuleType) -> None:
    assert migration.seed_id("property-type", "residential") == RESIDENTIAL
    assert migration.seed_id("property-subtype", "residential/house") == HOUSE
    assert migration.seed_id("amenity", "parking") == str(
        uuid.uuid5(uuid.NAMESPACE_URL, "urn:estatehub:amenity:parking")
    )


# --- Upgrade ----------------------------------------------------------------------------


def test_upgrade_creates_declared_schema(alembic_config: Config, database_url: str) -> None:
    actual = inspect_schema(database_url)

    assert TABLES <= set(actual)
    assert {name: actual[name] for name in TABLES} == expected_schema(TABLES)


def test_upgrade_seeds_reference_data(
    alembic_config: Config, database_url: str, migration: ModuleType
) -> None:
    async def work(connection: AsyncConnection) -> list[tuple[str, str]]:
        result = await connection.execute(
            text(
                "SELECT t.name, s.name FROM property_subtypes s "
                "JOIN property_types t ON t.id = s.property_type_id "
                "WHERE t.id = :type_id ORDER BY s.display_order, s.name_key, s.id"
            ),
            {"type_id": RESIDENTIAL},
        )
        return [(row[0], row[1]) for row in result]

    seeded = counts(database_url)

    assert seeded["property_types"] == len(migration.PROPERTY_TYPES)
    assert seeded["property_subtypes"] == sum(len(c) for *_, c in migration.PROPERTY_TYPES)
    assert seeded["amenities"] == len(migration.AMENITIES)
    assert query(database_url, work)[:3] == [
        ("Residential", "House"),
        ("Residential", "Apartment"),
        ("Residential", "Villa"),
    ]


def test_seeded_rows_are_active_unowned_and_keyed(
    alembic_config: Config, database_url: str
) -> None:
    async def work(connection: AsyncConnection) -> tuple[object, ...]:
        result = await connection.execute(
            text(
                "SELECT name_key, is_active, created_by_id, description IS NULL "
                "FROM property_subtypes WHERE id = :id"
            ),
            {"id": HOUSE},
        )
        return tuple(result.one())

    assert query(database_url, work) == ("house", True, None, True)


def test_reseeding_creates_no_duplicates(
    alembic_config: Config, database_url: str, migration: ModuleType
) -> None:
    before = counts(database_url)

    reseed(database_url, migration)
    reseed(database_url, migration)

    assert counts(database_url) == before


def test_reseeding_keeps_administrator_changes(
    alembic_config: Config, database_url: str, migration: ModuleType
) -> None:
    execute(
        database_url,
        f"UPDATE property_subtypes SET name = 'Detached house', is_active = false "
        f"WHERE id = '{HOUSE}'",
    )
    try:
        before = counts(database_url)
        reseed(database_url, migration)

        async def work(connection: AsyncConnection) -> list[tuple[str, bool]]:
            result = await connection.execute(
                text(
                    "SELECT name, is_active FROM property_subtypes "
                    "WHERE property_type_id = :type_id AND name_key LIKE '%house'"
                ),
                {"type_id": RESIDENTIAL},
            )
            return sorted((row[0], row[1]) for row in result)

        assert counts(database_url) == before
        assert query(database_url, work) == [("Detached house", False), ("Townhouse", True)]
    finally:
        execute(
            database_url,
            f"UPDATE property_subtypes SET name = 'House', is_active = true WHERE id = '{HOUSE}'",
        )


# --- Database constraints ---------------------------------------------------------------


def _insert_type(name: str, display_order: int = 0) -> str:
    return (
        "INSERT INTO property_types (id, name, display_order) "
        f"VALUES (gen_random_uuid(), '{name}', {display_order})"
    )


def _insert_subtype(type_id: str, name: str) -> str:
    return (
        "INSERT INTO property_subtypes (id, property_type_id, name) "
        f"VALUES (gen_random_uuid(), '{type_id}', '{name}')"
    )


@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        (_insert_type("RESIDENTIAL"), "uq_property_types_name_key"),
        (_insert_type(""), "ck_property_types_name_not_blank"),
        (_insert_type(" Padded"), "ck_property_types_name_normalized"),
        (_insert_type("Double  space"), "ck_property_types_name_normalized"),
        (_insert_type("Negative", -1), "ck_property_types_display_order_range"),
        (_insert_subtype(RESIDENTIAL, "HOUSE"), "uq_property_subtypes_property_type_id_name_key"),
        (
            _insert_subtype(str(uuid.uuid4()), "Orphan"),
            "fk_property_subtypes_property_type_id_property_types",
        ),
        (
            "INSERT INTO property_subtypes (id, name) VALUES (gen_random_uuid(), 'No parent')",
            "property_type_id",
        ),
        (
            "INSERT INTO amenities (id, name) VALUES (gen_random_uuid(), 'parking')",
            "uq_amenities_name_key",
        ),
        (
            "INSERT INTO amenities (id, name, category) "
            "VALUES (gen_random_uuid(), 'Sauna', 'Wellness area')",
            "ck_amenities_category_format",
        ),
        (
            "INSERT INTO amenities (id, name, description) "
            "VALUES (gen_random_uuid(), 'Sauna', '   ')",
            "ck_amenities_description_not_blank",
        ),
        (f"DELETE FROM property_types WHERE id = '{RESIDENTIAL}'", "fk_property_subtypes"),
        (
            f"UPDATE property_subtypes SET name_key = 'other' WHERE id = '{HOUSE}'",
            "name_key",
        ),
    ],
)
def test_database_enforces_reference_rules(
    alembic_config: Config, database_url: str, statement: str, constraint: str
) -> None:
    with pytest.raises(DBAPIError) as error:
        execute(database_url, statement)

    assert constraint in str(error.value)


def test_subtype_names_are_unique_only_within_their_type(
    alembic_config: Config, database_url: str
) -> None:
    # "House" exists under Residential; a commercial "house" is a different subtype.
    execute(database_url, _insert_subtype(COMMERCIAL, "house"))
    try:
        with pytest.raises(IntegrityError):
            execute(database_url, _insert_subtype(COMMERCIAL, "House"))
    finally:
        execute(
            database_url,
            f"DELETE FROM property_subtypes WHERE property_type_id = '{COMMERCIAL}' "
            "AND name_key = 'house'",
        )


# --- Downgrade --------------------------------------------------------------------------


def test_downgrade_removes_reference_data_and_keeps_authentication(
    alembic_config: Config, database_url: str, migration: ModuleType
) -> None:
    command.downgrade(alembic_config, PREVIOUS)

    tables = set(inspect_schema(database_url))
    assert not TABLES & tables
    assert {"users", "roles", "audit_events"} <= tables

    command.upgrade(alembic_config, REVISION)
    assert counts(database_url)["property_types"] == len(migration.PROPERTY_TYPES)
