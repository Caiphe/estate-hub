"""Uploading, ordering, downloading, and archiving property and unit files.

Every mutation locks the parent property row (for unit files too), so cover changes,
ordering, and uploads to one property run one at a time.

Upload consistency: the file is validated into a temporary file before the transaction,
moved into storage inside it, and deleted again if anything later fails, including the
commit. A storage failure rolls the transaction back, so metadata never points at a
missing object. Only an object this request stored is ever deleted.

Audit metadata holds parent IDs, media types, sizes, categories, and changed field names:
never filenames, titles, alt text, storage keys, or file contents.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.events import AuditEventCode
from app.audit.service import record_audit_event
from app.auth.permissions import Permission
from app.auth.policy import Actor, require_permissions
from app.catalog.errors import (
    ArchivedRecordError,
    CatalogNotFoundError,
    InvalidRelationshipError,
    InvalidUploadError,
    StaleVersionError,
)
from app.catalog.limits import MAX_ACTIVE_IMAGES_PER_PARENT, ensure_below
from app.core.config import Settings
from app.core.pagination import MAX_PAGE_SIZE
from app.core.security.access_tokens import utc_now
from app.media.constants import DOCUMENT_TYPES, IMAGE_TYPES, FileType
from app.media.files import (
    UploadRejectedError,
    check_pdf,
    discard,
    inspect_image,
    stage_upload,
    validate_filename,
)
from app.media.models import Document, MediaAsset
from app.media.repository import DocumentRepository, MediaRepository, Parent
from app.media.schemas import DocumentCreate, DocumentUpdate, MediaOrder, MediaUpdate
from app.media.storage import Namespace, ObjectStorage, new_storage_key
from app.properties.repository import PropertyRepository, UnitRepository

logger = logging.getLogger(__name__)
ORDER_MISMATCH = "Provide every active image of this parent exactly once."
Store = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class UploadLimits:
    max_image_bytes: int
    max_document_bytes: int
    max_image_pixels: int

    @classmethod
    def from_settings(cls, settings: Settings) -> UploadLimits:
        return cls(
            settings.media_max_image_bytes,
            settings.media_max_document_bytes,
            settings.media_max_image_pixels,
        )


@dataclass(frozen=True, slots=True)
class Upload:
    """An upload as received from a client. Every field is untrusted."""

    filename: str | None
    chunks: AsyncIterable[bytes]
    declared_size: int | None = None


@dataclass(frozen=True, slots=True)
class ReceivedFile:
    """A validated upload in a temporary file the service must move or delete."""

    path: Path
    filename: str
    file_type: FileType
    byte_size: int
    width: int | None = None
    height: int | None = None


class _ParentedFiles:
    def __init__(
        self,
        db: AsyncSession,
        storage: ObjectStorage,
        limits: UploadLimits,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._db = db
        self._storage = storage
        self._limits = limits
        self._clock = clock
        self._properties = PropertyRepository(db)
        self._units = UnitRepository(db)

    async def _check_parent(self, parent: Parent, *, for_change: bool) -> None:
        """The property must exist (and the unit belong to it). Changes also lock the
        property row and refuse archived parents."""
        found = await self._properties.get(parent.property_id, for_update=for_change)
        if found is None:
            raise CatalogNotFoundError()
        unit = None
        if parent.unit_id is not None:
            unit = await self._units.get(parent.property_id, parent.unit_id)
            if unit is None:
                raise CatalogNotFoundError()
        if for_change and (found.is_archived or (unit is not None and unit.is_archived)):
            raise ArchivedRecordError()

    async def _receive(self, upload: Upload, *, documents: bool) -> ReceivedFile:
        """Stage and inspect an upload (see ``app.media.files``). Rejections become
        ``invalid_upload`` with a generic message; the temporary file is removed."""
        try:
            staged = await stage_upload(
                upload.chunks,
                allowed=DOCUMENT_TYPES if documents else IMAGE_TYPES,
                max_bytes=(
                    self._limits.max_document_bytes if documents else self._limits.max_image_bytes
                ),
                declared_size=upload.declared_size,
                directory=self._storage.incoming_dir(),
            )
        except UploadRejectedError as exc:
            raise InvalidUploadError({"file": [exc.message]}) from None
        try:
            filename = validate_filename(upload.filename, staged.file_type)
            staged = await asyncio.to_thread(
                inspect_image, staged, max_pixels=self._limits.max_image_pixels
            )
            await asyncio.to_thread(check_pdf, staged)
        except UploadRejectedError as exc:
            await discard(staged.path)
            raise InvalidUploadError({"file": [exc.message]}) from None
        except BaseException:
            await discard(staged.path)
            raise
        return ReceivedFile(
            staged.path,
            filename,
            staged.file_type,
            staged.byte_size,
            staged.width,
            staged.height,
        )

    async def _with_new_object[T](
        self,
        namespace: Namespace,
        received: ReceivedFile,
        work: Callable[[str, Store], Awaitable[T]],
    ) -> T:
        """Run ``work(key, store)`` and commit; ``work`` calls ``store()`` after its rows
        are flushed, so constraint failures happen before any object exists.

        On any failure the transaction is rolled back and the object, if this call
        stored it, is deleted. The temporary file is always removed.
        """
        key = new_storage_key(namespace)
        stored = False

        async def store() -> None:
            nonlocal stored
            await self._storage.save(key, received.path)
            stored = True

        try:
            result = await work(key, store)
            await self._db.commit()
            return result
        except BaseException:
            await self._db.rollback()
            if stored:
                await self._storage.delete(key)
            raise
        finally:
            await asyncio.to_thread(received.path.unlink, missing_ok=True)

    async def _unit_of_work[T](self, work: Callable[[], Awaitable[T]]) -> T:
        try:
            result = await work()
            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            raise
        return result

    async def _stream(self, key: str) -> AsyncIterator[bytes]:
        """Fail before any byte is sent when the object is missing."""
        if not await self._storage.exists(key):
            # Metadata without its object is a storage fault worth an operator's look.
            logger.error("Stored object missing for file metadata")
            raise CatalogNotFoundError()
        return self._storage.stream(key)

    def _audit(
        self,
        code: AuditEventCode,
        actor: Actor,
        entity_type: str,
        entity_id: uuid.UUID,
        request_id: str | None,
        metadata: dict[str, Any],
    ) -> None:
        record_audit_event(
            self._db,
            code,
            actor_id=actor.user_id,
            request_id=request_id,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata=metadata,
        )


class MediaService(_ParentedFiles):
    """Images of a property or unit: JPEG, PNG, or WebP."""

    ENTITY_TYPE = "media"

    async def list_media(
        self,
        actor: Actor,
        parent: Parent,
        *,
        include_archived: bool = False,
        limit: int = MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> list[MediaAsset]:
        require_permissions(actor, Permission.PROPERTIES_READ)
        await self._check_parent(parent, for_change=False)
        return await MediaRepository(self._db).list(
            parent, include_archived=include_archived, limit=limit, offset=offset
        )

    async def count_media(
        self, actor: Actor, parent: Parent, *, include_archived: bool = False
    ) -> int:
        require_permissions(actor, Permission.PROPERTIES_READ)
        await self._check_parent(parent, for_change=False)
        return await MediaRepository(self._db).count(parent, include_archived=include_archived)

    async def open_media(
        self, actor: Actor, parent: Parent, media_id: uuid.UUID
    ) -> tuple[MediaAsset, AsyncIterator[bytes]]:
        require_permissions(actor, Permission.PROPERTIES_READ)
        await self._check_parent(parent, for_change=False)
        media = await self._media(parent, media_id)
        return media, await self._stream(media.storage_key)

    async def upload_media(
        self,
        actor: Actor,
        parent: Parent,
        upload: Upload,
        *,
        alt_text: str | None = None,
        request_id: str | None = None,
    ) -> MediaAsset:
        require_permissions(actor, Permission.PROPERTY_MEDIA_MANAGE)
        received = await self._receive(upload, documents=False)
        assert received.width is not None and received.height is not None

        async def work(key: str, store: Store) -> MediaAsset:
            await self._check_parent(parent, for_change=True)
            # Under the property lock, so concurrent uploads cannot pass the cap.
            ensure_below(
                await MediaRepository(self._db).count(parent),
                MAX_ACTIVE_IMAGES_PER_PARENT,
                "file",
            )
            media = MediaAsset(
                id=uuid.uuid4(),
                property_id=None if parent.unit_id else parent.property_id,
                unit_id=parent.unit_id,
                storage_key=key,
                original_filename=received.filename,
                media_type=received.file_type.value,
                byte_size=received.byte_size,
                width=received.width,
                height=received.height,
                display_order=await MediaRepository(self._db).next_display_order(parent),
                alt_text=alt_text,
                uploaded_by_id=actor.user_id,
                updated_by_id=actor.user_id,
            )
            self._db.add(media)
            await self._db.flush()
            await store()
            self._audit(
                AuditEventCode.MEDIA_UPLOADED,
                actor,
                self.ENTITY_TYPE,
                media.id,
                request_id,
                parent.audit_metadata
                | {"media_type": media.media_type, "byte_size": media.byte_size},
            )
            return media

        return await self._with_new_object("media", received, work)

    async def update_media(
        self,
        actor: Actor,
        parent: Parent,
        media_id: uuid.UUID,
        data: MediaUpdate,
        *,
        request_id: str | None = None,
    ) -> MediaAsset:
        require_permissions(actor, Permission.PROPERTY_MEDIA_MANAGE)

        async def work() -> MediaAsset:
            await self._check_parent(parent, for_change=True)
            media = await self._active_media(parent, media_id)
            changes = {
                name: value
                for name, value in data.model_dump(exclude_unset=True).items()
                if getattr(media, name) != value
            }
            if not changes:
                return media
            for name, value in changes.items():
                setattr(media, name, value)
            media.updated_by_id = actor.user_id
            await self._db.flush()
            self._audit(
                AuditEventCode.MEDIA_UPDATED,
                actor,
                self.ENTITY_TYPE,
                media.id,
                request_id,
                parent.audit_metadata | {"changed_fields": sorted(changes)},
            )
            return media

        return await self._unit_of_work(work)

    async def reorder_media(
        self, actor: Actor, parent: Parent, data: MediaOrder, *, request_id: str | None = None
    ) -> list[MediaAsset]:
        """Replace the whole order. The IDs must be exactly the parent's active images."""
        require_permissions(actor, Permission.PROPERTY_MEDIA_MANAGE)

        async def work() -> list[MediaAsset]:
            await self._check_parent(parent, for_change=True)
            repository = MediaRepository(self._db)
            current = {media.id: media for media in await repository.list(parent)}
            if set(data.media_ids) != set(current):
                raise InvalidRelationshipError({"media_ids": [ORDER_MISMATCH]})
            for position, media_id in enumerate(data.media_ids):
                current[media_id].display_order = position
            await self._db.flush()
            self._audit(
                AuditEventCode.MEDIA_REORDERED,
                actor,
                self.ENTITY_TYPE,
                data.media_ids[0],
                request_id,
                parent.audit_metadata | {"media_ids": [str(i) for i in data.media_ids]},
            )
            return await repository.list(parent)

        return await self._unit_of_work(work)

    async def set_cover(
        self, actor: Actor, parent: Parent, media_id: uuid.UUID, *, request_id: str | None = None
    ) -> MediaAsset:
        """Make one image the cover, clearing the previous cover in the same transaction."""
        require_permissions(actor, Permission.PROPERTY_MEDIA_MANAGE)

        async def work() -> MediaAsset:
            await self._check_parent(parent, for_change=True)
            media = await self._active_media(parent, media_id)
            previous = await MediaRepository(self._db).cover(parent)
            if previous is not None and previous.id == media.id:
                return media
            if previous is not None:
                previous.is_cover = False
                # Clear first: the partial unique index allows one cover per parent.
                await self._db.flush()
            media.is_cover = True
            media.updated_by_id = actor.user_id
            await self._db.flush()
            metadata = parent.audit_metadata
            if previous is not None:
                metadata |= {"previous_cover_id": str(previous.id)}
            self._audit(
                AuditEventCode.MEDIA_COVER_CHANGED,
                actor,
                self.ENTITY_TYPE,
                media.id,
                request_id,
                metadata,
            )
            return media

        return await self._unit_of_work(work)

    async def archive_media(
        self, actor: Actor, parent: Parent, media_id: uuid.UUID, *, request_id: str | None = None
    ) -> MediaAsset:
        """Archive an image (final; idempotent). It stops being the cover; the stored
        object is kept as history."""
        require_permissions(actor, Permission.PROPERTY_MEDIA_MANAGE)

        async def work() -> MediaAsset:
            await self._check_parent(parent, for_change=True)
            media = await self._media(parent, media_id)
            if media.is_archived:
                return media
            media.is_cover = False
            media.archived_at = self._clock()
            media.archived_by_id = actor.user_id
            media.updated_by_id = actor.user_id
            await self._db.flush()
            self._audit(
                AuditEventCode.MEDIA_ARCHIVED,
                actor,
                self.ENTITY_TYPE,
                media.id,
                request_id,
                parent.audit_metadata,
            )
            return media

        return await self._unit_of_work(work)

    async def _media(self, parent: Parent, media_id: uuid.UUID) -> MediaAsset:
        media = await MediaRepository(self._db).get(parent, media_id)
        if media is None:
            raise CatalogNotFoundError()
        return media

    async def _active_media(self, parent: Parent, media_id: uuid.UUID) -> MediaAsset:
        media = await self._media(parent, media_id)
        if media.is_archived:
            raise ArchivedRecordError()
        return media


class DocumentService(_ParentedFiles):
    """Private documents: PDF, or JPEG/PNG/WebP scans. Every operation needs an explicit
    ``property_documents:*`` permission; downloads are audited."""

    ENTITY_TYPE = "document"

    async def list_documents(
        self,
        actor: Actor,
        parent: Parent,
        *,
        include_archived: bool = False,
        limit: int = MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> list[Document]:
        require_permissions(actor, Permission.PROPERTY_DOCUMENTS_READ)
        await self._check_parent(parent, for_change=False)
        return await DocumentRepository(self._db).list(
            parent, include_archived=include_archived, limit=limit, offset=offset
        )

    async def count_documents(
        self, actor: Actor, parent: Parent, *, include_archived: bool = False
    ) -> int:
        require_permissions(actor, Permission.PROPERTY_DOCUMENTS_READ)
        await self._check_parent(parent, for_change=False)
        return await DocumentRepository(self._db).count(parent, include_archived=include_archived)

    async def get_document(self, actor: Actor, parent: Parent, document_id: uuid.UUID) -> Document:
        require_permissions(actor, Permission.PROPERTY_DOCUMENTS_READ)
        await self._check_parent(parent, for_change=False)
        return await self._document(parent, document_id)

    async def open_document(
        self,
        actor: Actor,
        parent: Parent,
        document_id: uuid.UUID,
        *,
        request_id: str | None = None,
    ) -> tuple[Document, AsyncIterator[bytes]]:
        require_permissions(actor, Permission.PROPERTY_DOCUMENTS_READ)

        async def work() -> tuple[Document, AsyncIterator[bytes]]:
            await self._check_parent(parent, for_change=False)
            document = await self._document(parent, document_id)
            stream = await self._stream(document.storage_key)
            self._audit(
                AuditEventCode.DOCUMENT_DOWNLOADED,
                actor,
                self.ENTITY_TYPE,
                document.id,
                request_id,
                parent.audit_metadata,
            )
            return document, stream

        return await self._unit_of_work(work)

    async def upload_document(
        self,
        actor: Actor,
        parent: Parent,
        upload: Upload,
        data: DocumentCreate,
        *,
        request_id: str | None = None,
    ) -> Document:
        require_permissions(actor, Permission.PROPERTY_DOCUMENTS_MANAGE)
        received = await self._receive(upload, documents=True)

        async def work(key: str, store: Store) -> Document:
            await self._check_parent(parent, for_change=True)
            document = Document(
                id=uuid.uuid4(),
                property_id=None if parent.unit_id else parent.property_id,
                unit_id=parent.unit_id,
                storage_key=key,
                original_filename=received.filename,
                media_type=received.file_type.value,
                byte_size=received.byte_size,
                category=data.category,
                title=data.title,
                expiry_date=data.expiry_date,
                uploaded_by_id=actor.user_id,
                updated_by_id=actor.user_id,
            )
            self._db.add(document)
            await self._db.flush()
            await store()
            self._audit(
                AuditEventCode.DOCUMENT_UPLOADED,
                actor,
                self.ENTITY_TYPE,
                document.id,
                request_id,
                parent.audit_metadata
                | {
                    "media_type": document.media_type,
                    "byte_size": document.byte_size,
                    "category": document.category.value,
                },
            )
            return document

        return await self._with_new_object("documents", received, work)

    async def update_document(
        self,
        actor: Actor,
        parent: Parent,
        document_id: uuid.UUID,
        data: DocumentUpdate,
        *,
        request_id: str | None = None,
    ) -> Document:
        require_permissions(actor, Permission.PROPERTY_DOCUMENTS_MANAGE)

        async def work() -> Document:
            await self._check_parent(parent, for_change=True)
            document = await self._changeable_document(parent, document_id, data.version)
            changes = {
                name: value
                for name, value in data.changes().items()
                if getattr(document, name) != value
            }
            if not changes:
                return document
            for name, value in changes.items():
                setattr(document, name, value)
            document.updated_by_id = actor.user_id
            await self._db.flush()
            self._audit(
                AuditEventCode.DOCUMENT_UPDATED,
                actor,
                self.ENTITY_TYPE,
                document.id,
                request_id,
                parent.audit_metadata | {"changed_fields": sorted(changes)},
            )
            return document

        return await self._unit_of_work(work)

    async def replace_document(
        self,
        actor: Actor,
        parent: Parent,
        document_id: uuid.UUID,
        upload: Upload,
        *,
        version: int,
        request_id: str | None = None,
    ) -> Document:
        """Replace the file, keeping the record and its metadata. The previous object is
        deleted only after the new one is committed."""
        require_permissions(actor, Permission.PROPERTY_DOCUMENTS_MANAGE)
        received = await self._receive(upload, documents=True)
        previous_key: str | None = None

        async def work(key: str, store: Store) -> Document:
            nonlocal previous_key
            await self._check_parent(parent, for_change=True)
            document = await self._changeable_document(parent, document_id, version)
            previous_key = document.storage_key
            document.storage_key = key
            document.original_filename = received.filename
            document.media_type = received.file_type.value
            document.byte_size = received.byte_size
            document.updated_by_id = actor.user_id
            await self._db.flush()
            await store()
            self._audit(
                AuditEventCode.DOCUMENT_REPLACED,
                actor,
                self.ENTITY_TYPE,
                document.id,
                request_id,
                parent.audit_metadata
                | {"media_type": document.media_type, "byte_size": document.byte_size},
            )
            return document

        document = await self._with_new_object("documents", received, work)
        if previous_key is not None:
            try:
                await self._storage.delete(previous_key)
            except Exception:
                # The replacement is committed; an orphaned old object is only wasted space.
                logger.exception("Could not delete a replaced document object")
        return document

    async def archive_document(
        self,
        actor: Actor,
        parent: Parent,
        document_id: uuid.UUID,
        *,
        request_id: str | None = None,
    ) -> Document:
        """Archive a document (final; idempotent). The stored object is kept."""
        require_permissions(actor, Permission.PROPERTY_DOCUMENTS_MANAGE)

        async def work() -> Document:
            await self._check_parent(parent, for_change=True)
            document = await self._document(parent, document_id)
            if document.is_archived:
                return document
            document.archived_at = self._clock()
            document.archived_by_id = actor.user_id
            document.updated_by_id = actor.user_id
            await self._db.flush()
            self._audit(
                AuditEventCode.DOCUMENT_ARCHIVED,
                actor,
                self.ENTITY_TYPE,
                document.id,
                request_id,
                parent.audit_metadata,
            )
            return document

        return await self._unit_of_work(work)

    async def _document(self, parent: Parent, document_id: uuid.UUID) -> Document:
        document = await DocumentRepository(self._db).get(parent, document_id)
        if document is None:
            raise CatalogNotFoundError()
        return document

    async def _changeable_document(
        self, parent: Parent, document_id: uuid.UUID, version: int
    ) -> Document:
        document = await self._document(parent, document_id)
        if document.is_archived:
            raise ArchivedRecordError()
        if document.version != version:
            raise StaleVersionError()
        return document
