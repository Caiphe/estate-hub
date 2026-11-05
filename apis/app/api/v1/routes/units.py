"""Units of a property. A unit requested under another property is not found."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.auth.dependencies import ClockDep, CurrentIdentity, DbDep, require_permissions
from app.auth.permissions import Permission
from app.catalog.http import location, translated
from app.catalog.openapi import error_responses
from app.core.middleware import get_request_id
from app.core.pagination import Page
from app.properties.schemas import ArchivedQuery, UnitCreate, UnitDetail, UnitUpdate, unit_view
from app.properties.units import UnitService

router = APIRouter()


def get_unit_service(db: DbDep, clock: ClockDep) -> UnitService:
    return UnitService(db, clock=clock)


ServiceDep = Annotated[UnitService, Depends(get_unit_service)]
Reader = Annotated[CurrentIdentity, Depends(require_permissions(Permission.PROPERTIES_READ))]
Manager = Annotated[CurrentIdentity, Depends(require_permissions(Permission.PROPERTY_UNITS_MANAGE))]


@router.get("/{property_id}/units", responses=error_responses(404, 422), summary="List units")
async def list_units(
    property_id: uuid.UUID,
    query: Annotated[ArchivedQuery, Query()],
    identity: Reader,
    service: ServiceDep,
) -> Page[UnitDetail]:
    """Active units ordered by identifier, then ID. Units of an archived property, and
    archived units, appear only with `include_archived=true`."""
    with translated():
        units = await service.list_units(
            identity.actor,
            property_id,
            include_archived=query.include_archived,
            limit=query.limit,
            offset=query.offset,
        )
        total = await service.count_units(
            identity.actor, property_id, include_archived=query.include_archived
        )
    return Page[UnitDetail](
        items=[unit_view(identity.actor, unit) for unit in units],
        total=total,
        limit=query.limit,
        offset=query.offset,
    )


@router.post(
    "/{property_id}/units",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(404, 409, 422),
    summary="Create a unit",
)
async def create_unit(
    property_id: uuid.UUID,
    payload: UnitCreate,
    request: Request,
    response: Response,
    identity: Manager,
    service: ServiceDep,
) -> UnitDetail:
    """Refused for a property managed as a whole (`409 conflict`) and for an identifier
    already used by an active unit of the property, ignoring case
    (`409 duplicate_reference`)."""
    with translated():
        unit = await service.create_unit(
            identity.actor, property_id, payload, request_id=get_request_id(request)
        )
    response.headers["Location"] = location(
        request, "get_unit", property_id=property_id, unit_id=unit.id
    )
    return unit_view(identity.actor, unit)


@router.get(
    "/{property_id}/units/{unit_id}", responses=error_responses(404, 422), summary="Get a unit"
)
async def get_unit(
    property_id: uuid.UUID, unit_id: uuid.UUID, identity: Reader, service: ServiceDep
) -> UnitDetail:
    with translated():
        return unit_view(
            identity.actor, await service.get_unit(identity.actor, property_id, unit_id)
        )


@router.patch(
    "/{property_id}/units/{unit_id}",
    responses=error_responses(404, 409, 422),
    summary="Update a unit",
)
async def update_unit(
    property_id: uuid.UUID,
    unit_id: uuid.UUID,
    payload: UnitUpdate,
    request: Request,
    identity: Manager,
    service: ServiceDep,
) -> UnitDetail:
    """Send the current `version`. A unit never moves to another property."""
    with translated():
        unit = await service.update_unit(
            identity.actor, property_id, unit_id, payload, request_id=get_request_id(request)
        )
    return unit_view(identity.actor, unit)


@router.delete(
    "/{property_id}/units/{unit_id}",
    responses=error_responses(404, 409, 422),
    summary="Archive a unit",
)
async def archive_unit(
    property_id: uuid.UUID,
    unit_id: uuid.UUID,
    request: Request,
    identity: Manager,
    service: ServiceDep,
) -> UnitDetail:
    """Archives, never deletes; its identifier becomes free for a new unit. Idempotent."""
    with translated():
        unit = await service.archive_unit(
            identity.actor, property_id, unit_id, request_id=get_request_id(request)
        )
    return unit_view(identity.actor, unit)


@router.post(
    "/{property_id}/units/{unit_id}/restore",
    responses=error_responses(404, 409, 422),
    summary="Restore a unit",
)
async def restore_unit(
    property_id: uuid.UUID,
    unit_id: uuid.UUID,
    request: Request,
    identity: Manager,
    service: ServiceDep,
) -> UnitDetail:
    """Refused while another active unit uses the identifier, or while the property is
    managed as a whole. Idempotent."""
    with translated():
        unit = await service.restore_unit(
            identity.actor, property_id, unit_id, request_id=get_request_id(request)
        )
    return unit_view(identity.actor, unit)
