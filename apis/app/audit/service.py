import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.events import AuditEventCode
from app.audit.models import AuditEvent
from app.audit.schemas import AuditEventCreate


def record_audit_event(
    db: AsyncSession,
    code: AuditEventCode,
    *,
    actor_id: uuid.UUID | None,
    request_id: str | None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add an audit event to the caller's transaction. Never commits.

    Writing the event in the same transaction as the change means a rolled-back change
    leaves no event, and a committed change always has one. Metadata is validated so it
    cannot carry credentials.
    """
    event = AuditEventCreate(
        event_code=code,
        actor_id=actor_id,
        entity_type=entity_type,
        entity_id=entity_id,
        request_id=request_id,
        metadata=metadata or {},
    )
    row = AuditEvent(
        id=uuid.uuid4(),
        actor_id=event.actor_id,
        event_code=event.event_code,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        request_id=event.request_id,
        details=event.metadata,
    )
    db.add(row)
    return row
