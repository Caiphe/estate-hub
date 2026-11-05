"""Media and private documents: upload security, ordering, covers, cleanup, and privacy."""

import asyncio
import io
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from auth_support import Sessions
from catalog_support import actor_for, audit_events, create_property
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.auth.errors import PermissionDeniedError
from app.auth.policy import Actor
from app.catalog.errors import (
    ArchivedRecordError,
    CatalogNotFoundError,
    InvalidRelationshipError,
    InvalidUploadError,
    StaleVersionError,
)
from app.media import service as media_service
from app.media.constants import DocumentCategory
from app.media.models import Document, MediaAsset
from app.media.repository import Parent
from app.media.schemas import (
    DocumentCreate,
    DocumentSummary,
    DocumentUpdate,
    MediaOrder,
    MediaPublic,
    MediaUpdate,
)
from app.media.service import DocumentService, MediaService, Upload, UploadLimits
from app.media.storage import LocalStorage, StorageError
from app.properties.constants import ManagementMode, PropertyStatus
from app.properties.schemas import UnitCreate
from app.properties.units import UnitService

LIMITS = UploadLimits(
    max_image_bytes=200_000, max_document_bytes=300_000, max_image_pixels=1_000_000
)
PDF = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


def image_bytes(fmt: str = "PNG", size: tuple[int, int] = (40, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 120, 40)).save(buffer, format=fmt)
    return buffer.getvalue()


async def chunks(data: bytes, size: int = 4096) -> AsyncIterator[bytes]:
    for start in range(0, len(data), size):
        yield data[start : start + size]


def upload(data: bytes, filename: str | None = "photo.png", **kwargs: Any) -> Upload:
    return Upload(filename=filename, chunks=chunks(data), **kwargs)


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


@pytest.fixture
async def manager(session_factory: Sessions) -> Actor:
    return await actor_for(session_factory, "manager")


@pytest.fixture
async def parent(session_factory: Sessions) -> Parent:
    return Parent(await create_property(session_factory, management_mode=ManagementMode.MIXED))


def stored_files(storage: LocalStorage) -> list[Path]:
    root = storage.incoming_dir().parent
    return sorted(p for p in root.rglob("*") if p.is_file() and ".incoming" not in p.parts)


def incoming_files(storage: LocalStorage) -> list[Path]:
    return list(storage.incoming_dir().iterdir())


async def upload_image(
    session_factory: Sessions,
    storage: LocalStorage,
    actor: Actor,
    parent: Parent,
    data: bytes | None = None,
    filename: str = "photo.png",
) -> MediaAsset:
    async with session_factory() as db:
        return await MediaService(db, storage, LIMITS).upload_media(
            actor, parent, upload(data or image_bytes(), filename)
        )


async def table_count(session_factory: Sessions, table: str) -> int:
    async with session_factory() as db:
        return int(await db.scalar(text(f"SELECT count(*) FROM {table}")) or 0)


# --- Accepted uploads -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fmt", "filename", "media_type"),
    [
        ("JPEG", "front.JPG", "image/jpeg"),
        ("PNG", "plan.png", "image/png"),
        ("WEBP", "a.webp", "image/webp"),
    ],
)
async def test_images_are_stored_with_detected_metadata(
    session_factory: Sessions,
    storage: LocalStorage,
    manager: Actor,
    parent: Parent,
    fmt: str,
    filename: str,
    media_type: str,
) -> None:
    data = image_bytes(fmt)

    media = await upload_image(session_factory, storage, manager, parent, data, filename)

    assert (media.media_type, media.width, media.height) == (media_type, 40, 30)
    assert media.byte_size == len(data)
    assert media.original_filename == filename
    assert media.property_id == parent.property_id and media.unit_id is None
    [stored] = stored_files(storage)
    assert stored.read_bytes() == data
    assert filename not in str(stored) and media.storage_key.endswith(stored.name)
    assert incoming_files(storage) == []


async def test_upload_audit_and_responses_hide_private_details(
    session_factory: Sessions, storage: LocalStorage, manager: Actor, parent: Parent
) -> None:
    media = await upload_image(session_factory, storage, manager, parent, filename="secret.png")

    [event] = await audit_events(session_factory, "media.uploaded")
    assert event.details == {
        "property_id": str(parent.property_id),
        "media_type": "image/png",
        "byte_size": media.byte_size,
    }
    rendered = json.dumps(event.details) + MediaPublic.model_validate(media).model_dump_json()
    assert media.storage_key not in rendered
    assert "storage_key" not in MediaPublic.model_fields
    assert "secret.png" not in json.dumps(event.details)


# --- Rejected uploads -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "filename", "message"),
    [
        (b"", "photo.png", "empty"),
        (b"<html><script>alert(1)</script></html>", "photo.png", "not accepted"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "logo.svg", "not accepted"),
        (b"MZ\x90\x00" + b"\x00" * 100, "photo.png", "not accepted"),
        (b"\x7fELF" + b"\x00" * 100, "photo.jpg", "not accepted"),
        (PDF, "brochure.pdf", "not accepted"),  # PDFs are documents, not images.
        (image_bytes()[:60], "photo.png", "damaged"),
        (image_bytes("JPEG")[:200], "photo.jpg", "damaged"),
        (image_bytes("PNG"), "photo.jpg", "does not match"),
        (image_bytes("PNG"), "photo.png.exe", "does not match"),
        (image_bytes("PNG"), "invoice.php.png", "disallowed extension"),
        (image_bytes("PNG"), "../../etc/photo.png", "path"),
        (image_bytes("PNG"), "..\\photo.png", "path"),
        (image_bytes("PNG"), "photo\x00.png", "invalid characters"),
        (image_bytes("PNG"), ".png", "path"),
        (image_bytes("PNG"), None, "needs a name"),
        (image_bytes("PNG", (1200, 1000)), "huge.png", "too large"),
    ],
)
async def test_unsafe_or_invalid_uploads_are_rejected(
    session_factory: Sessions,
    storage: LocalStorage,
    manager: Actor,
    parent: Parent,
    data: bytes,
    filename: str | None,
    message: str,
) -> None:
    async with session_factory() as db:
        with pytest.raises(InvalidUploadError) as error:
            await MediaService(db, storage, LIMITS).upload_media(
                manager, parent, upload(data, filename)
            )

    assert message in error.value.fields["file"][0]  # type: ignore[index]
    if filename:
        assert filename not in str(error.value.fields)
    assert stored_files(storage) == [] and incoming_files(storage) == []
    assert await table_count(session_factory, "media_assets") == 0
    assert await audit_events(session_factory, "media.uploaded") == []


async def test_spoofed_content_type_is_irrelevant(
    session_factory: Sessions, storage: LocalStorage, manager: Actor, parent: Parent
) -> None:
    # There is no way to pass a Content-Type: only the bytes decide. HTML stays HTML.
    async with session_factory() as db:
        with pytest.raises(InvalidUploadError):
            await MediaService(db, storage, LIMITS).upload_media(
                manager, parent, upload(b"<!doctype html><p>hi</p>", "photo.jpg")
            )


async def test_oversized_streams_are_cut_off(
    session_factory: Sessions, storage: LocalStorage, manager: Actor, parent: Parent
) -> None:
    received: list[int] = []

    async def endless() -> AsyncIterator[bytes]:
        yield image_bytes()[:16]
        while True:
            received.append(1)
            yield b"\x00" * 10_000

    async with session_factory() as db:
        service = MediaService(db, storage, LIMITS)
        with pytest.raises(InvalidUploadError, match="invalid_upload"):
            await service.upload_media(manager, parent, Upload("photo.png", endless()))
        # A declared size over the limit is refused before reading anything.
        with pytest.raises(InvalidUploadError):
            await service.upload_media(
                manager, parent, upload(image_bytes(), declared_size=LIMITS.max_image_bytes + 1)
            )

    assert len(received) <= LIMITS.max_image_bytes // 10_000 + 1
    assert incoming_files(storage) == []


# --- Cleanup ----------------------------------------------------------------------------


async def test_database_failure_after_storing_removes_the_object(
    session_factory: Sessions,
    storage: LocalStorage,
    manager: Actor,
    parent: Parent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(media_service, "record_audit_event", fail)

    with pytest.raises(RuntimeError):
        await upload_image(session_factory, storage, manager, parent)

    assert stored_files(storage) == [] and incoming_files(storage) == []
    assert await table_count(session_factory, "media_assets") == 0


async def test_storage_failure_leaves_no_metadata(
    session_factory: Sessions, storage: LocalStorage, manager: Actor, parent: Parent
) -> None:
    class BrokenStorage(LocalStorage):
        async def save(self, key: str, source: Path) -> None:
            raise StorageError("disk full")

    broken = BrokenStorage(storage.incoming_dir().parent)

    with pytest.raises(StorageError):
        await upload_image(session_factory, broken, manager, parent)

    assert await table_count(session_factory, "media_assets") == 0
    assert stored_files(storage) == [] and incoming_files(storage) == []


async def test_key_collision_never_deletes_the_existing_object(
    session_factory: Sessions,
    storage: LocalStorage,
    manager: Actor,
    parent: Parent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = await upload_image(session_factory, storage, manager, parent)
    monkeypatch.setattr(media_service, "new_storage_key", lambda namespace: first.storage_key)

    # The unique key fails at flush, before anything is stored (storage itself would
    # refuse with ObjectExistsError); the existing object is never deleted.
    with pytest.raises(IntegrityError, match="uq_media_assets_storage_key"):
        await upload_image(session_factory, storage, manager, parent)

    assert len(stored_files(storage)) == 1
    assert await storage.exists(first.storage_key)
    assert await table_count(session_factory, "media_assets") == 1


# --- Ordering, covers, metadata, archive ------------------------------------------------


async def test_ordering_is_deterministic_and_reorder_is_complete(
    session_factory: Sessions, storage: LocalStorage, manager: Actor, parent: Parent
) -> None:
    a, b, c = [await upload_image(session_factory, storage, manager, parent) for _ in range(3)]
    assert [a.display_order, b.display_order, c.display_order] == [0, 1, 2]

    async with session_factory() as db:
        service = MediaService(db, storage, LIMITS)
        reordered = await service.reorder_media(
            manager, parent, MediaOrder(media_ids=[c.id, a.id, b.id])
        )
        assert [m.id for m in reordered] == [c.id, a.id, b.id]
        for bad in ([c.id, a.id], [c.id, a.id, b.id, uuid.uuid4()]):
            with pytest.raises(InvalidRelationshipError):
                await service.reorder_media(manager, parent, MediaOrder(media_ids=bad))
        assert [m.id for m in await service.list_media(manager, parent)] == [c.id, a.id, b.id]

    with pytest.raises(ValidationError, match="must not repeat"):
        MediaOrder(media_ids=[a.id, a.id])


async def test_one_cover_per_parent(
    session_factory: Sessions, storage: LocalStorage, manager: Actor, parent: Parent
) -> None:
    a = await upload_image(session_factory, storage, manager, parent)
    b = await upload_image(session_factory, storage, manager, parent)

    async with session_factory() as db:
        service = MediaService(db, storage, LIMITS)
        await service.set_cover(manager, parent, a.id)
        await service.set_cover(manager, parent, b.id)
        await service.set_cover(manager, parent, b.id)  # No-op.
        covers = [m.id for m in await service.list_media(manager, parent) if m.is_cover]
        assert covers == [b.id]
        archived = await service.archive_media(manager, parent, b.id)
        assert not archived.is_cover
        assert not [m for m in await service.list_media(manager, parent) if m.is_cover]
        with pytest.raises(ArchivedRecordError):
            await service.set_cover(manager, parent, b.id)

    changes = await audit_events(session_factory, "media.cover_changed")
    assert [e.details.get("previous_cover_id") for e in changes] == [None, str(a.id)]


async def test_concurrent_cover_changes_end_with_one_cover(
    session_factory: Sessions, storage: LocalStorage, manager: Actor, parent: Parent
) -> None:
    images = [await upload_image(session_factory, storage, manager, parent) for _ in range(4)]

    async def cover(media: MediaAsset) -> None:
        async with session_factory() as db:
            await MediaService(db, storage, LIMITS).set_cover(manager, parent, media.id)

    await asyncio.gather(*(cover(m) for m in images))

    async with session_factory() as db:
        assert await db.scalar(text("SELECT count(*) FROM media_assets WHERE is_cover")) == 1


async def test_database_allows_one_cover_per_parent(
    session_factory: Sessions, storage: LocalStorage, manager: Actor, parent: Parent
) -> None:
    await upload_image(session_factory, storage, manager, parent)
    await upload_image(session_factory, storage, manager, parent)

    async with session_factory() as db:
        with pytest.raises(Exception, match="uq_media_assets_property_cover"):
            await db.execute(text("UPDATE media_assets SET is_cover = true"))


async def test_alt_text_updates_and_never_change_the_file(
    session_factory: Sessions, storage: LocalStorage, manager: Actor, parent: Parent
) -> None:
    media = await upload_image(session_factory, storage, manager, parent)

    async with session_factory() as db:
        updated = await MediaService(db, storage, LIMITS).update_media(
            manager, parent, media.id, MediaUpdate(alt_text="  Front of the house  ")
        )

    assert updated.alt_text == "Front of the house"
    assert updated.storage_key == media.storage_key
    for field in ("storage_key", "media_type", "original_filename", "is_cover"):
        with pytest.raises(ValidationError):
            MediaUpdate.model_validate({field: "x"})
    [event] = await audit_events(session_factory, "media.updated")
    assert event.details["changed_fields"] == ["alt_text"]
    assert "Front" not in json.dumps(event.details)


async def test_downloads_stream_bytes_and_missing_objects_are_not_found(
    session_factory: Sessions, storage: LocalStorage, manager: Actor, parent: Parent
) -> None:
    data = image_bytes()
    media = await upload_image(session_factory, storage, manager, parent, data)

    async with session_factory() as db:
        _, stream = await MediaService(db, storage, LIMITS).open_media(manager, parent, media.id)
        assert b"".join([chunk async for chunk in stream]) == data

    await storage.delete(media.storage_key)
    async with session_factory() as db:
        with pytest.raises(CatalogNotFoundError):
            await MediaService(db, storage, LIMITS).open_media(manager, parent, media.id)


# --- Parents ----------------------------------------------------------------------------


async def test_unit_media_belongs_to_exactly_one_parent(
    session_factory: Sessions, storage: LocalStorage, manager: Actor, parent: Parent
) -> None:
    async with session_factory() as db:
        unit = await UnitService(db).create_unit(
            manager, parent.property_id, UnitCreate(identifier="Flat 1")
        )
    unit_parent = Parent(parent.property_id, unit.id)
    other_property = Parent(await create_property(session_factory))

    media = await upload_image(session_factory, storage, manager, unit_parent)

    assert (media.property_id, media.unit_id) == (None, unit.id)
    async with session_factory() as db:
        service = MediaService(db, storage, LIMITS)
        assert await service.list_media(manager, parent) == []
        assert [m.id for m in await service.list_media(manager, unit_parent)] == [media.id]
        for wrong in (parent, Parent(other_property.property_id, unit.id)):
            with pytest.raises(CatalogNotFoundError):
                await service.open_media(manager, wrong, media.id)
    async with session_factory() as db:
        with pytest.raises(Exception, match="ck_media_assets_one_parent"):
            await db.execute(
                text("UPDATE media_assets SET property_id = :p"), {"p": parent.property_id}
            )


async def test_archived_parents_refuse_changes(
    session_factory: Sessions, storage: LocalStorage, manager: Actor
) -> None:
    archived = Parent(await create_property(session_factory, status=PropertyStatus.ARCHIVED))

    with pytest.raises(ArchivedRecordError):
        await upload_image(session_factory, storage, manager, archived)
    assert stored_files(storage) == [] and incoming_files(storage) == []


# --- Documents --------------------------------------------------------------------------


async def upload_document(
    session_factory: Sessions,
    storage: LocalStorage,
    actor: Actor,
    parent: Parent,
    data: bytes = PDF,
    filename: str = "deed.pdf",
) -> Document:
    async with session_factory() as db:
        return await DocumentService(db, storage, LIMITS).upload_document(
            actor,
            parent,
            upload(data, filename),
            DocumentCreate(category=DocumentCategory.TITLE_DEED, title=" Title  deed "),
        )


async def test_documents_accept_pdfs_and_scans_only(
    session_factory: Sessions, storage: LocalStorage, manager: Actor, parent: Parent
) -> None:
    pdf = await upload_document(session_factory, storage, manager, parent)
    scan = await upload_document(
        session_factory, storage, manager, parent, image_bytes("JPEG"), "scan.jpeg"
    )

    assert (pdf.media_type, pdf.title, pdf.version) == ("application/pdf", "Title deed", 1)
    assert scan.media_type == "image/jpeg"
    for data, name in (
        (b"PK\x03\x04" + b"\x00" * 50, "lease.docx"),
        (b"%PDF-1.7\nno end marker", "broken.pdf"),
        (b"<html></html>", "deed.pdf"),
    ):
        with pytest.raises(InvalidUploadError):
            await upload_document(session_factory, storage, manager, parent, data, name)
    [event, _] = await audit_events(session_factory, "document.uploaded")
    assert event.details == {
        "property_id": str(parent.property_id),
        "media_type": "application/pdf",
        "byte_size": len(PDF),
        "category": "title_deed",
    }


async def test_document_metadata_replacement_and_versions(
    session_factory: Sessions, storage: LocalStorage, manager: Actor, parent: Parent
) -> None:
    document = await upload_document(session_factory, storage, manager, parent)
    old_key = document.storage_key

    async with session_factory() as db:
        service = DocumentService(db, storage, LIMITS)
        updated = await service.update_document(
            manager, parent, document.id, DocumentUpdate(version=1, title="Deed (signed)")
        )
        assert updated.version == 2
        with pytest.raises(StaleVersionError):
            await service.replace_document(
                manager, parent, document.id, upload(PDF + b" ", "new.pdf"), version=1
            )
        replaced = await service.replace_document(
            manager, parent, document.id, upload(PDF + b"%%EOF\n", "deed-v2.pdf"), version=2
        )

    assert replaced.version == 3
    assert replaced.storage_key != old_key
    assert replaced.original_filename == "deed-v2.pdf"
    assert not await storage.exists(old_key)
    assert await storage.exists(replaced.storage_key)
    assert len(stored_files(storage)) == 1
    codes = [e.event_code for e in await audit_events(session_factory)]
    assert {"document.updated", "document.replaced"} <= set(codes)


async def test_failed_replacement_keeps_the_previous_file(
    session_factory: Sessions,
    storage: LocalStorage,
    manager: Actor,
    parent: Parent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = await upload_document(session_factory, storage, manager, parent)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(media_service, "record_audit_event", fail)

    async with session_factory() as db:
        with pytest.raises(RuntimeError):
            await DocumentService(db, storage, LIMITS).replace_document(
                manager, parent, document.id, upload(PDF, "deed-v2.pdf"), version=1
            )

    assert [p.name for p in stored_files(storage)] == [document.storage_key.rsplit("/", 1)[1]]


async def test_document_downloads_are_audited_and_permissioned(
    session_factory: Sessions, storage: LocalStorage, manager: Actor, parent: Parent
) -> None:
    document = await upload_document(session_factory, storage, manager, parent)

    async with session_factory() as db:
        _, stream = await DocumentService(db, storage, LIMITS).open_document(
            manager, parent, document.id
        )
        assert b"".join([c async for c in stream]) == PDF
    [event] = await audit_events(session_factory, "document.downloaded")
    assert event.details == {"property_id": str(parent.property_id)}

    for role in ("agent", "accountant"):
        actor = await actor_for(session_factory, role)
        async with session_factory() as db:
            service = DocumentService(db, storage, LIMITS)
            for call in (
                service.list_documents(actor, parent),
                service.get_document(actor, parent, document.id),
                service.open_document(actor, parent, document.id),
                service.archive_document(actor, parent, document.id),
            ):
                with pytest.raises(PermissionDeniedError):
                    await call


async def test_document_lists_hide_storage_keys_and_archived_documents(
    session_factory: Sessions, storage: LocalStorage, manager: Actor, parent: Parent
) -> None:
    kept = await upload_document(session_factory, storage, manager, parent)
    gone = await upload_document(session_factory, storage, manager, parent)

    async with session_factory() as db:
        service = DocumentService(db, storage, LIMITS)
        await service.archive_document(manager, parent, gone.id)
        current = await service.list_documents(manager, parent)
        history = await service.list_documents(manager, parent, include_archived=True)

    assert [d.id for d in current] == [kept.id]
    assert {d.id for d in history} == {kept.id, gone.id}
    rendered = json.dumps(
        [DocumentSummary.model_validate(d).model_dump(mode="json") for d in history]
    )
    assert kept.storage_key not in rendered and "storage" not in rendered
    assert await storage.exists(gone.storage_key)  # Archival keeps the object.
    for event in await audit_events(session_factory):
        assert kept.storage_key not in json.dumps(event.details)
        assert "deed.pdf" not in json.dumps(event.details)


async def test_media_permissions_by_role(
    session_factory: Sessions, storage: LocalStorage, manager: Actor, parent: Parent
) -> None:
    media = await upload_image(session_factory, storage, manager, parent)

    for role in ("agent", "accountant"):
        actor = await actor_for(session_factory, role)
        async with session_factory() as db:
            service = MediaService(db, storage, LIMITS)
            assert [m.id for m in await service.list_media(actor, parent)] == [media.id]
            with pytest.raises(PermissionDeniedError):
                await service.upload_media(actor, parent, upload(image_bytes()))
            with pytest.raises(PermissionDeniedError):
                await service.set_cover(actor, parent, media.id)
    # A denied upload never reads the stream, so nothing is staged.
    assert incoming_files(storage) == []
