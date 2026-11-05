"""The physical property aggregate: identity, classification, address, and physical facts.

Only the asset lives here. Prices, sale/rent terms, rental categories, and publication
belong to listings (prompt 03).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Column,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    Sequence,
    SmallInteger,
    String,
    Table,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.catalog.checks import (
    country_code_check,
    non_negative_check,
    normalized_check,
    not_blank_check,
    postal_code_check,
)
from app.catalog.models import Amenity, PropertySubtype, PropertyType
from app.catalog.text import normalize_label, normalize_optional_label, normalize_optional_text
from app.contacts.models import Contact
from app.core.database import Base, TimestampMixin, str_enum
from app.properties.constants import (
    ADDRESS_LINE_MAX_LENGTH,
    FLOOR_LABEL_MAX_LENGTH,
    LOCALITY_MAX_LENGTH,
    OWNERSHIP_NOTES_MAX_LENGTH,
    POSTAL_CODE_MAX_LENGTH,
    PROPERTY_DESCRIPTION_MAX_LENGTH,
    PROPERTY_NAME_MAX_LENGTH,
    PROPERTY_NOTES_MAX_LENGTH,
    PROPERTY_REFERENCE_MAX_LENGTH,
    PROPERTY_REFERENCE_PREFIX,
    REGION_MAX_LENGTH,
    UNIT_IDENTIFIER_MAX_LENGTH,
    UNIT_NAME_MAX_LENGTH,
    YEAR_BUILT_MAX,
    YEAR_BUILT_MIN,
    AreaUnit,
    FurnishedState,
    ManagementMode,
    PropertyStatus,
    UnitStatus,
)

# References come from a sequence, so concurrent inserts can never collide. Starting at
# 100001 keeps every reference the same width for years without zero-padding.
property_reference_seq = Sequence("property_reference_seq", start=100_001, metadata=Base.metadata)
REFERENCE_DEFAULT = text(f"'{PROPERTY_REFERENCE_PREFIX}' || nextval('property_reference_seq')")

property_amenities = Table(
    "property_amenities",
    Base.metadata,
    Column("property_id", ForeignKey("properties.id", ondelete="CASCADE"), primary_key=True),
    # RESTRICT: an amenity in use is disabled, never deleted.
    Column("amenity_id", ForeignKey("amenities.id", ondelete="RESTRICT"), primary_key=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    # The composite primary key prevents duplicates and serves property lookups; this
    # serves the amenity filter.
    Index("ix_property_amenities_amenity_id", "amenity_id"),
)


class Property(TimestampMixin, Base):
    __tablename__ = "properties"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    reference: Mapped[str] = mapped_column(
        String(PROPERTY_REFERENCE_MAX_LENGTH), unique=True, server_default=REFERENCE_DEFAULT
    )
    name: Mapped[str] = mapped_column(String(PROPERTY_NAME_MAX_LENGTH))
    # Internal description of the asset; public marketing copy belongs to listings.
    description: Mapped[str | None] = mapped_column(String(PROPERTY_DESCRIPTION_MAX_LENGTH))
    property_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("property_types.id", ondelete="RESTRICT")
    )
    property_subtype_id: Mapped[uuid.UUID | None]
    status: Mapped[PropertyStatus] = mapped_column(
        str_enum(PropertyStatus, "property_status"),
        default=PropertyStatus.DRAFT,
        server_default=PropertyStatus.DRAFT.value,
    )
    management_mode: Mapped[ManagementMode] = mapped_column(
        str_enum(ManagementMode, "management_mode"),
        default=ManagementMode.WHOLE,
        server_default=ManagementMode.WHOLE.value,
    )

    address_line_1: Mapped[str] = mapped_column(String(ADDRESS_LINE_MAX_LENGTH))
    address_line_2: Mapped[str | None] = mapped_column(String(ADDRESS_LINE_MAX_LENGTH))
    locality: Mapped[str] = mapped_column(String(LOCALITY_MAX_LENGTH))
    region: Mapped[str] = mapped_column(String(REGION_MAX_LENGTH))
    postal_code: Mapped[str | None] = mapped_column(String(POSTAL_CODE_MAX_LENGTH))
    # ISO 3166-1 alpha-2, checked structurally. It does not prove the address exists.
    country_code: Mapped[str] = mapped_column(String(2))
    # Six decimal places is about 0.1 m, more than enough for a building.
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))

    year_built: Mapped[int | None] = mapped_column(SmallInteger)
    bedrooms: Mapped[int | None] = mapped_column(SmallInteger)
    # Whole or half bathrooms (1.5 = one full bathroom and one with no bath or shower).
    bathrooms: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    floors: Mapped[int | None] = mapped_column(SmallInteger)
    parking_spaces: Mapped[int | None] = mapped_column(SmallInteger)
    furnished_state: Mapped[FurnishedState | None] = mapped_column(
        str_enum(FurnishedState, "furnished_state")
    )
    land_area: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    floor_area: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    area_unit: Mapped[AreaUnit | None] = mapped_column(str_enum(AreaUnit, "area_unit"))

    # Staff-only. Never add this field to a public schema.
    internal_notes: Mapped[str | None] = mapped_column(String(PROPERTY_NOTES_MAX_LENGTH))

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    archived_at: Mapped[datetime | None]
    archived_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Optimistic concurrency: SQLAlchemy adds "AND version = :old" to every UPDATE and
    # increments it, so a stale writer updates no row and gets StaleDataError.
    version: Mapped[int] = mapped_column(default=1, server_default="1")

    __mapper_args__: dict[str, Any] = {"eager_defaults": True, "version_id_col": version}
    __table_args__ = (
        # A subtype must belong to the selected type. MATCH SIMPLE skips the check when
        # no subtype is selected.
        ForeignKeyConstraint(
            ["property_type_id", "property_subtype_id"],
            ["property_subtypes.property_type_id", "property_subtypes.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            f"reference ~ '^{PROPERTY_REFERENCE_PREFIX}[0-9]{{6,}}$'", name="reference_format"
        ),
        normalized_check("name"),
        not_blank_check("description"),
        normalized_check("address_line_1"),
        normalized_check("address_line_2", optional=True),
        normalized_check("locality"),
        normalized_check("region"),
        postal_code_check(),
        country_code_check(),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="coordinates_complete"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
        CheckConstraint(
            f"year_built BETWEEN {YEAR_BUILT_MIN} AND {YEAR_BUILT_MAX}", name="year_built_range"
        ),
        non_negative_check("bedrooms"),
        CheckConstraint(
            "bathrooms >= 0 AND bathrooms * 2 = floor(bathrooms * 2)",
            name="bathrooms_half_units",
        ),
        non_negative_check("floors"),
        non_negative_check("parking_spaces"),
        non_negative_check("land_area"),
        non_negative_check("floor_area"),
        CheckConstraint(
            "(area_unit IS NULL) = (land_area IS NULL AND floor_area IS NULL)",
            name="area_unit_matches_areas",
        ),
        not_blank_check("internal_notes"),
        CheckConstraint(
            f"(status = '{PropertyStatus.ARCHIVED.value}') = (archived_at IS NOT NULL)",
            name="archived_state_consistent",
        ),
        CheckConstraint(
            "archived_by_id IS NULL OR archived_at IS NOT NULL", name="archived_by_needs_date"
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_properties_status", "status"),
        Index("ix_properties_classification", "property_type_id", "property_subtype_id"),
        Index("ix_properties_property_subtype_id", "property_subtype_id"),
        Index("ix_properties_location", "country_code", "region", "locality"),
        # Case-insensitive "contains" search (ILIKE) over these columns uses trigrams.
        Index(
            "ix_properties_search_trgm",
            "reference",
            "name",
            "locality",
            "region",
            postgresql_using="gin",
            postgresql_ops={
                "reference": "gin_trgm_ops",
                "name": "gin_trgm_ops",
                "locality": "gin_trgm_ops",
                "region": "gin_trgm_ops",
            },
        ),
        # Normal lists exclude archived records and sort by recency.
        Index(
            "ix_properties_unarchived_updated_at",
            "updated_at",
            "id",
            postgresql_where=text(f"status <> '{PropertyStatus.ARCHIVED.value}'"),
        ),
    )

    property_type: Mapped[PropertyType] = relationship(lazy="raise", viewonly=True)
    property_subtype: Mapped[PropertySubtype | None] = relationship(
        lazy="raise",
        viewonly=True,
        primaryjoin="PropertySubtype.id == foreign(Property.property_subtype_id)",
    )
    amenities: Mapped[list[Amenity]] = relationship(
        secondary=property_amenities,
        lazy="raise",
        order_by=[Amenity.display_order, Amenity.name_key, Amenity.id],
    )
    # Every unit, archived ones included; queries filter. Units are created and changed
    # through the unit service, never through this collection.
    units: Mapped[list[Unit]] = relationship(
        lazy="raise",
        viewonly=True,
        order_by="[Unit.identifier_key, Unit.id]",
    )

    @validates("reference")
    def _reference_is_server_generated(self, _: str, reference: str) -> str:
        raise ValueError("A property reference is generated by the database.")

    @validates("name", "address_line_1", "locality", "region")
    def _normalize_required_label(self, _: str, value: str) -> str:
        return normalize_label(value)

    @validates("address_line_2")
    def _normalize_optional_label(self, _: str, value: str | None) -> str | None:
        return normalize_optional_label(value)

    @validates("description", "internal_notes")
    def _normalize_text(self, _: str, value: str | None) -> str | None:
        return normalize_optional_text(value)

    @validates("postal_code")
    def _normalize_postal_code(self, _: str, value: str | None) -> str | None:
        normalized = normalize_optional_label(value)
        return normalized.upper() if normalized else None

    @validates("country_code")
    def _normalize_country_code(self, _: str, value: str) -> str:
        return value.strip().upper()

    @property
    def is_archived(self) -> bool:
        return self.status == PropertyStatus.ARCHIVED


class PropertyOwnership(TimestampMixin, Base):
    """A contact's ownership of a property, optionally with a share and dates.

    ``start_date``/``end_date`` record when the ownership held in the real world. Ending
    a link through the API sets ``archived_at`` instead; archived links are history, are
    never changed again, and do not count toward share totals or duplicate checks.
    """

    __tablename__ = "property_ownerships"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # RESTRICT: properties and contacts are archived, never deleted, while linked.
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id", ondelete="RESTRICT"))
    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contacts.id", ondelete="RESTRICT"))
    # Percent with two decimals; unknown shares stay NULL rather than being guessed.
    share_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    start_date: Mapped[date | None]
    end_date: Mapped[date | None]
    # Staff-only. Never add this field to audit metadata or a public schema.
    notes: Mapped[str | None] = mapped_column(String(OWNERSHIP_NOTES_MAX_LENGTH))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    archived_at: Mapped[datetime | None]
    archived_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint(
            "share_percentage > 0 AND share_percentage <= 100", name="share_percentage_range"
        ),
        CheckConstraint("end_date >= start_date", name="dates_ordered"),
        not_blank_check("notes"),
        CheckConstraint(
            "archived_by_id IS NULL OR archived_at IS NOT NULL", name="archived_by_needs_date"
        ),
        # One current link per property and contact. Ended links are history.
        Index(
            "uq_property_ownerships_current_link",
            "property_id",
            "contact_id",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        Index("ix_property_ownerships_contact_id", "contact_id"),
    )

    contact: Mapped[Contact] = relationship(lazy="raise", viewonly=True)

    @validates("property_id", "contact_id")
    def _link_is_immutable(self, key: str, value: uuid.UUID) -> uuid.UUID:
        if getattr(self, key) is not None and getattr(self, key) != value:
            raise ValueError("An ownership link cannot move to another property or contact.")
        return value

    @validates("notes")
    def _normalize_notes(self, _: str, value: str | None) -> str | None:
        return normalize_optional_text(value)

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


unit_amenities = Table(
    "unit_amenities",
    Base.metadata,
    Column("unit_id", ForeignKey("units.id", ondelete="CASCADE"), primary_key=True),
    # RESTRICT: an amenity in use is disabled, never deleted.
    Column("amenity_id", ForeignKey("amenities.id", ondelete="RESTRICT"), primary_key=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Index("ix_unit_amenities_amenity_id", "amenity_id"),
)


class Unit(TimestampMixin, Base):
    """A separately managed space inside a property: an apartment, office, shop, or room.

    Units belong to exactly one property and never move to another, and a unit never
    contains other units. Archiving a property leaves its units untouched; queries for
    active units also exclude units of archived properties.
    """

    __tablename__ = "units"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id", ondelete="RESTRICT"))
    # Staff-facing label such as "Flat 2B" or "Bay 4". Unique per property among active
    # units, ignoring case, through identifier_key = lower(identifier).
    identifier: Mapped[str] = mapped_column(String(UNIT_IDENTIFIER_MAX_LENGTH))
    identifier_key: Mapped[str] = mapped_column(
        String(UNIT_IDENTIFIER_MAX_LENGTH), Computed("lower(identifier)", persisted=True)
    )
    name: Mapped[str | None] = mapped_column(String(UNIT_NAME_MAX_LENGTH))
    floor_label: Mapped[str | None] = mapped_column(String(FLOOR_LABEL_MAX_LENGTH))
    description: Mapped[str | None] = mapped_column(String(PROPERTY_DESCRIPTION_MAX_LENGTH))
    # Must be a subtype of the parent property's type (checked by the unit service).
    property_subtype_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("property_subtypes.id", ondelete="RESTRICT")
    )
    bedrooms: Mapped[int | None] = mapped_column(SmallInteger)
    bathrooms: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    capacity: Mapped[int | None] = mapped_column(SmallInteger)
    floor_area: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    area_unit: Mapped[AreaUnit | None] = mapped_column(str_enum(AreaUnit, "area_unit"))
    furnished_state: Mapped[FurnishedState | None] = mapped_column(
        str_enum(FurnishedState, "furnished_state")
    )
    status: Mapped[UnitStatus] = mapped_column(
        str_enum(UnitStatus, "unit_status"),
        default=UnitStatus.AVAILABLE,
        server_default=UnitStatus.AVAILABLE.value,
    )
    # Staff-only. Never add this field to a public schema.
    internal_notes: Mapped[str | None] = mapped_column(String(PROPERTY_NOTES_MAX_LENGTH))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    archived_at: Mapped[datetime | None]
    archived_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(default=1, server_default="1")

    __mapper_args__: dict[str, Any] = {"eager_defaults": True, "version_id_col": version}
    __table_args__ = (
        normalized_check("identifier"),
        normalized_check("name", optional=True),
        normalized_check("floor_label", optional=True),
        not_blank_check("description"),
        non_negative_check("bedrooms"),
        CheckConstraint(
            "bathrooms >= 0 AND bathrooms * 2 = floor(bathrooms * 2)",
            name="bathrooms_half_units",
        ),
        non_negative_check("capacity"),
        non_negative_check("floor_area"),
        CheckConstraint(
            "(area_unit IS NULL) = (floor_area IS NULL)", name="area_unit_matches_area"
        ),
        not_blank_check("internal_notes"),
        CheckConstraint(
            "archived_by_id IS NULL OR archived_at IS NOT NULL", name="archived_by_needs_date"
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        # One active unit per identifier and property; archived units keep theirs.
        Index(
            "uq_units_current_identifier",
            "property_id",
            "identifier_key",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        # Serves the property's unit list (archived included) in display order.
        Index("ix_units_property_ordering", "property_id", "identifier_key", "id"),
        Index("ix_units_property_subtype_id", "property_subtype_id"),
        Index("ix_units_status", "status"),
    )

    property_subtype: Mapped[PropertySubtype | None] = relationship(lazy="raise", viewonly=True)
    amenities: Mapped[list[Amenity]] = relationship(
        secondary=unit_amenities,
        lazy="raise",
        order_by=[Amenity.display_order, Amenity.name_key, Amenity.id],
    )

    @validates("property_id")
    def _property_is_immutable(self, _: str, property_id: uuid.UUID) -> uuid.UUID:
        if self.property_id is not None and self.property_id != property_id:
            raise ValueError("A unit cannot move to another property.")
        return property_id

    @validates("identifier")
    def _normalize_identifier(self, _: str, value: str) -> str:
        return normalize_label(value)

    @validates("name", "floor_label")
    def _normalize_optional_label(self, _: str, value: str | None) -> str | None:
        return normalize_optional_label(value)

    @validates("description", "internal_notes")
    def _normalize_text(self, _: str, value: str | None) -> str | None:
        return normalize_optional_text(value)

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None
