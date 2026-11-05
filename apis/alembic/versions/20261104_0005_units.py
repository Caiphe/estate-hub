"""Add property management mode, units, and unit amenities.

Revision ID: 20261104_0005
Revises: 20261104_0004
Create Date: 2026-11-04

Values below are copied, not imported, so this revision never changes when application
code changes later.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261104_0005"
down_revision: str | None = "20261104_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MANAGEMENT_MODES = ("whole", "units", "mixed")
UNIT_STATUSES = ("available", "occupied", "unavailable")
FURNISHED_STATES = ("furnished", "part_furnished", "unfurnished")
AREA_UNITS = ("square_metre", "square_foot")


def _one_of(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _ck(name: str, rule: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(rule, name=op.f(f"ck_units_{name}"))


def _normalized(column: str, *, optional: bool = False) -> sa.CheckConstraint:
    rule = f"char_length({column}) > 0 AND {column} = btrim({column}) AND {column} !~ '\\s\\s'"
    if optional:
        rule = f"{column} IS NULL OR ({rule})"
    return _ck(f"{column}_normalized", rule)


def upgrade() -> None:
    # A constant default makes this a metadata-only change: existing rows read "whole".
    op.add_column(
        "properties",
        sa.Column("management_mode", sa.String(32), server_default="whole", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_properties_management_mode"),
        "properties",
        _one_of("management_mode", MANAGEMENT_MODES),
    )

    op.create_table(
        "units",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("identifier", sa.String(50), nullable=False),
        sa.Column(
            "identifier_key",
            sa.String(50),
            sa.Computed("lower(identifier)", persisted=True),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("floor_label", sa.String(50), nullable=True),
        sa.Column("description", sa.String(5000), nullable=True),
        sa.Column("property_subtype_id", sa.Uuid(), nullable=True),
        sa.Column("bedrooms", sa.SmallInteger(), nullable=True),
        sa.Column("bathrooms", sa.Numeric(4, 1), nullable=True),
        sa.Column("capacity", sa.SmallInteger(), nullable=True),
        sa.Column("floor_area", sa.Numeric(12, 2), nullable=True),
        sa.Column("area_unit", sa.String(32), nullable=True),
        sa.Column("furnished_state", sa.String(32), nullable=True),
        sa.Column("status", sa.String(32), server_default="available", nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_units")),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_units_property_id_properties"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["property_subtype_id"],
            ["property_subtypes.id"],
            name=op.f("fk_units_property_subtype_id_property_subtypes"),
            ondelete="RESTRICT",
        ),
        *(
            sa.ForeignKeyConstraint(
                [column], ["users.id"], name=op.f(f"fk_units_{column}_users"), ondelete="SET NULL"
            )
            for column in ("created_by_id", "updated_by_id", "archived_by_id")
        ),
        _normalized("identifier"),
        _normalized("name", optional=True),
        _normalized("floor_label", optional=True),
        _ck("description_not_blank", "description IS NULL OR char_length(btrim(description)) > 0"),
        _ck("bedrooms_non_negative", "bedrooms >= 0"),
        _ck("bathrooms_half_units", "bathrooms >= 0 AND bathrooms * 2 = floor(bathrooms * 2)"),
        _ck("capacity_non_negative", "capacity >= 0"),
        _ck("floor_area_non_negative", "floor_area >= 0"),
        _ck("area_unit_matches_area", "(area_unit IS NULL) = (floor_area IS NULL)"),
        _ck(
            "internal_notes_not_blank",
            "internal_notes IS NULL OR char_length(btrim(internal_notes)) > 0",
        ),
        _ck("archived_by_needs_date", "archived_by_id IS NULL OR archived_at IS NOT NULL"),
        _ck("version_positive", "version >= 1"),
        _ck("area_unit", _one_of("area_unit", AREA_UNITS)),
        _ck("furnished_state", _one_of("furnished_state", FURNISHED_STATES)),
        _ck("unit_status", _one_of("status", UNIT_STATUSES)),
    )
    op.create_index(
        "uq_units_current_identifier",
        "units",
        ["property_id", "identifier_key"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_index("ix_units_property_ordering", "units", ["property_id", "identifier_key", "id"])
    op.create_index("ix_units_property_subtype_id", "units", ["property_subtype_id"])
    op.create_index("ix_units_status", "units", ["status"])

    op.create_table(
        "unit_amenities",
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("amenity_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("unit_id", "amenity_id", name=op.f("pk_unit_amenities")),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["units.id"],
            name=op.f("fk_unit_amenities_unit_id_units"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["amenity_id"],
            ["amenities.id"],
            name=op.f("fk_unit_amenities_amenity_id_amenities"),
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_unit_amenities_amenity_id", "unit_amenities", ["amenity_id"])


def downgrade() -> None:
    op.drop_table("unit_amenities")
    op.drop_table("units")
    op.drop_constraint(op.f("ck_properties_management_mode"), "properties", type_="check")
    op.drop_column("properties", "management_mode")
