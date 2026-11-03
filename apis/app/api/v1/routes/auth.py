import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.auth.constants import AuthErrorCode
from app.auth.cookies import clear_auth_cookies, set_auth_cookies
from app.auth.dependencies import AuthServiceDep, CurrentIdentityDep, SettingsDep
from app.auth.errors import (
    AuthServiceError,
    IncorrectCurrentPasswordError,
    ReusedRefreshTokenError,
)
from app.auth.http import AuthAPIError, require_csrf
from app.auth.schemas import (
    ClientMetadata,
    EffectivePermissions,
    PasswordChange,
    TokenResponse,
)
from app.auth.service import IssuedSession
from app.core.config import Settings
from app.core.errors import ErrorResponse
from app.core.security.opaque_tokens import generate_csrf_token
from app.users.schemas import UserPublic

logger = logging.getLogger(__name__)
router = APIRouter()

_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
}
_PROTECTED_ERRORS: dict[int | str, dict[str, object]] = _ERRORS | {422: {"model": ErrorResponse}}


def _client(request: Request) -> ClientMetadata:
    host = request.client.host if request.client else None
    return ClientMetadata.from_request_values(request.headers.get("user-agent"), host)


def _token_response(response: Response, settings: Settings, issued: IssuedSession) -> TokenResponse:
    claims = issued.access_token.claims
    set_auth_cookies(
        response,
        settings,
        access_token=issued.access_token.token,
        access_expires_at=claims.expires_at,
        refresh_token=issued.refresh_token,
        refresh_expires_at=issued.refresh_expires_at,
        csrf_token=generate_csrf_token(),
        now=claims.issued_at,
    )
    # RFC 6749 section 5.1: token responses must not be cached.
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return TokenResponse(
        access_token=issued.access_token.token, expires_in=issued.access_token.expires_in
    )


@router.post(
    "/token",
    response_model=TokenResponse,
    responses=_ERRORS,
    summary="Sign in with email and password",
)
async def login(
    request: Request,
    response: Response,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    service: AuthServiceDep,
    settings: SettingsDep,
) -> TokenResponse:
    """OAuth2 password flow. `username` is the staff email address.

    Returns the access token in the body for API clients and sets the access, refresh,
    and CSRF cookies for browsers. The refresh token is only ever sent as a cookie.
    """
    try:
        issued = await service.authenticate(form.username, form.password, _client(request))
    except AuthServiceError as exc:
        raise AuthAPIError(exc.public_code) from None
    return _token_response(response, settings, issued)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    responses=_ERRORS,
    summary="Rotate the refresh session",
)
async def refresh(
    request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
) -> TokenResponse:
    """Browser-only: reads the refresh cookie and requires the `X-CSRF-Token` header.

    Every successful call replaces all three cookies. Any session failure clears them.
    """
    require_csrf(request, settings)
    refresh_token = request.cookies.get(settings.auth_refresh_cookie_name)
    if not refresh_token:
        raise AuthAPIError(AuthErrorCode.INVALID_SESSION, clear_cookies=True)
    try:
        issued = await service.refresh(refresh_token, _client(request))
    except ReusedRefreshTokenError as exc:
        logger.warning(
            "Refresh token reuse detected; session family revoked",
            extra={"user_id": str(exc.user_id), "family_id": str(exc.family_id)},
        )
        raise AuthAPIError(exc.public_code, clear_cookies=True) from None
    except AuthServiceError as exc:
        raise AuthAPIError(exc.public_code, clear_cookies=True) from None
    return _token_response(response, settings, issued)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={403: {"model": ErrorResponse}},
    summary="Sign out",
)
async def logout(
    request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
) -> None:
    """Revoke the current refresh session, if any, and clear every auth cookie.

    Always succeeds without revealing whether a session existed. When a refresh cookie
    is present the CSRF header is required, so other sites cannot sign a user out.
    """
    refresh_token = request.cookies.get(settings.auth_refresh_cookie_name)
    if refresh_token:
        require_csrf(request, settings)
        await service.logout(refresh_token)
    clear_auth_cookies(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT


@router.get(
    "/me",
    response_model=UserPublic,
    responses=_ERRORS,
    summary="Current staff member",
)
async def me(identity: CurrentIdentityDep, response: Response) -> UserPublic:
    """The signed-in staff member's identity and current role codes."""
    response.headers["Cache-Control"] = "no-store"
    return UserPublic.model_validate(identity.user)


@router.get(
    "/me/permissions",
    response_model=EffectivePermissions,
    responses=_ERRORS,
    summary="Current staff member's effective permissions",
)
async def my_permissions(identity: CurrentIdentityDep, response: Response) -> EffectivePermissions:
    """Role codes and the permissions they grant, for showing or hiding navigation.

    Every endpoint checks permissions itself; this response grants nothing.
    """
    response.headers["Cache-Control"] = "no-store"
    actor = identity.actor
    return EffectivePermissions(
        roles=sorted(actor.role_codes),
        permissions=sorted(permission.value for permission in actor.permissions),
    )


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_PROTECTED_ERRORS,
    summary="Change your own password",
)
async def change_password(
    payload: PasswordChange,
    identity: CurrentIdentityDep,
    service: AuthServiceDep,
    settings: SettingsDep,
    response: Response,
) -> None:
    """Change the password, then sign out everywhere.

    Every refresh session is revoked and every existing access token stops working, this
    one included. The response clears the auth cookies; sign in again with the new
    password. Cookie-authenticated calls need the `X-CSRF-Token` header.
    """
    try:
        await service.change_password(
            identity.user.id,
            payload.current_password.get_secret_value(),
            payload.new_password.get_secret_value(),
        )
    except IncorrectCurrentPasswordError as exc:
        raise AuthAPIError(
            exc.public_code, fields={"current_password": ["The current password is incorrect."]}
        ) from None
    except AuthServiceError as exc:
        raise AuthAPIError(exc.public_code, clear_cookies=True) from None
    clear_auth_cookies(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
