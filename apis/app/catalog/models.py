"""Administrator-managed reference data: property types, subtypes, and amenities.

These are data, not source-code enums. Rows are disabled and reactivated rather than
deleted, so records that already use a disabled row stay valid.

Case-insensitive uniqueness: ``name`` is stored trimmed with inner whitespace collapsed,
and PostgreSQL derives ``name_key = lower(name)`` as a stored generated column. A plain
unique constraint on ``name_key`` then rejects "House" next to "house", serves as an
``ON CONFLICT`` target for seeding, and is the deterministic sort key after
``display_order``. ``lower()`` follows the database collation, which is enough for
human-entered labels; it does not apply full Unicode case folding.
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.catalog.constants import (
    AMENITY_CATEGORY_MAX_LENGTH,
    DISPLAY_ORDER_MAX,
    REFERENCE_DESCRIPTION_MAX_LENGTH,
    REFERENCE_NAME_MAX_LENGTH,
)
from app.catalog.text import normalize_label, normalize_optional_text
from app.core.database import Base, TimestampMixin


def _label_checks() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint("char_length(name) > 0", name="name_not_blank"),
        CheckConstraint(r"name = btrim(name) AND name !~ '\s\s'", name="name_normalized"),
        CheckConstraint(
            "description IS NULL OR char_length(btrim(description)) > 0",
            name="description_not_blank",
        ),
        CheckConstraint(
            f"display_order BETWEEN 0 AND {DISPLAY_ORDER_MAX}", name="display_order_range"
        ),
    )


class ReferenceDataMixin(TimestampMixin):
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(REFERENCE_NAME_MAX_LENGTH))
    name_key: Mapped[str] = mapped_column(
        String(REFERENCE_NAME_MAX_LENGTH), Computed("lower(name)", persisted=True)
    )
    description: Mapped[str | None] = mapped_column(String(REFERENCE_DESCRIPTION_MAX_LENGTH))
    display_order: Mapped[int] = mapped_column(default=0, server_default="0")
    # Inactive rows stay valid where already used but cannot be newly assigned.
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    @validates("name")
    def _normalize_name(self, _: str, name: str) -> str:
        return normalize_label(name)

    @validates("description")
    def _normalize_description(self, _: str, description: str | None) -> str | None:
        return normalize_optional_text(description)


class PropertyType(ReferenceDataMixin, Base):
    __tablename__ = "property_types"
    __table_args__ = (
        UniqueConstraint("name_key"),
        *_label_checks(),
        Index("ix_property_types_ordering", "display_order", "name_key", "id"),
    )

    # Ordered like every reference list: display_order, then name, then ID.
    subtypes: Mapped[list[PropertySubtype]] = relationship(
        back_populates="property_type",
        lazy="raise",
        # Leave deletes to the database, whose RESTRICT keeps subtypes from being orphaned.
        passive_deletes="all",
        order_by="[PropertySubtype.display_order, PropertySubtype.name_key, PropertySubtype.id]",
    )


class PropertySubtype(ReferenceDataMixin, Base):
    __tablename__ = "property_subtypes"
    __table_args__ = (
        # Names are unique within their parent type; this also indexes the foreign key.
        UniqueConstraint("property_type_id", "name_key"),
        # Lets later tables reference (type, subtype) together, so the database itself
        # guarantees a selected subtype belongs to the selected type.
        UniqueConstraint("property_type_id", "id"),
        *_label_checks(),
        Index(
            "ix_property_subtypes_ordering", "property_type_id", "display_order", "name_key", "id"
        ),
    )

    # RESTRICT: a type with subtypes is disabled, never deleted.
    property_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("property_types.id", ondelete="RESTRICT")
    )

    property_type: Mapped[PropertyType] = relationship(back_populates="subtypes", lazy="raise")

    @validates("property_type_id")
    def _parent_is_immutable(self, _: str, property_type_id: uuid.UUID) -> uuid.UUID:
        if self.property_type_id is not None and self.property_type_id != property_type_id:
            raise ValueError("A subtype cannot move to another property type.")
        return property_type_id


class Amenity(ReferenceDataMixin, Base):
    __tablename__ = "amenities"
    __table_args__ = (
        UniqueConstraint("name_key"),
        *_label_checks(),
        CheckConstraint("category ~ '^[a-z][a-z_]*$'", name="category_format"),
        Index("ix_amenities_ordering", "display_order", "name_key", "id"),
    )

    # A short grouping code such as "outdoor" or "security"; free-form labels stay in name.
    category: Mapped[str | None] = mapped_column(String(AMENITY_CATEGORY_MAX_LENGTH))

    @validates("category")
    def _normalize_category(self, _: str, category: str | None) -> str | None:
        normalized = normalize_optional_text(category)
        return normalized.lower() if normalized else None
