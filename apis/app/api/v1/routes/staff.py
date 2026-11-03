import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.auth.constants import AuthErrorCode
from app.auth.dependencies import ClockDep, CurrentIdentity, DbDep, require_permissions
from app.auth.errors import PermissionDeniedError
from app.auth.http import AuthAPIError
from app.auth.permissions import Permission
from app.core.errors import ApiError, ErrorResponse
from app.core.middleware import get_request_id
from app.core.pagination import Page
from app.users.errors import (
    EmailAlreadyExistsError,
    LastAdministratorError,
    SelfLockoutError,
    StaffNotFoundError,
    StaffServiceError,
    UnknownRoleError,
)
from app.users.schemas import (
    RoleAssignment,
    StaffCreate,
    StaffListQuery,
    StaffUpdate,
    UserPublic,
)
from app.users.service import StaffService

router = APIRouter()


def get_staff_service(db: DbDep, clock: ClockDep) -> StaffService:
    return StaffService(db, clock=clock)


ServiceDep = Annotated[StaffService, Depends(get_staff_service)]


# Each route declares the exact permission it needs; the service checks it again.
Reader = Annotated[CurrentIdentity, Depends(require_permissions(Permission.STAFF_READ))]
Creator = Annotated[CurrentIdentity, Depends(require_permissions(Permission.STAFF_CREATE))]
Updater = Annotated[CurrentIdentity, Depends(require_permissions(Permission.STAFF_UPDATE))]
RoleAssigner = Annotated[
    CurrentIdentity, Depends(require_permissions(Permission.STAFF_ASSIGN_ROLES))
]
Disabler = Annotated[CurrentIdentity, Depends(require_permissions(Permission.STAFF_DISABLE))]
Reactivator = Annotated[CurrentIdentity, Depends(require_permissions(Permission.STAFF_REACTIVATE))]
SessionRevoker = Annotated[
    CurrentIdentity, Depends(require_permissions(Permission.STAFF_REVOKE_SESSIONS))
]

_STATUS = {
    StaffNotFoundError: status.HTTP_404_NOT_FOUND,
    EmailAlreadyExistsError: status.HTTP_409_CONFLICT,
    LastAdministratorError: status.HTTP_409_CONFLICT,
    SelfLockoutError: status.HTTP_409_CONFLICT,
    UnknownRoleError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def _responses(*codes: int) -> dict[int | str, dict[str, object]]:
    descriptions = {
        401: "Not authenticated (`authentication_required`, `invalid_token`, `token_expired`).",
        403: "Missing permission (`permission_denied`) or CSRF failure (`csrf_failed`).",
        404: "No staff member with this ID (`not_found`).",
        409: "Conflict: `email_already_exists`, `last_administrator`, or `self_lockout`.",
        422: "Invalid input (`validation_error`), including unknown role codes.",
    }
    return {code: {"model": ErrorResponse, "description": descriptions[code]} for code in codes}


@contextmanager
def _translated() -> Iterator[None]:
    """Map service errors to HTTP. The only logic route handlers contain."""
    try:
        yield
    except PermissionDeniedError:
        raise AuthAPIError(AuthErrorCode.PERMISSION_DENIED) from None
    except StaffServiceError as exc:
        raise ApiError(_STATUS[type(exc)], exc.code, exc.message, exc.fields) from None


def _public(user: object) -> UserPublic:
    return UserPublic.model_validate(user)


@router.get(
    "",
    response_model=Page[UserPublic],
    responses=_responses(401, 403, 422),
    summary="List staff",
)
async def list_staff(
    query: Annotated[StaffListQuery, Query()], identity: Reader, service: ServiceDep
) -> Page[UserPublic]:
    """Filter by `status`, `role`, and `q` (email or name, case-insensitive).

    Sorted by `sort` with the user ID as tie-breaker. `limit` is at most 100.
    """
    with _translated():
        users, total = await service.list_staff(identity.actor, query)
    return Page[UserPublic](
        items=[_public(user) for user in users],
        total=total,
        limit=query.limit,
        offset=query.offset,
    )


@router.get(
    "/{user_id}",
    response_model=UserPublic,
    responses=_responses(401, 403, 404, 422),
    summary="Get a staff member",
)
async def get_staff(user_id: uuid.UUID, identity: Reader, service: ServiceDep) -> UserPublic:
    with _translated():
        return _public(await service.get_staff(identity.actor, user_id))


@router.post(
    "",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
    responses=_responses(401, 403, 409, 422),
    summary="Create a staff member",
)
async def create_staff(
    payload: StaffCreate,
    request: Request,
    response: Response,
    identity: Creator,
    service: ServiceDep,
) -> UserPublic:
    """Create an active account with at least one role. The password is never returned."""
    with _translated():
        user = await service.create_staff(
            identity.actor, payload, request_id=get_request_id(request)
        )
    response.headers["Location"] = str(request.url_for("get_staff", user_id=user.id))
    return _public(user)


@router.patch(
    "/{user_id}",
    response_model=UserPublic,
    responses=_responses(401, 403, 404, 409, 422),
    summary="Update a staff member's name or email",
)
async def update_staff(
    user_id: uuid.UUID,
    payload: StaffUpdate,
    request: Request,
    identity: Updater,
    service: ServiceDep,
) -> UserPublic:
    """Only `full_name` and `email`. Roles, status, and passwords have their own endpoints."""
    with _translated():
        user = await service.update_profile(
            identity.actor, user_id, payload, request_id=get_request_id(request)
        )
    return _public(user)


@router.put(
    "/{user_id}/roles",
    response_model=UserPublic,
    responses=_responses(401, 403, 404, 409, 422),
    summary="Replace a staff member's roles",
)
async def replace_roles(
    user_id: uuid.UUID,
    payload: RoleAssignment,
    request: Request,
    identity: RoleAssigner,
    service: ServiceDep,
) -> UserPublic:
    """Replaces the whole role set. The user's existing access tokens stop working, so the
    new roles apply on their next request after a refresh."""
    with _translated():
        user = await service.replace_roles(
            identity.actor, user_id, payload.roles, request_id=get_request_id(request)
        )
    return _public(user)


@router.post(
    "/{user_id}/disable",
    response_model=UserPublic,
    responses=_responses(401, 403, 404, 409, 422),
    summary="Disable a staff member",
)
async def disable_staff(
    user_id: uuid.UUID, request: Request, identity: Disabler, service: ServiceDep
) -> UserPublic:
    """Blocks sign-in and ends every session immediately. Idempotent."""
    with _translated():
        user = await service.disable(identity.actor, user_id, request_id=get_request_id(request))
    return _public(user)


@router.post(
    "/{user_id}/reactivate",
    response_model=UserPublic,
    responses=_responses(401, 403, 404, 422),
    summary="Reactivate a staff member",
)
async def reactivate_staff(
    user_id: uuid.UUID, request: Request, identity: Reactivator, service: ServiceDep
) -> UserPublic:
    """Allows sign-in again. Earlier sessions stay revoked. Idempotent."""
    with _translated():
        user = await service.reactivate(identity.actor, user_id, request_id=get_request_id(request))
    return _public(user)


@router.post(
    "/{user_id}/revoke-sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_responses(401, 403, 404, 422),
    summary="Sign a staff member out everywhere",
)
async def revoke_sessions(
    user_id: uuid.UUID, request: Request, identity: SessionRevoker, service: ServiceDep
) -> Response:
    """Revokes every refresh session and invalidates every access token. Status is unchanged."""
    with _translated():
        await service.revoke_sessions(identity.actor, user_id, request_id=get_request_id(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
