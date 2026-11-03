from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.audit.schemas import AuditEventQuery
from app.auth.permissions import Permission
from app.auth.policy import Actor, require_permissions


async def list_audit_events(
    db: AsyncSession, actor: Actor, query: AuditEventQuery
) -> tuple[list[AuditEvent], int]:
    """Read-only access to the audit log. Requires ``audit:read``."""
    require_permissions(actor, Permission.AUDIT_READ)
    conditions: list[ColumnElement[bool]] = []
    if query.event_code is not None:
        conditions.append(AuditEvent.event_code == query.event_code)
    if query.actor_id is not None:
        conditions.append(AuditEvent.actor_id == query.actor_id)
    if query.entity_type is not None:
        conditions.append(AuditEvent.entity_type == query.entity_type)
    if query.entity_id is not None:
        conditions.append(AuditEvent.entity_id == query.entity_id)
    if query.occurred_from is not None:
        conditions.append(AuditEvent.occurred_at >= query.occurred_from)
    if query.occurred_to is not None:
        conditions.append(AuditEvent.occurred_at < query.occurred_to)

    total = await db.scalar(select(func.count()).select_from(AuditEvent).where(*conditions))
    events = await db.scalars(
        select(AuditEvent)
        .where(*conditions)
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        .limit(query.limit)
        .offset(query.offset)
    )
    return list(events), int(total or 0)
