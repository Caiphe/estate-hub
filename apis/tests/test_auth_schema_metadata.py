"""Checks the declared schema that the next Alembic migration will create."""

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateIndex, CreateTable

from app.core.database import Base
from app.models import AuditEvent, RefreshSession, Role, User, user_roles

AUTH_TABLES = {"users", "roles", "user_roles", "refresh_sessions", "audit_events"}


def constraint_names(table_name: str, kind: type) -> set[str]:
    table = Base.metadata.tables[table_name]
    return {str(c.name) for c in table.constraints if isinstance(c, kind)}


def index_names(table_name: str) -> set[str]:
    return {str(index.name) for index in Base.metadata.tables[table_name].indexes}


def test_mappers_configure() -> None:
    configure_mappers()
    assert AUTH_TABLES <= set(Base.metadata.tables)
    assert {User, Role, RefreshSession, AuditEvent}


def test_every_table_compiles_for_postgresql() -> None:
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    for name in AUTH_TABLES:
        table = Base.metadata.tables[name]
        assert "CREATE TABLE" in str(CreateTable(table).compile(dialect=dialect))
        for index in table.indexes:
            str(CreateIndex(index).compile(dialect=dialect))


def test_every_constraint_and_index_is_named() -> None:
    for name in AUTH_TABLES:
        table = Base.metadata.tables[name]
        for constraint in table.constraints:
            assert constraint.name, constraint
        for index in table.indexes:
            assert index.name, index


def test_users_constraints() -> None:
    assert constraint_names("users", UniqueConstraint) == {"uq_users_email"}
    assert {
        "ck_users_email_normalized",
        "ck_users_full_name_not_blank",
        "ck_users_token_version_non_negative",
        "ck_users_user_status",
    } <= constraint_names("users", CheckConstraint)


def test_roles_and_membership_constraints() -> None:
    assert constraint_names("roles", UniqueConstraint) == {"uq_roles_code"}
    assert "ck_roles_code_format" in constraint_names("roles", CheckConstraint)
    # The composite primary key prevents duplicate role assignments.
    assert [c.name for c in user_roles.primary_key.columns] == ["user_id", "role_id"]
    assert index_names("user_roles") == {"ix_user_roles_role_id"}


def test_refresh_session_constraints_and_indexes() -> None:
    assert constraint_names("refresh_sessions", UniqueConstraint) == {
        "uq_refresh_sessions_token_hash",
        "uq_refresh_sessions_parent_id",
    }
    assert {
        "ck_refresh_sessions_expires_after_issued",
        "ck_refresh_sessions_token_hash_length",
        "ck_refresh_sessions_revocation_complete",
        "ck_refresh_sessions_refresh_session_revoked_reason",
    } <= constraint_names("refresh_sessions", CheckConstraint)
    assert index_names("refresh_sessions") == {
        "ix_refresh_sessions_user_id",
        "ix_refresh_sessions_family_id",
        "ix_refresh_sessions_active_user_expiry",
        "ix_refresh_sessions_expires_at",
        "ix_refresh_sessions_revoked_at",
    }
    active = next(
        index
        for index in Base.metadata.tables["refresh_sessions"].indexes
        if index.name == "ix_refresh_sessions_active_user_expiry"
    )
    assert isinstance(active, Index)
    assert str(active.dialect_options["postgresql"]["where"]) == "revoked_at IS NULL"


def test_audit_event_constraints_and_indexes() -> None:
    assert {
        "ck_audit_events_event_code_format",
        "ck_audit_events_entity_reference_complete",
    } <= constraint_names("audit_events", CheckConstraint)
    assert index_names("audit_events") == {
        "ix_audit_events_occurred_at",
        "ix_audit_events_actor_occurred_at",
        "ix_audit_events_entity_occurred_at",
        "ix_audit_events_event_code_occurred_at",
    }


def test_foreign_key_delete_behaviour() -> None:
    def on_delete(table: str, column: str) -> str | None:
        (foreign_key,) = Base.metadata.tables[table].columns[column].foreign_keys
        return foreign_key.ondelete

    assert on_delete("user_roles", "user_id") == "CASCADE"
    assert on_delete("user_roles", "role_id") == "RESTRICT"
    assert on_delete("refresh_sessions", "user_id") == "CASCADE"
    assert on_delete("refresh_sessions", "parent_id") == "SET NULL"
    assert on_delete("audit_events", "actor_id") == "SET NULL"
    assert on_delete("users", "created_by_id") == "SET NULL"


def test_timestamps_are_timezone_aware() -> None:
    for name in AUTH_TABLES:
        for column in Base.metadata.tables[name].columns:
            if column.name.endswith("_at"):
                assert column.type.timezone, f"{name}.{column.name}"  # type: ignore[attr-defined]
