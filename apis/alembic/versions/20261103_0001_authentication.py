"""Create authentication tables and seed the initial roles.

Revision ID: 20261103_0001
Revises:
Create Date: 2026-11-03

Values below are copied, not imported, so this revision never changes when application
code changes later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261103_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USER_STATUSES = ("active", "disabled")
REVOCATION_REASONS = (
    "logout",
    "rotated",
    "reuse_detected",
    "password_changed",
    "user_disabled",
    "roles_changed",
    "admin_revoked",
)
# Role IDs are uuid5(NAMESPACE_URL, "urn:estatehub:role:<code>"), so every environment
# gets identical rows. Permissions stay in application code, not in this table.
INITIAL_ROLES = (
    (
        "4fdee0ac-c6d6-518d-ac0d-2f9213cc3871",
        "administrator",
        "Administrator",
        "Full access, staff accounts, roles, reference data, and system configuration.",
    ),
    (
        "ac69b9ec-e7ee-57ba-ab9c-f1741c3ecae1",
        "manager",
        "Manager",
        "Properties, listings, deals, rentals, maintenance, reports, and approvals.",
    ),
    (
        "310c740e-80f6-53c6-a5cf-44594700712f",
        "agent",
        "Agent",
        "Assigned properties, listings, contacts, inquiries, viewings, offers, and deals.",
    ),
    (
        "2fbc4b04-270d-56a3-8d83-995753984b30",
        "accountant",
        "Accountant",
        "Payment records, rent schedules, expenses, financial reports, and read-only "
        "property context.",
    ),
)


def _one_of(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    roles = op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), server_default="", nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("code", name=op.f("uq_roles_code")),
        sa.CheckConstraint("code ~ '^[a-z][a-z_]*$'", name=op.f("ck_roles_code_format")),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_users_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name=op.f("fk_users_updated_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("email = lower(btrim(email))", name=op.f("ck_users_email_normalized")),
        sa.CheckConstraint(
            "char_length(btrim(full_name)) > 0", name=op.f("ck_users_full_name_not_blank")
        ),
        sa.CheckConstraint("token_version >= 0", name=op.f("ck_users_token_version_non_negative")),
        sa.CheckConstraint(_one_of("status", USER_STATUSES), name=op.f("ck_users_user_status")),
    )

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id", name=op.f("pk_user_roles")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_roles_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name=op.f("fk_user_roles_role_id_roles"), ondelete="RESTRICT"
        ),
    )
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])

    op.create_table(
        "refresh_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(32), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("client_ip_prefix", sa.String(50), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_sessions_token_hash")),
        sa.UniqueConstraint("parent_id", name=op.f("uq_refresh_sessions_parent_id")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["refresh_sessions.id"],
            name=op.f("fk_refresh_sessions_parent_id_refresh_sessions"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "expires_at > issued_at", name=op.f("ck_refresh_sessions_expires_after_issued")
        ),
        sa.CheckConstraint(
            "char_length(token_hash) = 64", name=op.f("ck_refresh_sessions_token_hash_length")
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revoked_reason IS NULL)",
            name=op.f("ck_refresh_sessions_revocation_complete"),
        ),
        sa.CheckConstraint(
            _one_of("revoked_reason", REVOCATION_REASONS),
            name=op.f("ck_refresh_sessions_refresh_session_revoked_reason"),
        ),
    )
    op.create_index("ix_refresh_sessions_user_id", "refresh_sessions", ["user_id"])
    op.create_index("ix_refresh_sessions_family_id", "refresh_sessions", ["family_id"])
    op.create_index(
        "ix_refresh_sessions_active_user_expiry",
        "refresh_sessions",
        ["user_id", "expires_at"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index("ix_refresh_sessions_expires_at", "refresh_sessions", ["expires_at"])
    op.create_index(
        "ix_refresh_sessions_revoked_at",
        "refresh_sessions",
        ["revoked_at"],
        postgresql_where=sa.text("revoked_at IS NOT NULL"),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("event_code", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("details", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_audit_events_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            r"event_code ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'",
            name=op.f("ck_audit_events_event_code_format"),
        ),
        sa.CheckConstraint(
            "(entity_type IS NULL) = (entity_id IS NULL)",
            name=op.f("ck_audit_events_entity_reference_complete"),
        ),
    )
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])
    op.create_index(
        "ix_audit_events_actor_occurred_at", "audit_events", ["actor_id", "occurred_at"]
    )
    op.create_index(
        "ix_audit_events_entity_occurred_at",
        "audit_events",
        ["entity_type", "entity_id", "occurred_at"],
    )
    op.create_index(
        "ix_audit_events_event_code_occurred_at", "audit_events", ["event_code", "occurred_at"]
    )

    # ON CONFLICT keeps the seed safe if a role row was ever created by other means.
    op.execute(
        postgresql.insert(roles)
        .values(
            [
                {"id": role_id, "code": code, "name": name, "description": description}
                for role_id, code, name, description in INITIAL_ROLES
            ]
        )
        .on_conflict_do_nothing(index_elements=["code"])
    )


def downgrade() -> None:
    # Dependents first. Dropping a table also drops its indexes and constraints.
    op.drop_table("audit_events")
    op.drop_table("refresh_sessions")
    op.drop_table("user_roles")
    op.drop_table("users")
    op.drop_table("roles")
