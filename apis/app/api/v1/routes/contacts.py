"""Contacts: people and organizations acting as owners (and later sellers, buyers, tenants,
or prospects). Every response is private staff data."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.auth.dependencies import ClockDep, CurrentIdentity, DbDep, require_permissions
from app.auth.permissions import Permission
from app.catalog.http import location, translated
from app.catalog.openapi import error_responses
from app.contacts.schemas import (
    ContactCreate,
    ContactDetail,
    ContactListQuery,
    ContactSummary,
    ContactUpdate,
    contact_view,
)
from app.contacts.service import ContactService
from app.core.middleware import get_request_id
from app.core.pagination import Page

router = APIRouter()


def get_contact_service(db: DbDep, clock: ClockDep) -> ContactService:
    return ContactService(db, clock=clock)


ServiceDep = Annotated[ContactService, Depends(get_contact_service)]
Reader = Annotated[CurrentIdentity, Depends(require_permissions(Permission.CONTACTS_READ))]
Manager = Annotated[CurrentIdentity, Depends(require_permissions(Permission.CONTACTS_MANAGE))]


@router.get("", responses=error_responses(422), summary="List contacts")
async def list_contacts(
    query: Annotated[ContactListQuery, Query()], identity: Reader, service: ServiceDep
) -> Page[ContactSummary]:
    """Search `q` (name, organization, email, telephone digits), filter by `kind`, and
    include archived contacts with `include_archived`. The contact ID breaks sort ties."""
    with translated():
        rows, total = await service.list_contacts(identity.actor, query)
    return Page[ContactSummary](
        items=[ContactSummary.model_validate(row) for row in rows],
        total=total,
        limit=query.limit,
        offset=query.offset,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(422),
    summary="Create a contact",
)
async def create_contact(
    payload: ContactCreate,
    request: Request,
    response: Response,
    identity: Manager,
    service: ServiceDep,
) -> ContactDetail:
    with translated():
        row = await service.create_contact(
            identity.actor, payload, request_id=get_request_id(request)
        )
    response.headers["Location"] = location(request, "get_contact", contact_id=row.id)
    return contact_view(identity.actor, row)


@router.get("/{contact_id}", responses=error_responses(404, 422), summary="Get a contact")
async def get_contact(
    contact_id: uuid.UUID, identity: Reader, service: ServiceDep
) -> ContactDetail:
    """`internal_notes` appears only with properties:read_internal."""
    with translated():
        return contact_view(identity.actor, await service.get_contact(identity.actor, contact_id))


@router.patch("/{contact_id}", responses=error_responses(404, 409, 422), summary="Update a contact")
async def update_contact(
    contact_id: uuid.UUID,
    payload: ContactUpdate,
    request: Request,
    identity: Manager,
    service: ServiceDep,
) -> ContactDetail:
    """Send the current `version`; an older one is `409 stale_version`. `null` clears a
    field; the result must still have an email, a telephone, or an address."""
    with translated():
        row = await service.update_contact(
            identity.actor, contact_id, payload, request_id=get_request_id(request)
        )
    return contact_view(identity.actor, row)


@router.delete(
    "/{contact_id}", responses=error_responses(404, 409, 422), summary="Archive a contact"
)
async def archive_contact(
    contact_id: uuid.UUID, request: Request, identity: Manager, service: ServiceDep
) -> ContactDetail:
    """Archives, never deletes. Refused (`409 dependency_conflict`) while the contact
    owns a property. Idempotent."""
    with translated():
        row = await service.archive_contact(
            identity.actor, contact_id, request_id=get_request_id(request)
        )
    return contact_view(identity.actor, row)


@router.post(
    "/{contact_id}/restore", responses=error_responses(404, 422), summary="Restore a contact"
)
async def restore_contact(
    contact_id: uuid.UUID, request: Request, identity: Manager, service: ServiceDep
) -> ContactDetail:
    with translated():
        row = await service.restore_contact(
            identity.actor, contact_id, request_id=get_request_id(request)
        )
    return contact_view(identity.actor, row)
