from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.audit.repository import list_audit_events
from app.audit.schemas import AuditEventPublic, AuditEventQuery
from app.auth.dependencies import CurrentIdentity, DbDep, require_permissions
from app.auth.permissions import Permission
from app.core.errors import ErrorResponse
from app.core.pagination import Page

router = APIRouter()

AuditReader = Annotated[CurrentIdentity, Depends(require_permissions(Permission.AUDIT_READ))]


@router.get(
    "",
    response_model=Page[AuditEventPublic],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
    summary="List audit events",
)
async def list_events(
    query: Annotated[AuditEventQuery, Query()], identity: AuditReader, db: DbDep
) -> Page[AuditEventPublic]:
    """Newest first, with the event ID as tie-breaker. Filter by `event_code`, `actor_id`,
    `entity_type`, `entity_id`, and the half-open range `[occurred_from, occurred_to)`.
    Read-only: the application never updates or deletes audit events."""
    events, total = await list_audit_events(db, identity.actor, query)
    return Page[AuditEventPublic](
        items=[AuditEventPublic.model_validate(event) for event in events],
        total=total,
        limit=query.limit,
        offset=query.offset,
    )
