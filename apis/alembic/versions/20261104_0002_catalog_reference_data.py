"""Create property-catalog reference data and seed initial classifications.

Revision ID: 20261104_0002
Revises: 20261103_0001
Create Date: 2026-11-04

Values below are copied, not imported, so this revision never changes when application
code changes later. Seeded rows are ordinary, editable reference data.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Insert

from alembic import op

revision: str = "20261104_0002"
down_revision: str | None = "20261103_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME_MAX = 100
DESCRIPTION_MAX = 500
CATEGORY_MAX = 50
DISPLAY_ORDER_MAX = 10_000

# Physical classifications only. Residential, holiday, student, and commercial *rental
# categories* belong to listings (prompt 03); a villa or cottage can be listed for
# holidays without a "holiday" property type.
# (type slug, type name, description, ((subtype slug, subtype name), ...))
PROPERTY_TYPES: tuple[tuple[str, str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "residential",
        "Residential",
        "Homes for long stays or holiday letting.",
        (
            ("house", "House"),
            ("apartment", "Apartment"),
            ("villa", "Villa"),
            ("townhouse", "Townhouse"),
            ("cottage", "Cottage"),
            ("studio", "Studio"),
        ),
    ),
    (
        "student",
        "Student accommodation",
        "Purpose-built or shared accommodation let to students.",
        (
            ("student-residence", "Student residence"),
            ("student-room", "Student room"),
            ("shared-house", "Shared house"),
        ),
    ),
    (
        "commercial",
        "Commercial",
        "Premises used for business.",
        (
            ("office", "Office"),
            ("shop", "Shop"),
            ("warehouse", "Warehouse"),
            ("industrial-unit", "Industrial unit"),
        ),
    ),
    (
        "land",
        "Land",
        "Undeveloped or development land.",
        (
            ("residential-plot", "Residential plot"),
            ("commercial-plot", "Commercial plot"),
            ("agricultural-land", "Agricultural land"),
        ),
    ),
)

# (slug, name, category)
AMENITIES: tuple[tuple[str, str, str], ...] = (
    ("parking", "Parking", "parking"),
    ("garage", "Garage", "parking"),
    ("garden", "Garden", "outdoor"),
    ("balcony", "Balcony", "outdoor"),
    ("terrace", "Terrace", "outdoor"),
    ("swimming-pool", "Swimming pool", "outdoor"),
    ("elevator", "Elevator", "building"),
    ("air-conditioning", "Air conditioning", "comfort"),
    ("central-heating", "Central heating", "comfort"),
    ("internet", "Internet", "utilities"),
    ("laundry", "Laundry", "utilities"),
    ("wheelchair-access", "Wheelchair access", "accessibility"),
    ("security-system", "Security system", "security"),
    ("gated-access", "Gated access", "security"),
)


def seed_id(kind: str, slug: str) -> str:
    """Identical IDs in every environment, like the role seed."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"urn:estatehub:{kind}:{slug}"))


_property_types = sa.table(
    "property_types",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("description", sa.String()),
    sa.column("display_order", sa.Integer()),
)
_property_subtypes = sa.table(
    "property_subtypes",
    sa.column("id", sa.Uuid()),
    sa.column("property_type_id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("display_order", sa.Integer()),
)
_amenities = sa.table(
    "amenities",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("category", sa.String()),
    sa.column("display_order", sa.Integer()),
)


def seed_statements() -> list[Insert]:
    """Idempotent inserts. Re-running them skips any row whose ID or name already exists,
    so administrator edits, renames, and disabled rows are never overwritten."""
    types = [
        {
            "id": seed_id("property-type", slug),
            "name": name,
            "description": description,
            "display_order": (index + 1) * 10,
        }
        for index, (slug, name, description, _) in enumerate(PROPERTY_TYPES)
    ]
    subtypes = [
        {
            "id": seed_id("property-subtype", f"{type_slug}/{slug}"),
            "property_type_id": seed_id("property-type", type_slug),
            "name": name,
            "display_order": (index + 1) * 10,
        }
        for type_slug, _, _, children in PROPERTY_TYPES
        for index, (slug, name) in enumerate(children)
    ]
    amenities = [
        {
            "id": seed_id("amenity", slug),
            "name": name,
            "category": category,
            "display_order": (index + 1) * 10,
        }
        for index, (slug, name, category) in enumerate(AMENITIES)
    ]
    return [
        postgresql.insert(_property_types).values(types).on_conflict_do_nothing(),
        postgresql.insert(_property_subtypes).values(subtypes).on_conflict_do_nothing(),
        postgresql.insert(_amenities).values(amenities).on_conflict_do_nothing(),
    ]


def _reference_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(NAME_MAX), nullable=False),
        sa.Column(
            "name_key",
            sa.String(NAME_MAX),
            sa.Computed("lower(name)", persisted=True),
            nullable=False,
        ),
        sa.Column("description", sa.String(DESCRIPTION_MAX), nullable=True),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _reference_constraints(table: str) -> list[sa.Constraint]:
    return [
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=f"fk_{table}_created_by_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name=f"fk_{table}_updated_by_id_users",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("char_length(name) > 0", name=op.f(f"ck_{table}_name_not_blank")),
        sa.CheckConstraint(
            r"name = btrim(name) AND name !~ '\s\s'", name=op.f(f"ck_{table}_name_normalized")
        ),
        sa.CheckConstraint(
            "description IS NULL OR char_length(btrim(description)) > 0",
            name=op.f(f"ck_{table}_description_not_blank"),
        ),
        sa.CheckConstraint(
            f"display_order BETWEEN 0 AND {DISPLAY_ORDER_MAX}",
            name=op.f(f"ck_{table}_display_order_range"),
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "property_types",
        *_reference_columns(),
        *_reference_constraints("property_types"),
        sa.UniqueConstraint("name_key", name="uq_property_types_name_key"),
    )
    op.create_index(
        "ix_property_types_ordering", "property_types", ["display_order", "name_key", "id"]
    )

    op.create_table(
        "property_subtypes",
        *_reference_columns(),
        sa.Column("property_type_id", sa.Uuid(), nullable=False),
        *_reference_constraints("property_subtypes"),
        sa.ForeignKeyConstraint(
            ["property_type_id"],
            ["property_types.id"],
            name="fk_property_subtypes_property_type_id_property_types",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "property_type_id", "name_key", name="uq_property_subtypes_property_type_id_name_key"
        ),
        sa.UniqueConstraint(
            "property_type_id", "id", name="uq_property_subtypes_property_type_id_id"
        ),
    )
    op.create_index(
        "ix_property_subtypes_ordering",
        "property_subtypes",
        ["property_type_id", "display_order", "name_key", "id"],
    )

    op.create_table(
        "amenities",
        *_reference_columns(),
        sa.Column("category", sa.String(CATEGORY_MAX), nullable=True),
        *_reference_constraints("amenities"),
        sa.UniqueConstraint("name_key", name="uq_amenities_name_key"),
        sa.CheckConstraint(
            "category ~ '^[a-z][a-z_]*$'", name=op.f("ck_amenities_category_format")
        ),
    )
    op.create_index("ix_amenities_ordering", "amenities", ["display_order", "name_key", "id"])

    for statement in seed_statements():
        op.execute(statement)


def downgrade() -> None:
    # Reference data has no dependents yet. Later revisions add foreign keys to these
    # tables and must be downgraded first, which Alembic's ordering guarantees.
    op.drop_table("amenities")
    op.drop_table("property_subtypes")
    op.drop_table("property_types")
