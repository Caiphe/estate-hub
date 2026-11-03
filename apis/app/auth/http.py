"""HTTP translation for authentication: API errors, their handler, and CSRF checks."""

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.auth.constants import AUTH_ERRORS, CSRF_HEADER_NAME, AuthErrorCode
from app.auth.cookies import clear_auth_cookies
from app.core.config import Settings, get_settings
from app.core.errors import error_response
from app.core.security.opaque_tokens import csrf_tokens_match


class AuthAPIError(Exception):
    """An authentication failure to return with the standard error body."""

    def __init__(
        self,
        code: AuthErrorCode,
        *,
        clear_cookies: bool = False,
        fields: dict[str, list[str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.clear_cookies = clear_cookies
        self.fields = fields
        self.headers = headers or {}


def _settings_for(request: Request) -> Settings:
    # Honour dependency overrides so tests and the app agree on cookie attributes.
    overrides = getattr(request.app, "dependency_overrides", {})
    provider = overrides.get(get_settings, get_settings)
    settings: Settings = provider()
    return settings


async def _auth_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AuthAPIError)
    spec = AUTH_ERRORS[exc.code]
    headers = dict(exc.headers)
    if spec.status_code == 401:
        headers["WWW-Authenticate"] = "Bearer"
    response = error_response(
        request, spec.status_code, exc.code.value, spec.message, exc.fields, headers
    )
    if exc.clear_cookies:
        clear_auth_cookies(response, _settings_for(request))
    return response


def register_auth_exception_handlers(application: FastAPI) -> None:
    application.add_exception_handler(AuthAPIError, _auth_error_handler)


def _cookie_occurrences(request: Request, name: str) -> int:
    raw = request.headers.get("cookie", "")
    return sum(1 for part in raw.split(";") if part.strip().split("=", 1)[0] == name)


def require_csrf(request: Request, settings: Settings) -> None:
    """Double-submit check: the header must equal the CSRF cookie.

    Missing, duplicated, malformed, or mismatched values all fail with ``csrf_failed``.
    """
    headers = request.headers.getlist(CSRF_HEADER_NAME)
    cookie_name = settings.auth_csrf_cookie_name
    if len(headers) != 1 or _cookie_occurrences(request, cookie_name) != 1:
        raise AuthAPIError(AuthErrorCode.CSRF_FAILED)
    if not csrf_tokens_match(request.cookies.get(cookie_name), headers[0]):
        raise AuthAPIError(AuthErrorCode.CSRF_FAILED)
