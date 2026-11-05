"""Images and private documents of a property or of one of its units.

The same handlers serve both parents: ``/properties/{id}/media`` and
``/properties/{id}/units/{unit_id}/media`` (and likewise ``documents``). A file requested
under a parent it does not belong to is not found. Uploads are multipart; the file's type
comes from its bytes, never from its name or ``Content-Type``. Downloads stream through
this API with private, no-sniff headers; storage paths and keys are never exposed.
"""

import uuid
from collections.abc import AsyncIterator, Callable
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError

from app.auth.dependencies import (
    ClockDep,
    CurrentIdentity,
    DbDep,
    SettingsDep,
    require_permissions,
)
from app.auth.permissions import Permission
from app.catalog.http import location, translated
from app.catalog.openapi import error_responses
from app.core.middleware import get_request_id
from app.core.pagination import Page
from app.media.constants import DocumentCategory
from app.media.http import content_disposition, private_file_headers
from app.media.models import MediaAsset
from app.media.repository import Parent
from app.media.schemas import (
    DocumentCreate,
    DocumentDetail,
    DocumentSummary,
    DocumentUpdate,
    MediaOrder,
    MediaPublic,
    MediaUpdate,
)
from app.media.service import DocumentService, MediaService, Upload, UploadLimits
from app.media.storage import CHUNK_SIZE, LocalStorage, ObjectStorage
from app.properties.schemas import ArchivedQuery

router = APIRouter()


def get_storage(settings: SettingsDep) -> ObjectStorage:
    return LocalStorage(settings.media_storage_root)


def get_upload_limits(settings: SettingsDep) -> UploadLimits:
    return UploadLimits.from_settings(settings)


StorageDep = Annotated[ObjectStorage, Depends(get_storage)]
LimitsDep = Annotated[UploadLimits, Depends(get_upload_limits)]


def get_media_service(
    db: DbDep, storage: StorageDep, limits: LimitsDep, clock: ClockDep
) -> MediaService:
    return MediaService(db, storage, limits, clock=clock)


def get_document_service(
    db: DbDep, storage: StorageDep, limits: LimitsDep, clock: ClockDep
) -> DocumentService:
    return DocumentService(db, storage, limits, clock=clock)


MediaDep = Annotated[MediaService, Depends(get_media_service)]
DocumentsDep = Annotated[DocumentService, Depends(get_document_service)]
Reader = Annotated[CurrentIdentity, Depends(require_permissions(Permission.PROPERTIES_READ))]
MediaManager = Annotated[
    CurrentIdentity, Depends(require_permissions(Permission.PROPERTY_MEDIA_MANAGE))
]
DocumentReader = Annotated[
    CurrentIdentity, Depends(require_permissions(Permission.PROPERTY_DOCUMENTS_READ))
]
DocumentManager = Annotated[
    CurrentIdentity, Depends(require_permissions(Permission.PROPERTY_DOCUMENTS_MANAGE))
]
FileField = Annotated[UploadFile, File(description="JPEG, PNG, or WebP (documents: also PDF).")]


def property_parent(property_id: uuid.UUID) -> Parent:
    return Parent(property_id)


def unit_parent(property_id: uuid.UUID, unit_id: uuid.UUID) -> Parent:
    return Parent(property_id, unit_id)


def _upload(file: UploadFile) -> Upload:
    """The stream Starlette spooled, read in bounded chunks. ``size`` lets the service
    refuse an oversized file before copying it."""

    async def chunks() -> AsyncIterator[bytes]:
        while chunk := await file.read(CHUNK_SIZE):
            yield chunk

    return Upload(filename=file.filename, chunks=chunks(), declared_size=file.size)


def _form_model[M: BaseModel](model: type[M], **values: object) -> M:
    """Validate multipart form fields like a JSON body, with the same 422 shape."""
    try:
        return model.model_validate(values)
    except ValidationError as exc:
        raise RequestValidationError(
            [
                {**error, "loc": ("body", *error["loc"])}
                for error in exc.errors(include_url=False, include_input=False)
            ]
        ) from None


def _media_public(rows: list[MediaAsset]) -> list[MediaPublic]:
    return [MediaPublic.model_validate(row) for row in rows]


def _register(prefix: str, parent_dependency: Callable[..., Parent], name: str, label: str) -> None:
    """Media and document routes for one parent kind (property or unit)."""
    ParentDep = Annotated[Parent, Depends(parent_dependency)]
    media, media_item = f"{prefix}/media", f"{prefix}/media/{{media_id}}"
    docs, doc = f"{prefix}/documents", f"{prefix}/documents/{{document_id}}"

    def media_location(request: Request, parent: Parent, media_id: uuid.UUID) -> str:
        params: dict[str, object] = {"property_id": parent.property_id, "media_id": media_id}
        if parent.unit_id is not None:
            params["unit_id"] = parent.unit_id
        return location(request, f"{name}_download_media", **params)

    # --- Images --------------------------------------------------------------------------

    @router.get(
        media,
        name=f"{name}_list_media",
        responses=error_responses(404, 422),
        summary=f"List {label} images",
    )
    async def list_media(
        parent: ParentDep,
        query: Annotated[ArchivedQuery, Query()],
        identity: Reader,
        service: MediaDep,
    ) -> Page[MediaPublic]:
        """Active images in display order (then upload time, then ID). A parent has at
        most 100 active images, so `limit=100` returns the whole gallery."""
        with translated():
            rows = await service.list_media(
                identity.actor,
                parent,
                include_archived=query.include_archived,
                limit=query.limit,
                offset=query.offset,
            )
            total = await service.count_media(
                identity.actor, parent, include_archived=query.include_archived
            )
        return Page[MediaPublic](
            items=_media_public(rows), total=total, limit=query.limit, offset=query.offset
        )

    @router.post(
        media,
        name=f"{name}_upload_media",
        status_code=status.HTTP_201_CREATED,
        responses=error_responses(404, 409, 422),
        summary=f"Upload a {label} image",
    )
    async def upload_media(
        parent: ParentDep,
        file: FileField,
        request: Request,
        response: Response,
        identity: MediaManager,
        service: MediaDep,
        alt_text: Annotated[str | None, Form(max_length=500)] = None,
    ) -> MediaPublic:
        """JPEG, PNG, or WebP, checked by content and fully decoded. Rejected files are
        `422 invalid_upload` with a generic message. `Location` is the download URL."""
        metadata = _form_model(MediaUpdate, alt_text=alt_text)
        with translated():
            row = await service.upload_media(
                identity.actor,
                parent,
                _upload(file),
                alt_text=metadata.alt_text,
                request_id=get_request_id(request),
            )
        response.headers["Location"] = media_location(request, parent, row.id)
        return MediaPublic.model_validate(row)

    @router.put(
        f"{media}/order",
        name=f"{name}_reorder_media",
        responses=error_responses(404, 409, 422),
        summary=f"Reorder {label} images",
    )
    async def reorder_media(
        parent: ParentDep,
        payload: MediaOrder,
        request: Request,
        identity: MediaManager,
        service: MediaDep,
    ) -> list[MediaPublic]:
        """Send every active image's ID exactly once, in the new order."""
        with translated():
            rows = await service.reorder_media(
                identity.actor, parent, payload, request_id=get_request_id(request)
            )
        return _media_public(rows)

    @router.get(
        f"{media_item}/content",
        name=f"{name}_download_media",
        response_class=StreamingResponse,
        responses={
            200: {"content": {"image/jpeg": {}, "image/png": {}, "image/webp": {}}},
            **error_responses(404, 422),
        },
        summary=f"Download a {label} image",
    )
    async def download_media(
        parent: ParentDep, media_id: uuid.UUID, identity: Reader, service: MediaDep
    ) -> StreamingResponse:
        with translated():
            row, stream = await service.open_media(identity.actor, parent, media_id)
        headers = private_file_headers(no_store=False) | {
            "Content-Disposition": content_disposition("inline", row.original_filename),
            "Content-Length": str(row.byte_size),
        }
        return StreamingResponse(stream, media_type=row.media_type, headers=headers)

    @router.patch(
        media_item,
        name=f"{name}_update_media",
        responses=error_responses(404, 409, 422),
        summary=f"Update {label} image alt text",
    )
    async def update_media(
        parent: ParentDep,
        media_id: uuid.UUID,
        payload: MediaUpdate,
        request: Request,
        identity: MediaManager,
        service: MediaDep,
    ) -> MediaPublic:
        """Only `alt_text`; the file, its type, and its storage never change."""
        with translated():
            row = await service.update_media(
                identity.actor, parent, media_id, payload, request_id=get_request_id(request)
            )
        return MediaPublic.model_validate(row)

    @router.post(
        f"{media_item}/cover",
        name=f"{name}_set_cover",
        responses=error_responses(404, 409, 422),
        summary=f"Set the {label} cover",
    )
    async def set_cover(
        parent: ParentDep,
        media_id: uuid.UUID,
        request: Request,
        identity: MediaManager,
        service: MediaDep,
    ) -> MediaPublic:
        """Clears the previous cover in the same transaction."""
        with translated():
            row = await service.set_cover(
                identity.actor, parent, media_id, request_id=get_request_id(request)
            )
        return MediaPublic.model_validate(row)

    @router.delete(
        media_item,
        name=f"{name}_archive_media",
        responses=error_responses(404, 409, 422),
        summary=f"Archive a {label} image",
    )
    async def archive_media(
        parent: ParentDep,
        media_id: uuid.UUID,
        request: Request,
        identity: MediaManager,
        service: MediaDep,
    ) -> MediaPublic:
        """Final and idempotent; it stops being the cover. The stored file is kept."""
        with translated():
            row = await service.archive_media(
                identity.actor, parent, media_id, request_id=get_request_id(request)
            )
        return MediaPublic.model_validate(row)

    # --- Private documents ---------------------------------------------------------------

    @router.get(
        docs,
        name=f"{name}_list_documents",
        responses=error_responses(404, 422),
        summary=f"List {label} documents",
    )
    async def list_documents(
        parent: ParentDep,
        query: Annotated[ArchivedQuery, Query()],
        identity: DocumentReader,
        service: DocumentsDep,
    ) -> Page[DocumentSummary]:
        """Newest first, then ID. Metadata only: no file contents, keys, or paths."""
        with translated():
            rows = await service.list_documents(
                identity.actor,
                parent,
                include_archived=query.include_archived,
                limit=query.limit,
                offset=query.offset,
            )
            total = await service.count_documents(
                identity.actor, parent, include_archived=query.include_archived
            )
        return Page[DocumentSummary](
            items=[DocumentSummary.model_validate(row) for row in rows],
            total=total,
            limit=query.limit,
            offset=query.offset,
        )

    @router.post(
        docs,
        name=f"{name}_upload_document",
        status_code=status.HTTP_201_CREATED,
        responses=error_responses(404, 409, 422),
        summary=f"Upload a {label} document",
    )
    async def upload_document(
        parent: ParentDep,
        file: FileField,
        category: Annotated[DocumentCategory, Form()],
        title: Annotated[str, Form(max_length=500)],
        request: Request,
        response: Response,
        identity: DocumentManager,
        service: DocumentsDep,
        expiry_date: Annotated[date | None, Form()] = None,
    ) -> DocumentDetail:
        """PDF, or a JPEG/PNG/WebP scan, checked by content."""
        metadata = _form_model(
            DocumentCreate, category=category, title=title, expiry_date=expiry_date
        )
        with translated():
            row = await service.upload_document(
                identity.actor,
                parent,
                _upload(file),
                metadata,
                request_id=get_request_id(request),
            )
        params: dict[str, object] = {"property_id": parent.property_id, "document_id": row.id}
        if parent.unit_id is not None:
            params["unit_id"] = parent.unit_id
        response.headers["Location"] = location(request, f"{name}_get_document", **params)
        return DocumentDetail.model_validate(row)

    @router.get(
        doc,
        name=f"{name}_get_document",
        responses=error_responses(404, 422),
        summary=f"Get {label} document metadata",
    )
    async def get_document(
        parent: ParentDep,
        document_id: uuid.UUID,
        identity: DocumentReader,
        service: DocumentsDep,
    ) -> DocumentDetail:
        with translated():
            row = await service.get_document(identity.actor, parent, document_id)
        return DocumentDetail.model_validate(row)

    @router.get(
        f"{doc}/content",
        name=f"{name}_download_document",
        response_class=StreamingResponse,
        responses={
            200: {"content": {"application/pdf": {}, "image/jpeg": {}}},
            **error_responses(404, 422),
        },
        summary=f"Download a {label} document",
    )
    async def download_document(
        parent: ParentDep,
        document_id: uuid.UUID,
        request: Request,
        identity: DocumentReader,
        service: DocumentsDep,
    ) -> StreamingResponse:
        """Always an attachment, never cached. Each download is audited."""
        with translated():
            row, stream = await service.open_document(
                identity.actor, parent, document_id, request_id=get_request_id(request)
            )
        headers = private_file_headers(no_store=True) | {
            "Content-Disposition": content_disposition("attachment", row.original_filename),
            "Content-Length": str(row.byte_size),
        }
        return StreamingResponse(stream, media_type=row.media_type, headers=headers)

    @router.patch(
        doc,
        name=f"{name}_update_document",
        responses=error_responses(404, 409, 422),
        summary=f"Update {label} document metadata",
    )
    async def update_document(
        parent: ParentDep,
        document_id: uuid.UUID,
        payload: DocumentUpdate,
        request: Request,
        identity: DocumentManager,
        service: DocumentsDep,
    ) -> DocumentDetail:
        """Category, title, and expiry date; send the current `version`."""
        with translated():
            row = await service.update_document(
                identity.actor, parent, document_id, payload, request_id=get_request_id(request)
            )
        return DocumentDetail.model_validate(row)

    @router.put(
        f"{doc}/content",
        name=f"{name}_replace_document",
        responses=error_responses(404, 409, 422),
        summary=f"Replace a {label} document file",
    )
    async def replace_document(
        parent: ParentDep,
        document_id: uuid.UUID,
        file: FileField,
        version: Annotated[int, Form(ge=1)],
        request: Request,
        identity: DocumentManager,
        service: DocumentsDep,
    ) -> DocumentDetail:
        """Keeps the record and its metadata; the old file is removed only after the new
        one is committed. Send the current `version`."""
        with translated():
            row = await service.replace_document(
                identity.actor,
                parent,
                document_id,
                _upload(file),
                version=version,
                request_id=get_request_id(request),
            )
        return DocumentDetail.model_validate(row)

    @router.delete(
        doc,
        name=f"{name}_archive_document",
        responses=error_responses(404, 409, 422),
        summary=f"Archive a {label} document",
    )
    async def archive_document(
        parent: ParentDep,
        document_id: uuid.UUID,
        request: Request,
        identity: DocumentManager,
        service: DocumentsDep,
    ) -> DocumentDetail:
        """Final and idempotent. The stored file is kept as history."""
        with translated():
            row = await service.archive_document(
                identity.actor, parent, document_id, request_id=get_request_id(request)
            )
        return DocumentDetail.model_validate(row)


_register("/{property_id}", property_parent, "property", "property")
_register("/{property_id}/units/{unit_id}", unit_parent, "unit", "unit")
