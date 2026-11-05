"""HTTP translation for catalog routes, the only logic their handlers contain."""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import Request

from app.auth.constants import AuthErrorCode
from app.auth.errors import PermissionDeniedError
from app.auth.http import AuthAPIError
from app.catalog.errors import CatalogError
from app.core.errors import ApiError


@contextmanager
def translated() -> Iterator[None]:
    """Map service errors to the standard error body. A service-level denial (such as
    ``include_archived`` without its permission) becomes ``403 permission_denied``, the
    same as a route guard. Anything unexpected propagates and is logged as a 500."""
    try:
        yield
    except PermissionDeniedError:
        raise AuthAPIError(AuthErrorCode.PERMISSION_DENIED) from None
    except CatalogError as exc:
        raise ApiError(exc.status_code, exc.code.value, exc.message, exc.fields) from None


def location(request: Request, route_name: str, **path_params: object) -> str:
    return str(request.url_for(route_name, **{k: str(v) for k, v in path_params.items()}))
