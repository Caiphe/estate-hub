"""Staff property records: create, directory search, detail, update, archive, restore.

Permissions are checked before any record is loaded, so a caller without the route's
permission gets ``403`` whether or not the ID exists; a missing ID is ``404`` for
everyone who may call the route. ``DELETE`` archives; nothing here deletes a record.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, Request, Response, status

from app.auth.dependencies import ClockDep, CurrentIdentity, DbDep, require_permissions
from app.auth.permissions import Permission
from app.catalog.http import location, translated
from app.catalog.openapi import error_responses
from app.core.middleware import get_request_id
from app.core.pagination import Page
from app.properties.schemas import (
    PropertyCreate,
    PropertyDetail,
    PropertyListQuery,
    PropertySummary,
    PropertyUpdate,
)
from app.properties.service import PropertyService

router = APIRouter()


def get_property_service(db: DbDep, clock: ClockDep) -> PropertyService:
    return PropertyService(db, clock=clock)


ServiceDep = Annotated[PropertyService, Depends(get_property_service)]
Reader = Annotated[CurrentIdentity, Depends(require_permissions(Permission.PROPERTIES_READ))]
Creator = Annotated[CurrentIdentity, Depends(require_permissions(Permission.PROPERTIES_CREATE))]
Updater = Annotated[CurrentIdentity, Depends(require_permissions(Permission.PROPERTIES_UPDATE))]
Archiver = Annotated[CurrentIdentity, Depends(require_permissions(Permission.PROPERTIES_ARCHIVE))]

_ID = "00000000-0000-0000-0000-00000000000"
CREATE_EXAMPLES: dict[str, Any] = {
    "standalone": {
        "summary": "Standalone house",
        "description": "Managed as a whole: no units.",
        "value": {
            "name": "Rose Cottage",
            "property_type_id": f"{_ID}1",
            "property_subtype_id": f"{_ID}2",
            "status": "active",
            "address_line_1": "1 High Street",
            "locality": "Bath",
            "region": "Somerset",
            "postal_code": "BA1 1AA",
            "country_code": "GB",
            "latitude": "51.381072",
            "longitude": "-2.359910",
            "bedrooms": 3,
            "bathrooms": "1.5",
            "floor_area": "120.00",
            "area_unit": "square_metre",
            "amenity_ids": [f"{_ID}3"],
            "owners": [{"contact_id": f"{_ID}4", "share_percentage": "100.00"}],
        },
    },
    "multi_unit": {
        "summary": "Apartment building with units",
        "description": "Managed by unit; units are created in the same transaction.",
        "value": {
            "name": "Rose Court",
            "property_type_id": f"{_ID}1",
            "management_mode": "units",
            "address_line_1": "10 Park Road",
            "locality": "Bristol",
            "region": "Avon",
            "country_code": "GB",
            "floors": 4,
            "units": [
                {"identifier": "Flat 1", "property_subtype_id": f"{_ID}5", "bedrooms": 2},
                {"identifier": "Flat 2", "property_subtype_id": f"{_ID}5", "bedrooms": 1},
            ],
        },
    },
}


@router.get("", responses=error_responses(422), summary="List properties")
async def list_properties(
    query: Annotated[PropertyListQuery, Query()], identity: Reader, service: ServiceDep
) -> Page[PropertySummary]:
    """Multi-select filters repeat the parameter (`?status=active&status=draft`).
    `amenity_id` matches properties having every listed amenity. Archived properties
    appear only with `include_archived=true` (properties:archive). `q` also searches
    current owners' names for callers with property_ownership:read. Sorted by `sort`
    with the property ID as tie-breaker."""
    with translated():
        rows, total = await service.list_properties(identity.actor, query)
    return Page[PropertySummary](items=rows, total=total, limit=query.limit, offset=query.offset)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(409, 422),
    summary="Create a property",
)
async def create_property(
    payload: Annotated[PropertyCreate, Body(openapi_examples=CREATE_EXAMPLES)],
    request: Request,
    response: Response,
    identity: Creator,
    service: ServiceDep,
) -> PropertyDetail:
    """Creates the property and any initial amenities, owners, and units atomically.
    Initial owners need property_ownership:manage and units property_units:manage. The
    server sets `reference`, staff IDs, timestamps, and `version`."""
    with translated():
        detail = await service.create_property(
            identity.actor, payload, request_id=get_request_id(request)
        )
    response.headers["Location"] = location(request, "get_property", property_id=detail.id)
    return detail


@router.get("/{property_id}", responses=error_responses(404, 422), summary="Get a property")
async def get_property(
    property_id: uuid.UUID, identity: Reader, service: ServiceDep
) -> PropertyDetail:
    """Archived properties stay readable. `internal_notes` needs
    properties:read_internal and `owners` property_ownership:read; otherwise they are
    omitted."""
    with translated():
        return await service.get_property(identity.actor, property_id)


@router.patch(
    "/{property_id}",
    responses=error_responses(404, 409, 422),
    summary="Update a property",
)
async def update_property(
    property_id: uuid.UUID,
    payload: PropertyUpdate,
    request: Request,
    identity: Updater,
    service: ServiceDep,
) -> PropertyDetail:
    """Send the current `version`; an older one is `409 stale_version` and changes
    nothing. Omitted fields are unchanged and `null` clears an optional field.
    `amenity_ids` replaces the whole set. Owners and units have their own endpoints."""
    with translated():
        return await service.update_property(
            identity.actor, property_id, payload, request_id=get_request_id(request)
        )


@router.delete(
    "/{property_id}",
    responses=error_responses(404, 409, 422),
    summary="Archive a property",
)
async def archive_property(
    property_id: uuid.UUID, request: Request, identity: Archiver, service: ServiceDep
) -> PropertyDetail:
    """Archives instead of deleting. Units, owners, and files are kept unchanged; the
    property leaves normal lists. Idempotent."""
    with translated():
        return await service.archive_property(
            identity.actor, property_id, request_id=get_request_id(request)
        )


@router.post(
    "/{property_id}/restore",
    responses=error_responses(404, 409, 422),
    summary="Restore a property",
)
async def restore_property(
    property_id: uuid.UUID, request: Request, identity: Archiver, service: ServiceDep
) -> PropertyDetail:
    """Returns an archived property as `inactive`. Idempotent."""
    with translated():
        return await service.restore_property(
            identity.actor, property_id, request_id=get_request_id(request)
        )
