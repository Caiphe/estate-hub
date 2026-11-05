"""Create contacts and property ownership links.

Revision ID: 20261104_0004
Revises: 20261104_0003
Create Date: 2026-11-04

Values below are copied, not imported, so this revision never changes when application
code changes later.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261104_0004"
down_revision: str | None = "20261104_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTACT_KINDS = ("person", "organization")
CONTACT_STATUSES = ("active", "archived")
TELEPHONE_PATTERN = r"^\+?[0-9]{6,15}$"
ADDRESS_COLUMNS = (
    "address_line_1",
    "address_line_2",
    "locality",
    "region",
    "postal_code",
    "country_code",
)


def _one_of(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _ck(table: str, name: str, rule: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(rule, name=op.f(f"ck_{table}_{name}"))


def _normalized(column: str, *, optional: bool = False) -> sa.CheckConstraint:
    rule = f"char_length({column}) > 0 AND {column} = btrim({column}) AND {column} !~ '\\s\\s'"
    if optional:
        rule = f"{column} IS NULL OR ({rule})"
    return _ck("contacts", f"{column}_normalized", rule)


def _user_fks(table: str) -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(
            [column], ["users.id"], name=op.f(f"fk_{table}_{column}_users"), ondelete="SET NULL"
        )
        for column in ("created_by_id", "updated_by_id", "archived_by_id")
    ]


def _audit_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    address_absent = " AND ".join(f"{column} IS NULL" for column in ADDRESS_COLUMNS)
    op.create_table(
        "contacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("organization_name", sa.String(200), nullable=True),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("telephone", sa.String(16), nullable=True),
        sa.Column("alternative_telephone", sa.String(16), nullable=True),
        sa.Column("address_line_1", sa.String(200), nullable=True),
        sa.Column("address_line_2", sa.String(200), nullable=True),
        sa.Column("locality", sa.String(100), nullable=True),
        sa.Column("region", sa.String(100), nullable=True),
        sa.Column("postal_code", sa.String(20), nullable=True),
        sa.Column("country_code", sa.String(2), nullable=True),
        sa.Column("internal_notes", sa.String(10000), nullable=True),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contacts")),
        *_user_fks("contacts"),
        _normalized("display_name"),
        _normalized("organization_name", optional=True),
        _ck(
            "contacts",
            "organization_name_for_people",
            "kind = 'person' OR organization_name IS NULL",
        ),
        _ck("contacts", "email_normalized", "email = lower(btrim(email)) AND email LIKE '_%@_%'"),
        _ck("contacts", "telephone_format", f"telephone ~ '{TELEPHONE_PATTERN}'"),
        _ck(
            "contacts",
            "alternative_telephone_format",
            f"alternative_telephone ~ '{TELEPHONE_PATTERN}'",
        ),
        _ck(
            "contacts",
            "alternative_telephone_secondary",
            "alternative_telephone IS NULL OR "
            "(telephone IS NOT NULL AND alternative_telephone <> telephone)",
        ),
        _normalized("address_line_1", optional=True),
        _normalized("address_line_2", optional=True),
        _normalized("locality", optional=True),
        _normalized("region", optional=True),
        _ck(
            "contacts",
            "postal_code_normalized",
            "postal_code IS NULL OR (postal_code = upper(btrim(postal_code)) "
            "AND char_length(postal_code) > 0)",
        ),
        _ck("contacts", "country_code_format", "country_code ~ '^[A-Z]{2}$'"),
        _ck(
            "contacts",
            "address_complete",
            f"({address_absent}) OR (address_line_1 IS NOT NULL AND locality IS NOT NULL "
            "AND country_code IS NOT NULL)",
        ),
        _ck(
            "contacts",
            "has_contact_method",
            "email IS NOT NULL OR telephone IS NOT NULL OR address_line_1 IS NOT NULL",
        ),
        _ck(
            "contacts",
            "internal_notes_not_blank",
            "internal_notes IS NULL OR char_length(btrim(internal_notes)) > 0",
        ),
        _ck(
            "contacts",
            "archived_state_consistent",
            "(status = 'archived') = (archived_at IS NOT NULL)",
        ),
        _ck(
            "contacts",
            "archived_by_needs_date",
            "archived_by_id IS NULL OR archived_at IS NOT NULL",
        ),
        _ck("contacts", "version_positive", "version >= 1"),
        _ck("contacts", "contact_kind", _one_of("kind", CONTACT_KINDS)),
        _ck("contacts", "contact_status", _one_of("status", CONTACT_STATUSES)),
    )
    op.create_index("ix_contacts_status", "contacts", ["status"])
    op.create_index("ix_contacts_email", "contacts", ["email"])
    op.create_index("ix_contacts_telephone", "contacts", ["telephone"])
    op.create_index(
        "ix_contacts_search_trgm",
        "contacts",
        ["display_name", "organization_name", "email"],
        postgresql_using="gin",
        postgresql_ops={
            "display_name": "gin_trgm_ops",
            "organization_name": "gin_trgm_ops",
            "email": "gin_trgm_ops",
        },
    )

    op.create_table(
        "property_ownerships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("share_percentage", sa.Numeric(5, 2), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.String(2000), nullable=True),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_property_ownerships")),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_property_ownerships_property_id_properties"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name=op.f("fk_property_ownerships_contact_id_contacts"),
            ondelete="RESTRICT",
        ),
        *_user_fks("property_ownerships"),
        _ck(
            "property_ownerships",
            "share_percentage_range",
            "share_percentage > 0 AND share_percentage <= 100",
        ),
        _ck("property_ownerships", "dates_ordered", "end_date >= start_date"),
        _ck(
            "property_ownerships",
            "notes_not_blank",
            "notes IS NULL OR char_length(btrim(notes)) > 0",
        ),
        _ck(
            "property_ownerships",
            "archived_by_needs_date",
            "archived_by_id IS NULL OR archived_at IS NOT NULL",
        ),
    )
    op.create_index(
        "uq_property_ownerships_current_link",
        "property_ownerships",
        ["property_id", "contact_id"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_index("ix_property_ownerships_contact_id", "property_ownerships", ["contact_id"])


def downgrade() -> None:
    op.drop_table("property_ownerships")
    op.drop_table("contacts")
