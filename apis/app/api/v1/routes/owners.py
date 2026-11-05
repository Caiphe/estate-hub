"""Owners of a property: links to contacts with optional shares and dates.

Contact details inside each link appear only with ``contacts:read``, and link notes only
with ``properties:read_internal``.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.auth.dependencies import ClockDep, CurrentIdentity, DbDep, require_permissions
from app.auth.permissions import Permission
from app.catalog.http import location, translated
from app.catalog.openapi import error_responses
from app.core.middleware import get_request_id
from app.properties.ownership import OwnershipService
from app.properties.schemas import (
    ArchivedQuery,
    OwnershipCreate,
    OwnershipPublic,
    OwnershipUpdate,
    PropertyOwners,
    owners_view,
    ownership_view,
)

router = APIRouter()


def get_ownership_service(db: DbDep, clock: ClockDep) -> OwnershipService:
    return OwnershipService(db, clock=clock)


ServiceDep = Annotated[OwnershipService, Depends(get_ownership_service)]
Reader = Annotated[
    CurrentIdentity, Depends(require_permissions(Permission.PROPERTY_OWNERSHIP_READ))
]
Manager = Annotated[
    CurrentIdentity, Depends(require_permissions(Permission.PROPERTY_OWNERSHIP_MANAGE))
]


@router.get(
    "/{property_id}/owners", responses=error_responses(404, 422), summary="List property owners"
)
async def list_owners(
    property_id: uuid.UUID,
    query: Annotated[ArchivedQuery, Query()],
    identity: Reader,
    service: ServiceDep,
) -> PropertyOwners:
    """Current links, plus ended ones with `include_archived=true`. `shares` summarizes
    today's known shares; `complete` is true only when every share is known and they
    total 100."""
    with translated():
        links, summary = await service.list_owners(
            identity.actor,
            property_id,
            include_ended=query.include_archived,
            limit=query.limit,
            offset=query.offset,
        )
        total = await service.count_owners(
            identity.actor, property_id, include_ended=query.include_archived
        )
    return owners_view(
        identity.actor, links, summary, total=total, limit=query.limit, offset=query.offset
    )


@router.post(
    "/{property_id}/owners",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(404, 409, 422),
    summary="Add a property owner",
)
async def add_owner(
    property_id: uuid.UUID,
    payload: OwnershipCreate,
    request: Request,
    response: Response,
    identity: Manager,
    service: ServiceDep,
) -> OwnershipPublic:
    """Refused when known shares in force on any day would exceed 100%
    (`409 conflict`), or when the contact already owns the property
    (`409 duplicate_reference`)."""
    with translated():
        link = await service.add_owner(
            identity.actor, property_id, payload, request_id=get_request_id(request)
        )
    response.headers["Location"] = location(
        request, "get_owner", property_id=property_id, ownership_id=link.id
    )
    return ownership_view(identity.actor, link)


@router.get(
    "/{property_id}/owners/{ownership_id}",
    responses=error_responses(404, 422),
    summary="Get a property ownership",
)
async def get_owner(
    property_id: uuid.UUID, ownership_id: uuid.UUID, identity: Reader, service: ServiceDep
) -> OwnershipPublic:
    with translated():
        link = await service.get_owner(identity.actor, property_id, ownership_id)
    return ownership_view(identity.actor, link)


@router.patch(
    "/{property_id}/owners/{ownership_id}",
    responses=error_responses(404, 409, 422),
    summary="Update a property ownership",
)
async def update_owner(
    property_id: uuid.UUID,
    ownership_id: uuid.UUID,
    payload: OwnershipUpdate,
    request: Request,
    identity: Manager,
    service: ServiceDep,
) -> OwnershipPublic:
    with translated():
        link = await service.update_owner(
            identity.actor,
            property_id,
            ownership_id,
            payload,
            request_id=get_request_id(request),
        )
    return ownership_view(identity.actor, link)


@router.delete(
    "/{property_id}/owners/{ownership_id}",
    responses=error_responses(404, 409, 422),
    summary="End a property ownership",
)
async def end_owner(
    property_id: uuid.UUID,
    ownership_id: uuid.UUID,
    request: Request,
    identity: Manager,
    service: ServiceDep,
) -> OwnershipPublic:
    """Ends the link and keeps it as history. Final and idempotent."""
    with translated():
        link = await service.end_owner(
            identity.actor, property_id, ownership_id, request_id=get_request_id(request)
        )
    return ownership_view(identity.actor, link)
