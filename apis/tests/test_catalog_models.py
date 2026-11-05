"""Reference-data models: normalization, relationships, ordering, and constraints via the ORM."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.catalog.models import Amenity, PropertySubtype, PropertyType
from app.catalog.text import normalize_label, normalize_optional_text

Sessions = async_sessionmaker[AsyncSession]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("House", "House"),
        ("  Student   room ", "Student room"),
        ("Office\tspace\n", "Office space"),
    ],
)
def test_labels_are_trimmed_and_collapsed(raw: str, expected: str) -> None:
    assert normalize_label(raw) == expected
    assert PropertyType(name=raw).name == expected


def test_optional_text_is_trimmed_and_blank_becomes_none() -> None:
    assert normalize_optional_text(None) is None
    assert normalize_optional_text("   ") is None
    assert normalize_optional_text("  Detached homes  ") == "Detached homes"
    assert PropertyType(name="House", description="  ").description is None


def test_amenity_category_is_a_lowercase_code() -> None:
    assert Amenity(name="Pool", category=" Outdoor ").category == "outdoor"
    assert Amenity(name="Pool", category="").category is None


def test_subtype_cannot_move_to_another_type() -> None:
    subtype = PropertySubtype(name="Villa", property_type_id=uuid.uuid4())
    subtype.property_type_id = subtype.property_type_id

    with pytest.raises(ValueError, match="cannot move"):
        subtype.property_type_id = uuid.uuid4()


async def test_flush_returns_generated_key_and_defaults(session_factory: Sessions) -> None:
    async with session_factory() as db:
        row = PropertyType(name="  Mixed   Use ")
        db.add(row)
        await db.commit()

        assert row.name == "Mixed Use"
        assert row.name_key == "mixed use"
        assert row.is_active is True
        assert row.display_order == 0
        assert row.created_at is not None


async def test_case_insensitive_duplicates_are_rejected(session_factory: Sessions) -> None:
    async with session_factory() as db:
        db.add(Amenity(name="Swimming pool"))
        await db.commit()

    async with session_factory() as db:
        db.add(Amenity(name="SWIMMING   POOL"))
        with pytest.raises(IntegrityError, match="uq_amenities_name_key"):
            await db.commit()


async def test_subtypes_load_in_deterministic_order(session_factory: Sessions) -> None:
    async with session_factory() as db:
        parent = PropertyType(name="Residential")
        parent.subtypes = [
            PropertySubtype(name="Villa", display_order=20),
            PropertySubtype(name="apartment", display_order=10),
            PropertySubtype(name="House", display_order=10),
            PropertySubtype(name="Bungalow", display_order=30, is_active=False),
        ]
        db.add(parent)
        await db.commit()
        parent_id = parent.id

    async with session_factory() as db:
        loaded = (
            await db.scalars(
                select(PropertyType)
                .where(PropertyType.id == parent_id)
                .options(selectinload(PropertyType.subtypes))
            )
        ).one()

        # display_order, then case-insensitive name; disabled rows stay attached.
        assert [s.name for s in loaded.subtypes] == ["apartment", "House", "Villa", "Bungalow"]
        assert all(s.property_type_id == parent_id for s in loaded.subtypes)


async def test_unloaded_relationships_raise(session_factory: Sessions) -> None:
    async with session_factory() as db:
        db.add(PropertyType(name="Commercial"))
        await db.commit()

    async with session_factory() as db:
        loaded = (await db.scalars(select(PropertyType))).one()
        with pytest.raises(InvalidRequestError):
            _ = loaded.subtypes


async def test_types_order_by_display_order_name_then_id(session_factory: Sessions) -> None:
    async with session_factory() as db:
        db.add_all(
            [
                PropertyType(name="Land", display_order=40),
                PropertyType(name="commercial", display_order=10),
                PropertyType(name="Agricultural", display_order=10),
            ]
        )
        await db.commit()

    async with session_factory() as db:
        names = await db.scalars(
            select(PropertyType.name).order_by(
                PropertyType.display_order, PropertyType.name_key, PropertyType.id
            )
        )

        assert list(names) == ["Agricultural", "commercial", "Land"]


async def test_a_type_with_subtypes_cannot_be_deleted(session_factory: Sessions) -> None:
    async with session_factory() as db:
        parent = PropertyType(name="Student accommodation")
        parent.subtypes = [PropertySubtype(name="Student room")]
        db.add(parent)
        await db.commit()

    async with session_factory() as db:
        loaded = (await db.scalars(select(PropertyType))).one()
        await db.delete(loaded)
        with pytest.raises(IntegrityError, match="fk_property_subtypes_property_type_id"):
            await db.commit()
