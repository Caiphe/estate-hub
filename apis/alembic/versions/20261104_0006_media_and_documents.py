"""Create media assets and private documents.

Revision ID: 20261104_0006
Revises: 20261104_0005
Create Date: 2026-11-04

Values below are copied, not imported, so this revision never changes when application
code changes later. File bytes live in object storage; these tables hold metadata only.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261104_0006"
down_revision: str | None = "20261104_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")
DOCUMENT_TYPES = ("application/pdf", *IMAGE_TYPES)
DOCUMENT_CATEGORIES = (
    "title_deed",
    "sale_agreement",
    "lease",
    "certificate",
    "insurance",
    "inspection_report",
    "floor_plan",
    "invoice",
    "other",
)
STORAGE_KEY_PATTERN = r"^(media|documents)/[0-9a-f]{2}/[0-9a-f]{32}$"


def _one_of(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _stored_file(table: str, namespace: str, media_types: Sequence[str]) -> list[sa.SchemaItem]:
    """Columns and constraints shared by both tables."""

    def ck(name: str, rule: str) -> sa.CheckConstraint:
        return sa.CheckConstraint(rule, name=op.f(f"ck_{table}_{name}"))

    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=True),
        sa.Column("unit_id", sa.Uuid(), nullable=True),
        sa.Column("storage_key", sa.String(64), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("uploaded_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("storage_key", name=op.f(f"uq_{table}_storage_key")),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f(f"fk_{table}_property_id_properties"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"], ["units.id"], name=op.f(f"fk_{table}_unit_id_units"), ondelete="RESTRICT"
        ),
        *(
            sa.ForeignKeyConstraint(
                [column], ["users.id"], name=op.f(f"fk_{table}_{column}_users"), ondelete="SET NULL"
            )
            for column in ("uploaded_by_id", "updated_by_id", "archived_by_id")
        ),
        ck("one_parent", "num_nonnulls(property_id, unit_id) = 1"),
        ck("media_type_allowed", _one_of("media_type", sorted(media_types))),
        ck(
            "storage_key_format",
            f"storage_key ~ '{STORAGE_KEY_PATTERN}' AND storage_key LIKE '{namespace}/%'",
        ),
        ck("byte_size_positive", "byte_size > 0"),
        ck(
            "original_filename_safe",
            "char_length(original_filename) > 0 AND original_filename !~ '[/\\\\]'",
        ),
        ck("archived_by_needs_date", "archived_by_id IS NULL OR archived_at IS NOT NULL"),
    ]


def upgrade() -> None:
    op.create_table(
        "media_assets",
        *_stored_file("media_assets", "media", IMAGE_TYPES),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("alt_text", sa.String(500), nullable=True),
        sa.Column("is_cover", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.CheckConstraint(
            "width > 0 AND height > 0", name=op.f("ck_media_assets_dimensions_positive")
        ),
        sa.CheckConstraint(
            "display_order >= 0", name=op.f("ck_media_assets_display_order_non_negative")
        ),
        sa.CheckConstraint(
            "alt_text IS NULL OR char_length(btrim(alt_text)) > 0",
            name=op.f("ck_media_assets_alt_text_not_blank"),
        ),
        sa.CheckConstraint(
            "NOT (is_cover AND archived_at IS NOT NULL)",
            name=op.f("ck_media_assets_cover_not_archived"),
        ),
    )
    for parent in ("property", "unit"):
        op.create_index(
            f"uq_media_assets_{parent}_cover",
            "media_assets",
            [f"{parent}_id"],
            unique=True,
            postgresql_where=sa.text(f"is_cover AND {parent}_id IS NOT NULL"),
        )
        op.create_index(
            f"ix_media_assets_{parent}_order",
            "media_assets",
            [f"{parent}_id", "display_order", "created_at", "id"],
            postgresql_where=sa.text(f"archived_at IS NULL AND {parent}_id IS NOT NULL"),
        )

    op.create_table(
        "documents",
        *_stored_file("documents", "documents", DOCUMENT_TYPES),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            _one_of("category", DOCUMENT_CATEGORIES), name=op.f("ck_documents_document_category")
        ),
        sa.CheckConstraint(
            "char_length(title) > 0 AND title = btrim(title) AND title !~ '\\s\\s'",
            name=op.f("ck_documents_title_normalized"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_documents_version_positive")),
    )
    for parent in ("property", "unit"):
        op.create_index(
            f"ix_documents_{parent}",
            "documents",
            [f"{parent}_id", "created_at", "id"],
            postgresql_where=sa.text(f"{parent}_id IS NOT NULL"),
        )
    op.create_index(
        "ix_documents_expiry_date",
        "documents",
        ["expiry_date"],
        postgresql_where=sa.text("expiry_date IS NOT NULL"),
    )


def downgrade() -> None:
    # Stored objects are not touched: they remain on the volume for recovery.
    op.drop_table("documents")
    op.drop_table("media_assets")
