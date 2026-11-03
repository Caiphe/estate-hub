import logging
from collections.abc import Mapping

from fastapi import FastAPI, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.middleware import REQUEST_ID_HEADER, get_request_id

logger = logging.getLogger(__name__)

_STATUS_CODES: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "validation_error",
    status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
    status.HTTP_503_SERVICE_UNAVAILABLE: "service_unavailable",
}


class ErrorDetail(BaseModel):
    code: str = Field(examples=["invalid_credentials"])
    message: str = Field(examples=["Incorrect email or password."])
    fields: dict[str, list[str]] = Field(default_factory=dict)
    request_id: str = Field(examples=["3f1c9a52-7d1e-4b8e-9b0a-2f4c6d8e1a3b"])


class ErrorResponse(BaseModel):
    """The standard error body returned by every endpoint."""

    error: ErrorDetail


class ApiError(Exception):
    """A business failure to return with the standard error body.

    Services raise their own errors; route handlers translate them into this.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        fields: dict[str, list[str]] | None = None,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = fields


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    fields: dict[str, list[str]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    request_id = get_request_id(request)
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, fields=fields or {}, request_id=request_id)
    )
    response_headers = dict(headers or {})
    if request_id:
        response_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(body.model_dump(), status_code=status_code, headers=response_headers)


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _STATUS_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
    return error_response(request, exc.status_code, code, message, headers=exc.headers)


async def _api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return error_response(request, exc.status_code, exc.code, exc.message, exc.fields)


async def _validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    fields: dict[str, list[str]] = {}
    for error in exc.errors():
        # Drop the leading "body"/"query"/"path" segment so fields match the client's names.
        location = [str(part) for part in error.get("loc", ())[1:]]
        fields.setdefault(".".join(location) or "__root__", []).append(str(error.get("msg")))
    return error_response(
        request,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "validation_error",
        "The request contains invalid data.",
        fields,
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", extra={"request_id": get_request_id(request)})
    return error_response(
        request,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "internal_error",
        "An unexpected error occurred.",
    )


def register_exception_handlers(application: FastAPI) -> None:
    application.add_exception_handler(ApiError, _api_error_handler)
    application.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    application.add_exception_handler(RequestValidationError, _validation_exception_handler)
    application.add_exception_handler(Exception, _unhandled_exception_handler)
