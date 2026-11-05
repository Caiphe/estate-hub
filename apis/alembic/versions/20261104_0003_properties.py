"""Create properties and their amenity associations.

Revision ID: 20261104_0003
Revises: 20261104_0002
Create Date: 2026-11-04

Values below are copied, not imported, so this revision never changes when application
code changes later.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261104_0003"
down_revision: str | None = "20261104_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROPERTY_STATUSES = ("draft", "active", "inactive", "archived")
FURNISHED_STATES = ("furnished", "part_furnished", "unfurnished")
AREA_UNITS = ("square_metre", "square_foot")
REFERENCE_PREFIX = "PR-"
REFERENCE_START = 100_001


def _one_of(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _normalized(column: str, *, optional: bool = False) -> sa.CheckConstraint:
    rule = f"char_length({column}) > 0 AND {column} = btrim({column}) AND {column} !~ '\\s\\s'"
    if optional:
        rule = f"{column} IS NULL OR ({rule})"
    return sa.CheckConstraint(rule, name=op.f(f"ck_properties_{column}_normalized"))


def _not_blank(column: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(
        f"{column} IS NULL OR char_length(btrim({column})) > 0",
        name=op.f(f"ck_properties_{column}_not_blank"),
    )


def _non_negative(column: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"{column} >= 0", name=op.f(f"ck_properties_{column}_non_negative"))


def _user_fk(column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=op.f(f"fk_properties_{column}_users"), ondelete="SET NULL"
    )


def upgrade() -> None:
    # Trigram indexes make case-insensitive "contains" search indexable. pg_trgm is a
    # trusted extension, so a database owner can create it without superuser rights.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(f"CREATE SEQUENCE property_reference_seq START WITH {REFERENCE_START}")

    op.create_table(
        "properties",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "reference",
            sa.String(20),
            server_default=sa.text(f"'{REFERENCE_PREFIX}' || nextval('property_reference_seq')"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(5000), nullable=True),
        sa.Column("property_type_id", sa.Uuid(), nullable=False),
        sa.Column("property_subtype_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column("address_line_1", sa.String(200), nullable=False),
        sa.Column("address_line_2", sa.String(200), nullable=True),
        sa.Column("locality", sa.String(100), nullable=False),
        sa.Column("region", sa.String(100), nullable=False),
        sa.Column("postal_code", sa.String(20), nullable=True),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("latitude", sa.Numeric(8, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("year_built", sa.SmallInteger(), nullable=True),
        sa.Column("bedrooms", sa.SmallInteger(), nullable=True),
        sa.Column("bathrooms", sa.Numeric(4, 1), nullable=True),
        sa.Column("floors", sa.SmallInteger(), nullable=True),
        sa.Column("parking_spaces", sa.SmallInteger(), nullable=True),
        sa.Column("furnished_state", sa.String(32), nullable=True),
        sa.Column("land_area", sa.Numeric(12, 2), nullable=True),
        sa.Column("floor_area", sa.Numeric(12, 2), nullable=True),
        sa.Column("area_unit", sa.String(32), nullable=True),
        sa.Column("internal_notes", sa.String(10000), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_properties")),
        sa.UniqueConstraint("reference", name=op.f("uq_properties_reference")),
        sa.ForeignKeyConstraint(
            ["property_type_id"],
            ["property_types.id"],
            name=op.f("fk_properties_property_type_id_property_types"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["property_type_id", "property_subtype_id"],
            ["property_subtypes.property_type_id", "property_subtypes.id"],
            name=op.f("fk_properties_property_type_id_property_subtypes"),
            ondelete="RESTRICT",
        ),
        _user_fk("created_by_id"),
        _user_fk("updated_by_id"),
        _user_fk("archived_by_id"),
        sa.CheckConstraint(
            f"reference ~ '^{REFERENCE_PREFIX}[0-9]{{6,}}$'",
            name=op.f("ck_properties_reference_format"),
        ),
        _normalized("name"),
        _not_blank("description"),
        _normalized("address_line_1"),
        _normalized("address_line_2", optional=True),
        _normalized("locality"),
        _normalized("region"),
        sa.CheckConstraint(
            "postal_code IS NULL OR (postal_code = upper(btrim(postal_code)) "
            "AND char_length(postal_code) > 0)",
            name=op.f("ck_properties_postal_code_normalized"),
        ),
        sa.CheckConstraint(
            "country_code ~ '^[A-Z]{2}$'", name=op.f("ck_properties_country_code_format")
        ),
        sa.CheckConstraint(
            "(latitude IS NULL) = (longitude IS NULL)",
            name=op.f("ck_properties_coordinates_complete"),
        ),
        sa.CheckConstraint(
            "latitude BETWEEN -90 AND 90", name=op.f("ck_properties_latitude_range")
        ),
        sa.CheckConstraint(
            "longitude BETWEEN -180 AND 180", name=op.f("ck_properties_longitude_range")
        ),
        sa.CheckConstraint(
            "year_built BETWEEN 1000 AND 2999", name=op.f("ck_properties_year_built_range")
        ),
        _non_negative("bedrooms"),
        sa.CheckConstraint(
            "bathrooms >= 0 AND bathrooms * 2 = floor(bathrooms * 2)",
            name=op.f("ck_properties_bathrooms_half_units"),
        ),
        _non_negative("floors"),
        _non_negative("parking_spaces"),
        _non_negative("land_area"),
        _non_negative("floor_area"),
        sa.CheckConstraint(
            "(area_unit IS NULL) = (land_area IS NULL AND floor_area IS NULL)",
            name=op.f("ck_properties_area_unit_matches_areas"),
        ),
        _not_blank("internal_notes"),
        sa.CheckConstraint(
            "(status = 'archived') = (archived_at IS NOT NULL)",
            name=op.f("ck_properties_archived_state_consistent"),
        ),
        sa.CheckConstraint(
            "archived_by_id IS NULL OR archived_at IS NOT NULL",
            name=op.f("ck_properties_archived_by_needs_date"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_properties_version_positive")),
        sa.CheckConstraint(
            _one_of("status", PROPERTY_STATUSES), name=op.f("ck_properties_property_status")
        ),
        sa.CheckConstraint(
            _one_of("furnished_state", FURNISHED_STATES),
            name=op.f("ck_properties_furnished_state"),
        ),
        sa.CheckConstraint(_one_of("area_unit", AREA_UNITS), name=op.f("ck_properties_area_unit")),
    )
    # Dropping the table drops the sequence with it.
    op.execute("ALTER SEQUENCE property_reference_seq OWNED BY properties.reference")

    op.create_index("ix_properties_status", "properties", ["status"])
    op.create_index(
        "ix_properties_classification", "properties", ["property_type_id", "property_subtype_id"]
    )
    op.create_index("ix_properties_property_subtype_id", "properties", ["property_subtype_id"])
    op.create_index("ix_properties_location", "properties", ["country_code", "region", "locality"])
    op.create_index(
        "ix_properties_search_trgm",
        "properties",
        ["reference", "name", "locality", "region"],
        postgresql_using="gin",
        postgresql_ops={
            "reference": "gin_trgm_ops",
            "name": "gin_trgm_ops",
            "locality": "gin_trgm_ops",
            "region": "gin_trgm_ops",
        },
    )
    op.create_index(
        "ix_properties_unarchived_updated_at",
        "properties",
        ["updated_at", "id"],
        postgresql_where=sa.text("status <> 'archived'"),
    )

    op.create_table(
        "property_amenities",
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("amenity_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("property_id", "amenity_id", name=op.f("pk_property_amenities")),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_property_amenities_property_id_properties"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["amenity_id"],
            ["amenities.id"],
            name=op.f("fk_property_amenities_amenity_id_amenities"),
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_property_amenities_amenity_id", "property_amenities", ["amenity_id"])


def downgrade() -> None:
    # pg_trgm stays installed: other objects may use it, and keeping it loses no data.
    op.drop_table("property_amenities")
    op.drop_table("properties")  # Also drops the owned reference sequence.
