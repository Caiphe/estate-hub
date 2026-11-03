import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, Mapper, mapped_column, validates

from app.audit.metadata import validate_audit_metadata
from app.core.database import Base

EVENT_CODE_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"
EVENT_CODE_MAX_LENGTH = 100
ENTITY_TYPE_MAX_LENGTH = 50
REQUEST_ID_MAX_LENGTH = 128


class AuditEvent(Base):
    """An immutable record of a security-sensitive or important business action.

    The application only inserts audit events. Updates and deletes are refused at the ORM
    level.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(f"event_code ~ '{EVENT_CODE_PATTERN}'", name="event_code_format"),
        CheckConstraint(
            "(entity_type IS NULL) = (entity_id IS NULL)", name="entity_reference_complete"
        ),
        Index("ix_audit_events_occurred_at", "occurred_at"),
        Index("ix_audit_events_actor_occurred_at", "actor_id", "occurred_at"),
        Index("ix_audit_events_entity_occurred_at", "entity_type", "entity_id", "occurred_at"),
        Index("ix_audit_events_event_code_occurred_at", "event_code", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Kept when the actor is deleted so history survives; NULL means the system acted.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    event_code: Mapped[str] = mapped_column(String(EVENT_CODE_MAX_LENGTH))
    entity_type: Mapped[str | None] = mapped_column(String(ENTITY_TYPE_MAX_LENGTH))
    entity_id: Mapped[uuid.UUID | None]
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())
    request_id: Mapped[str | None] = mapped_column(String(REQUEST_ID_MAX_LENGTH))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")

    @validates("details")
    def _safe_details(self, _: str, details: dict[str, Any]) -> dict[str, Any]:
        return validate_audit_metadata(details)


class AuditEventImmutableError(RuntimeError):
    pass


def _refuse_change(_: Mapper[AuditEvent], __: Connection, target: AuditEvent) -> None:
    raise AuditEventImmutableError(f"Audit event {target.id} is append-only.")


event.listen(AuditEvent, "before_update", _refuse_change)
event.listen(AuditEvent, "before_delete", _refuse_change)
