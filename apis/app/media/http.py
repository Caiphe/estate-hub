"""HTTP concerns for uploads and downloads.

FastAPI parses a multipart body before any route code runs, so the early size limit is
ASGI middleware: a multipart request without ``Content-Length``, or declaring more than
the largest allowed upload, is refused before its body is read. The exact per-type limit
is enforced again on every chunk by ``app.media.files.stage_upload``.
"""

import re
import unicodedata
from urllib.parse import quote

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.catalog.errors import CATALOG_ERRORS, CatalogErrorCode
from app.core.errors import error_response

# Room for multipart boundaries, part headers, and small form fields such as a title.
MULTIPART_ALLOWANCE = 64 * 1024
LENGTH_REQUIRED = "Uploads need a Content-Length header."
TOO_LARGE = "The file is larger than the allowed size."
_UNSAFE_ASCII = re.compile(r"[^A-Za-z0-9._ ()-]")


class UploadLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_upload_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_upload_bytes + MULTIPART_ALLOWANCE

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in {"POST", "PUT", "PATCH"}:
            headers = dict(scope["headers"])
            if headers.get(b"content-type", b"").startswith(b"multipart/form-data"):
                problem = self._problem(headers.get(b"content-length"))
                if problem is not None:
                    response = error_response(
                        Request(scope),
                        CATALOG_ERRORS[CatalogErrorCode.INVALID_UPLOAD].status_code,
                        CatalogErrorCode.INVALID_UPLOAD.value,
                        CATALOG_ERRORS[CatalogErrorCode.INVALID_UPLOAD].message,
                        {"file": [problem]},
                        # The unread body would otherwise be parsed as the next request.
                        headers={"Connection": "close"},
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)

    def _problem(self, declared: bytes | None) -> str | None:
        if declared is None or not declared.isdigit():
            return LENGTH_REQUIRED
        if int(declared) > self.max_body_bytes:
            return TOO_LARGE
        return None


def content_disposition(disposition: str, filename: str) -> str:
    """A header that cannot be broken by the stored name: an ASCII fallback with every
    unusual character replaced, plus the exact name percent-encoded (RFC 6266/5987)."""
    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode()
    ascii_name = _UNSAFE_ASCII.sub("_", ascii_name).strip() or "download"
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


def private_file_headers(*, no_store: bool) -> dict[str, str]:
    """Authenticated content: never cached by shared caches, never sniffed or executed."""
    return {
        "Cache-Control": "private, no-store" if no_store else "private, max-age=300",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cross-Origin-Resource-Policy": "same-origin",
    }
