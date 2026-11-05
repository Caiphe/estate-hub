"""Property types, subtypes, and amenities.

Reads need ``properties:read``: lists hold active records, which is what property forms
offer, and ``include_inactive=true`` adds disabled ones for administrators. Every write
needs ``reference_data:manage``. Records are disabled and reactivated, never deleted.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.auth.dependencies import CurrentIdentity, DbDep, require_permissions
from app.auth.permissions import Permission
from app.catalog.http import location, translated
from app.catalog.openapi import error_responses
from app.catalog.schemas import (
    AmenityCreate,
    AmenityRead,
    AmenityUpdate,
    PropertySubtypeRead,
    PropertyTypeRead,
    ReferenceCreate,
    ReferenceListQuery,
    ReferenceOrder,
    ReferenceUpdate,
)
from app.catalog.service import ReferenceDataService
from app.core.middleware import get_request_id

router = APIRouter()


def get_reference_service(db: DbDep) -> ReferenceDataService:
    return ReferenceDataService(db)


ServiceDep = Annotated[ReferenceDataService, Depends(get_reference_service)]
Reader = Annotated[CurrentIdentity, Depends(require_permissions(Permission.PROPERTIES_READ))]
Manager = Annotated[CurrentIdentity, Depends(require_permissions(Permission.REFERENCE_DATA_MANAGE))]


def _type(row: object) -> PropertyTypeRead:
    return PropertyTypeRead.model_validate(row)


# --- Property types ----------------------------------------------------------------------


@router.get(
    "/property-types",
    responses=error_responses(422),
    summary="List property types with subtypes",
)
async def list_property_types(
    query: Annotated[ReferenceListQuery, Query()], identity: Reader, service: ServiceDep
) -> list[PropertyTypeRead]:
    """Active types with their active subtypes, ordered by display order, then name.
    `include_inactive=true` (reference_data:manage) adds disabled records."""
    with translated():
        rows = await service.list_property_types(
            identity.actor, include_inactive=query.include_inactive
        )
    return [_type(row) for row in rows]


@router.post(
    "/property-types",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(409, 422),
    summary="Create a property type",
)
async def create_property_type(
    payload: ReferenceCreate,
    request: Request,
    response: Response,
    identity: Manager,
    service: ServiceDep,
) -> PropertyTypeRead:
    with translated():
        row = await service.create_property_type(
            identity.actor, payload, request_id=get_request_id(request)
        )
        detail = await service.get_property_type(identity.actor, row.id)
    response.headers["Location"] = location(request, "get_property_type", property_type_id=row.id)
    return _type(detail)


@router.put(
    "/property-types/order",
    responses=error_responses(422),
    summary="Reorder property types",
)
async def reorder_property_types(
    payload: ReferenceOrder, request: Request, identity: Manager, service: ServiceDep
) -> list[PropertyTypeRead]:
    """Send every type's ID, disabled included, in the new order."""
    with translated():
        await service.reorder_property_types(
            identity.actor, payload, request_id=get_request_id(request)
        )
        rows = await service.list_property_types(identity.actor, include_inactive=True)
    return [_type(row) for row in rows]


@router.get(
    "/property-types/{property_type_id}",
    responses=error_responses(404, 422),
    summary="Get a property type",
)
async def get_property_type(
    property_type_id: uuid.UUID, identity: Reader, service: ServiceDep
) -> PropertyTypeRead:
    """The type, active or not, with every subtype; `is_active` marks what can be newly
    chosen."""
    with translated():
        return _type(await service.get_property_type(identity.actor, property_type_id))


@router.patch(
    "/property-types/{property_type_id}",
    responses=error_responses(404, 409, 422),
    summary="Update a property type",
)
async def update_property_type(
    property_type_id: uuid.UUID,
    payload: ReferenceUpdate,
    request: Request,
    identity: Manager,
    service: ServiceDep,
) -> PropertyTypeRead:
    with translated():
        await service.update_property_type(
            identity.actor, property_type_id, payload, request_id=get_request_id(request)
        )
        return _type(await service.get_property_type(identity.actor, property_type_id))


async def _set_type_active(
    property_type_id: uuid.UUID,
    active: bool,
    request: Request,
    identity: CurrentIdentity,
    service: ReferenceDataService,
) -> PropertyTypeRead:
    with translated():
        await service.set_property_type_active(
            identity.actor, property_type_id, active, request_id=get_request_id(request)
        )
        return _type(await service.get_property_type(identity.actor, property_type_id))


@router.post(
    "/property-types/{property_type_id}/disable",
    responses=error_responses(404, 422),
    summary="Disable a property type",
)
async def disable_property_type(
    property_type_id: uuid.UUID, request: Request, identity: Manager, service: ServiceDep
) -> PropertyTypeRead:
    """Existing properties keep the type; it can no longer be newly chosen, and neither
    can its subtypes. Idempotent."""
    return await _set_type_active(property_type_id, False, request, identity, service)


@router.post(
    "/property-types/{property_type_id}/reactivate",
    responses=error_responses(404, 422),
    summary="Reactivate a property type",
)
async def reactivate_property_type(
    property_type_id: uuid.UUID, request: Request, identity: Manager, service: ServiceDep
) -> PropertyTypeRead:
    return await _set_type_active(property_type_id, True, request, identity, service)


# --- Property subtypes -------------------------------------------------------------------


@router.post(
    "/property-types/{property_type_id}/subtypes",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(404, 409, 422),
    summary="Create a property subtype",
)
async def create_subtype(
    property_type_id: uuid.UUID,
    payload: ReferenceCreate,
    request: Request,
    response: Response,
    identity: Manager,
    service: ServiceDep,
) -> PropertySubtypeRead:
    with translated():
        row = await service.create_subtype(
            identity.actor, property_type_id, payload, request_id=get_request_id(request)
        )
    response.headers["Location"] = location(
        request, "get_subtype", property_type_id=property_type_id, property_subtype_id=row.id
    )
    return PropertySubtypeRead.model_validate(row)


@router.put(
    "/property-types/{property_type_id}/subtypes/order",
    responses=error_responses(404, 422),
    summary="Reorder property subtypes",
)
async def reorder_subtypes(
    property_type_id: uuid.UUID,
    payload: ReferenceOrder,
    request: Request,
    identity: Manager,
    service: ServiceDep,
) -> list[PropertySubtypeRead]:
    """Send every subtype of this type, disabled included, in the new order."""
    with translated():
        rows = await service.reorder_subtypes(
            identity.actor, property_type_id, payload, request_id=get_request_id(request)
        )
    return [PropertySubtypeRead.model_validate(row) for row in rows]


@router.get(
    "/property-types/{property_type_id}/subtypes/{property_subtype_id}",
    responses=error_responses(404, 422),
    summary="Get a property subtype",
)
async def get_subtype(
    property_type_id: uuid.UUID,
    property_subtype_id: uuid.UUID,
    identity: Reader,
    service: ServiceDep,
) -> PropertySubtypeRead:
    """A subtype requested under another type is not found."""
    with translated():
        row = await service.get_subtype(identity.actor, property_type_id, property_subtype_id)
    return PropertySubtypeRead.model_validate(row)


@router.patch(
    "/property-types/{property_type_id}/subtypes/{property_subtype_id}",
    responses=error_responses(404, 409, 422),
    summary="Update a property subtype",
)
async def update_subtype(
    property_type_id: uuid.UUID,
    property_subtype_id: uuid.UUID,
    payload: ReferenceUpdate,
    request: Request,
    identity: Manager,
    service: ServiceDep,
) -> PropertySubtypeRead:
    with translated():
        row = await service.update_subtype(
            identity.actor,
            property_type_id,
            property_subtype_id,
            payload,
            request_id=get_request_id(request),
        )
    return PropertySubtypeRead.model_validate(row)


async def _set_subtype_active(
    property_type_id: uuid.UUID,
    property_subtype_id: uuid.UUID,
    active: bool,
    request: Request,
    identity: CurrentIdentity,
    service: ReferenceDataService,
) -> PropertySubtypeRead:
    with translated():
        row = await service.set_subtype_active(
            identity.actor,
            property_type_id,
            property_subtype_id,
            active,
            request_id=get_request_id(request),
        )
    return PropertySubtypeRead.model_validate(row)


@router.post(
    "/property-types/{property_type_id}/subtypes/{property_subtype_id}/disable",
    responses=error_responses(404, 422),
    summary="Disable a property subtype",
)
async def disable_subtype(
    property_type_id: uuid.UUID,
    property_subtype_id: uuid.UUID,
    request: Request,
    identity: Manager,
    service: ServiceDep,
) -> PropertySubtypeRead:
    return await _set_subtype_active(
        property_type_id, property_subtype_id, False, request, identity, service
    )


@router.post(
    "/property-types/{property_type_id}/subtypes/{property_subtype_id}/reactivate",
    responses=error_responses(404, 422),
    summary="Reactivate a property subtype",
)
async def reactivate_subtype(
    property_type_id: uuid.UUID,
    property_subtype_id: uuid.UUID,
    request: Request,
    identity: Manager,
    service: ServiceDep,
) -> PropertySubtypeRead:
    return await _set_subtype_active(
        property_type_id, property_subtype_id, True, request, identity, service
    )


# --- Amenities ---------------------------------------------------------------------------


@router.get("/amenities", responses=error_responses(422), summary="List amenities")
async def list_amenities(
    query: Annotated[ReferenceListQuery, Query()], identity: Reader, service: ServiceDep
) -> list[AmenityRead]:
    with translated():
        rows = await service.list_amenities(identity.actor, include_inactive=query.include_inactive)
    return [AmenityRead.model_validate(row) for row in rows]


@router.post(
    "/amenities",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(409, 422),
    summary="Create an amenity",
)
async def create_amenity(
    payload: AmenityCreate,
    request: Request,
    response: Response,
    identity: Manager,
    service: ServiceDep,
) -> AmenityRead:
    with translated():
        row = await service.create_amenity(
            identity.actor, payload, request_id=get_request_id(request)
        )
    response.headers["Location"] = location(request, "get_amenity", amenity_id=row.id)
    return AmenityRead.model_validate(row)


@router.put("/amenities/order", responses=error_responses(422), summary="Reorder amenities")
async def reorder_amenities(
    payload: ReferenceOrder, request: Request, identity: Manager, service: ServiceDep
) -> list[AmenityRead]:
    """Send every amenity's ID, disabled included, in the new order."""
    with translated():
        rows = await service.reorder_amenities(
            identity.actor, payload, request_id=get_request_id(request)
        )
    return [AmenityRead.model_validate(row) for row in rows]


@router.get(
    "/amenities/{amenity_id}", responses=error_responses(404, 422), summary="Get an amenity"
)
async def get_amenity(amenity_id: uuid.UUID, identity: Reader, service: ServiceDep) -> AmenityRead:
    with translated():
        return AmenityRead.model_validate(await service.get_amenity(identity.actor, amenity_id))


@router.patch(
    "/amenities/{amenity_id}",
    responses=error_responses(404, 409, 422),
    summary="Update an amenity",
)
async def update_amenity(
    amenity_id: uuid.UUID,
    payload: AmenityUpdate,
    request: Request,
    identity: Manager,
    service: ServiceDep,
) -> AmenityRead:
    with translated():
        row = await service.update_amenity(
            identity.actor, amenity_id, payload, request_id=get_request_id(request)
        )
    return AmenityRead.model_validate(row)


async def _set_amenity_active(
    amenity_id: uuid.UUID,
    active: bool,
    request: Request,
    identity: CurrentIdentity,
    service: ReferenceDataService,
) -> AmenityRead:
    with translated():
        row = await service.set_amenity_active(
            identity.actor, amenity_id, active, request_id=get_request_id(request)
        )
    return AmenityRead.model_validate(row)


@router.post(
    "/amenities/{amenity_id}/disable",
    responses=error_responses(404, 422),
    summary="Disable an amenity",
)
async def disable_amenity(
    amenity_id: uuid.UUID, request: Request, identity: Manager, service: ServiceDep
) -> AmenityRead:
    """Existing properties and units keep the amenity; it can no longer be newly chosen."""
    return await _set_amenity_active(amenity_id, False, request, identity, service)


@router.post(
    "/amenities/{amenity_id}/reactivate",
    responses=error_responses(404, 422),
    summary="Reactivate an amenity",
)
async def reactivate_amenity(
    amenity_id: uuid.UUID, request: Request, identity: Manager, service: ServiceDep
) -> AmenityRead:
    return await _set_amenity_active(amenity_id, True, request, identity, service)
