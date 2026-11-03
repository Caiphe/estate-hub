"""Authentication cookie attributes. Every set and delete uses the same attributes."""

from datetime import datetime
from typing import Literal

from starlette.responses import Response

from app.core.config import Settings


def _set(
    response: Response,
    settings: Settings,
    *,
    name: str,
    value: str,
    path: str,
    expires_at: datetime,
    now: datetime,
    httponly: bool,
) -> None:
    samesite: Literal["lax", "strict", "none"] = settings.auth_cookie_same_site
    response.set_cookie(
        name,
        value,
        max_age=max(int((expires_at - now).total_seconds()), 0),
        expires=expires_at,
        path=path,
        domain=settings.auth_cookie_domain,
        secure=settings.auth_cookie_secure,
        httponly=httponly,
        samesite=samesite,
    )


def set_auth_cookies(
    response: Response,
    settings: Settings,
    *,
    access_token: str,
    access_expires_at: datetime,
    refresh_token: str,
    refresh_expires_at: datetime,
    csrf_token: str,
    now: datetime,
) -> None:
    """Set the access, refresh, and CSRF cookies.

    The CSRF cookie lives as long as the refresh session because the frontend needs it
    to call refresh after the access token has expired. It is the only cookie scripts can
    read.
    """
    _set(
        response,
        settings,
        name=settings.auth_access_cookie_name,
        value=access_token,
        path=settings.auth_access_cookie_path,
        expires_at=access_expires_at,
        now=now,
        httponly=True,
    )
    _set(
        response,
        settings,
        name=settings.auth_refresh_cookie_name,
        value=refresh_token,
        path=settings.auth_refresh_cookie_path,
        expires_at=refresh_expires_at,
        now=now,
        httponly=True,
    )
    _set(
        response,
        settings,
        name=settings.auth_csrf_cookie_name,
        value=csrf_token,
        path="/",
        expires_at=refresh_expires_at,
        now=now,
        httponly=False,
    )


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    samesite: Literal["lax", "strict", "none"] = settings.auth_cookie_same_site
    for name, path, httponly in (
        (settings.auth_access_cookie_name, settings.auth_access_cookie_path, True),
        (settings.auth_refresh_cookie_name, settings.auth_refresh_cookie_path, True),
        (settings.auth_csrf_cookie_name, "/", False),
    ):
        response.delete_cookie(
            name,
            path=path,
            domain=settings.auth_cookie_domain,
            secure=settings.auth_cookie_secure,
            httponly=httponly,
            samesite=samesite,
        )
