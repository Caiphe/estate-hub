"""OpenAPI error documentation for catalog routes, generated from the error contracts.

Routes pass ``responses=error_responses(404, 409, ...)``. Every description lists the
exact codes a client can receive for that status, so documentation cannot drift from
``CATALOG_ERRORS``.
"""

from collections import defaultdict

from fastapi import status

from app.auth.constants import AuthErrorCode
from app.catalog.errors import CATALOG_ERRORS
from app.core.errors import ErrorResponse

_AUTH_CODES: dict[int, tuple[str, ...]] = {
    status.HTTP_401_UNAUTHORIZED: (
        AuthErrorCode.AUTHENTICATION_REQUIRED,
        AuthErrorCode.INVALID_TOKEN,
        AuthErrorCode.TOKEN_EXPIRED,
    ),
    status.HTTP_403_FORBIDDEN: (AuthErrorCode.PERMISSION_DENIED, AuthErrorCode.CSRF_FAILED),
}
_TITLES = {
    status.HTTP_401_UNAUTHORIZED: "Not authenticated",
    status.HTTP_403_FORBIDDEN: "Missing permission, or CSRF failure on a cookie request",
    status.HTTP_404_NOT_FOUND: "No such record under this parent",
    status.HTTP_409_CONFLICT: "Conflicts with stored state",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "Invalid input",
}


def codes_by_status() -> dict[int, list[str]]:
    grouped: defaultdict[int, list[str]] = defaultdict(list)
    for http_status, codes in _AUTH_CODES.items():
        grouped[http_status].extend(str(code) for code in codes)
    for code, spec in CATALOG_ERRORS.items():
        if code.value not in grouped[spec.status_code]:
            grouped[spec.status_code].append(code.value)
    return dict(grouped)


def error_responses(*statuses: int) -> dict[int | str, dict[str, object]]:
    """Every route gets 401 and 403; add the statuses the route can also return."""
    grouped = codes_by_status()
    documented = sorted({status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN, *statuses})
    return {
        code: {
            "model": ErrorResponse,
            "description": f"{_TITLES[code]}: "
            + ", ".join(f"`{name}`" for name in grouped[code])
            + ".",
        }
        for code in documented
    }
