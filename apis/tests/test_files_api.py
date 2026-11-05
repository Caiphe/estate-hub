"""HTTP: units, images, and private documents under a property or unit."""

import asyncio
import io
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from auth_support import assert_error, bearer, create_staff, csrf_header, login, token_for
from catalog_support import audit_events
from httpx import ASGITransport, AsyncClient, Response
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.routes.files import get_storage, get_upload_limits
from app.catalog.models import PropertyType
from app.main import app
from app.media import service as media_service
from app.media.service import UploadLimits
from app.media.storage import LocalStorage, StorageError
from app.properties.constants import ManagementMode
from app.properties.models import Property
from app.users.constants import RoleCode

Sessions = async_sessionmaker[AsyncSession]
API = "/api/v1/properties"
LIMITS = UploadLimits(
    max_image_bytes=200_000, max_document_bytes=300_000, max_image_pixels=1_000_000
)
PDF = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
EVERYONE = {r.value for r in RoleCode}
WRITERS = {"administrator", "manager"}


def image(fmt: str = "PNG", size: tuple[int, int] = (40, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (10, 120, 200)).save(buffer, format=fmt)
    return buffer.getvalue()


def sample(data: bytes | str) -> bytes:
    """Named samples are built per test; raw bytes pass through."""
    if isinstance(data, bytes):
        return data
    return {"truncated": image()[:60], "png": image(), "huge": image(size=(1200, 1000))}[data]


@pytest.fixture
def storage(tmp_path: Path, api: AsyncClient) -> Iterator[LocalStorage]:
    local = LocalStorage(tmp_path / "storage")
    app.dependency_overrides[get_storage] = lambda: local
    app.dependency_overrides[get_upload_limits] = lambda: LIMITS
    yield local


def stored(storage: LocalStorage) -> list[Path]:
    root = storage.incoming_dir().parent
    return [p for p in root.rglob("*") if p.is_file() and ".incoming" not in p.parts]


async def make_property(
    session_factory: Sessions, mode: ManagementMode = ManagementMode.MIXED
) -> uuid.UUID:
    async with session_factory() as db:
        kind = PropertyType(name=f"Type {uuid.uuid4().hex[:6]}")
        db.add(kind)
        await db.flush()
        row = Property(
            name="Rose Court",
            property_type_id=kind.id,
            management_mode=mode,
            address_line_1="1 High Street",
            locality="Bath",
            region="Somerset",
            country_code="GB",
        )
        db.add(row)
        await db.commit()
        return row.id


async def headers_for(api: AsyncClient, session_factory: Sessions, role: str) -> dict[str, str]:
    return bearer(await token_for(api, await create_staff(session_factory, [role])))


@contextmanager
def server_errors_as_responses(api: AsyncClient) -> Iterator[AsyncClient]:
    """A client that, like a real one, receives the 500 instead of the raised error, from
    the app as deployed (debug off; a local .env may turn on Starlette's traceback page)."""
    previous = app.debug
    app.debug = False
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        yield AsyncClient(transport=transport, base_url=str(api.base_url))
    finally:
        app.debug = previous


@pytest.fixture
async def admin(api: AsyncClient, session_factory: Sessions) -> dict[str, str]:
    return await headers_for(api, session_factory, "administrator")


@pytest.fixture
async def property_id(session_factory: Sessions) -> uuid.UUID:
    return await make_property(session_factory)


async def upload_image(
    api: AsyncClient,
    headers: dict[str, str],
    path: str,
    data: bytes | None = None,
    filename: str = "front.png",
    content_type: str = "image/png",
    **form: str,
) -> Response:
    return await api.post(
        path,
        files={"file": (filename, data if data is not None else image(), content_type)},
        data=form,
        headers=headers,
    )


async def upload_document(
    api: AsyncClient,
    headers: dict[str, str],
    path: str,
    *,
    data: bytes = PDF,
    filename: str = "deed.pdf",
    fields: dict[str, str] | None = None,
) -> Response:
    form = {"category": "title_deed", "title": "Title deed"} | (fields or {})
    return await api.post(
        path, files={"file": (filename, data, "application/pdf")}, data=form, headers=headers
    )


# --- Units ------------------------------------------------------------------------------


async def test_unit_crud_and_conflicts(
    api: AsyncClient, session_factory: Sessions, admin: dict[str, str], property_id: uuid.UUID
) -> None:
    units = f"{API}/{property_id}/units"

    created = await api.post(
        units, json={"identifier": "Flat 1", "internal_notes": "Key safe"}, headers=admin
    )
    unit = created.json()
    path = created.headers["location"]
    duplicate = await api.post(units, json={"identifier": " FLAT  1 "}, headers=admin)
    updated = await api.patch(path, json={"version": 1, "bedrooms": 2}, headers=admin)
    stale = await api.patch(path, json={"version": 1, "bedrooms": 3}, headers=admin)
    archived = await api.delete(path, headers=admin)
    listed = await api.get(units, headers=admin)
    history = await api.get(f"{units}?include_archived=true", headers=admin)
    reuse = await api.post(units, json={"identifier": "flat 1"}, headers=admin)
    restore_taken = await api.post(f"{path}/restore", headers=admin)

    assert created.status_code == 201 and path.endswith(f"/units/{unit['id']}")
    assert unit["internal_notes"] == "Key safe"
    assert duplicate.json()["error"]["code"] == "duplicate_reference"
    assert updated.json()["version"] == 2
    assert stale.json()["error"]["code"] == "stale_version"
    assert archived.json()["archived_at"] is not None
    assert listed.json()["items"] == [] and len(history.json()["items"]) == 1
    assert reuse.status_code == 201
    assert (
        restore_taken.status_code == 409
        and restore_taken.json()["error"]["code"] == "duplicate_reference"
    )

    accountant = await headers_for(api, session_factory, "accountant")
    seen = (await api.get(f"{units}/{reuse.json()['id']}", headers=accountant)).json()
    assert "internal_notes" not in seen


async def test_units_respect_parent_and_management_mode(
    api: AsyncClient, session_factory: Sessions, admin: dict[str, str], property_id: uuid.UUID
) -> None:
    whole = await make_property(session_factory, ManagementMode.WHOLE)
    other = await make_property(session_factory)
    unit = (
        await api.post(f"{API}/{property_id}/units", json={"identifier": "A"}, headers=admin)
    ).json()

    refused = await api.post(f"{API}/{whole}/units", json={"identifier": "A"}, headers=admin)
    elsewhere = await api.get(f"{API}/{other}/units/{unit['id']}", headers=admin)
    moved = await api.patch(
        f"{API}/{property_id}/units/{unit['id']}",
        json={"version": 1, "property_id": str(other)},
        headers=admin,
    )

    assert refused.status_code == 409 and refused.json()["error"]["code"] == "conflict"
    assert elsewhere.status_code == 404
    assert moved.status_code == 422


UNIT_ROUTES: list[tuple[str, str, dict[str, Any] | None, int, set[str]]] = [
    ("GET", "/units", None, 200, EVERYONE),
    ("POST", "/units", {"identifier": "New"}, 201, WRITERS),
    ("GET", "/units/{unit}", None, 200, EVERYONE),
    ("PATCH", "/units/{unit}", {"version": 1, "name": "Garden flat"}, 200, WRITERS),
    ("DELETE", "/units/{unit}", None, 200, WRITERS),
    ("POST", "/units/{unit}/restore", None, 200, WRITERS),
]


@pytest.mark.parametrize("role", sorted(EVERYONE))
@pytest.mark.parametrize(("method", "path", "payload", "success", "allowed"), UNIT_ROUTES)
async def test_unit_routes_for_every_role(
    api: AsyncClient,
    session_factory: Sessions,
    admin: dict[str, str],
    property_id: uuid.UUID,
    role: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    success: int,
    allowed: set[str],
) -> None:
    unit = (
        await api.post(f"{API}/{property_id}/units", json={"identifier": "A"}, headers=admin)
    ).json()

    response = await api.request(
        method,
        f"{API}/{property_id}" + path.format(unit=unit["id"]),
        json=payload,
        headers=await headers_for(api, session_factory, role),
    )

    if role in allowed:
        assert response.status_code == success, response.text
    else:
        assert_error(response, 403, "permission_denied")


# --- Images: accepted uploads and downloads ---------------------------------------------


@pytest.mark.parametrize(
    ("fmt", "filename", "media_type"),
    [
        ("PNG", "front.png", "image/png"),
        ("JPEG", "Façade été.jpg", "image/jpeg"),
        ("WEBP", 'say "cheese".webp', "image/webp"),
    ],
)
async def test_images_upload_and_download_privately(
    api: AsyncClient,
    storage: LocalStorage,
    admin: dict[str, str],
    property_id: uuid.UUID,
    fmt: str,
    filename: str,
    media_type: str,
) -> None:
    data = image(fmt)

    created = await upload_image(
        api,
        admin,
        f"{API}/{property_id}/media",
        data,
        filename,
        "application/octet-stream",
        alt_text=" Front ",
    )
    download = await api.get(created.headers["location"], headers=admin)

    body = created.json()
    assert created.status_code == 201, created.text
    assert (body["media_type"], body["width"], body["height"], body["alt_text"]) == (
        media_type,
        40,
        30,
        "Front",
    )
    assert (
        "storage_key" not in created.text and str(storage.incoming_dir().parent) not in created.text
    )
    assert download.content == data
    assert download.headers["content-type"] == media_type
    assert download.headers["x-content-type-options"] == "nosniff"
    assert download.headers["cache-control"] == "private, max-age=300"
    assert download.headers["content-security-policy"] == "default-src 'none'; sandbox"
    disposition = download.headers["content-disposition"]
    assert disposition.startswith('inline; filename="') and "filename*=UTF-8''" in disposition
    assert '"cheese"' not in disposition and "\n" not in disposition


@pytest.mark.parametrize(
    ("data", "filename", "content_type"),
    [
        (b"", "empty.png", "image/png"),
        (b"<html><script>alert(1)</script></html>", "photo.jpg", "image/jpeg"),
        (
            b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
            "logo.svg",
            "image/svg+xml",
        ),
        (b"MZ\x90\x00" + b"\x00" * 64, "setup.png", "image/png"),
        (PDF, "brochure.pdf", "application/pdf"),
        ("truncated", "photo.png", "image/png"),
        ("png", "photo.png.exe", "image/png"),
        ("png", "invoice.php.png", "image/png"),
        ("png", "../../etc/photo.png", "image/png"),
        ("png", "photo.jpg", "image/png"),
        ("huge", "huge.png", "image/png"),
    ],
)
async def test_malicious_and_invalid_images_are_rejected(
    api: AsyncClient,
    session_factory: Sessions,
    storage: LocalStorage,
    admin: dict[str, str],
    property_id: uuid.UUID,
    data: bytes | str,
    filename: str,
    content_type: str,
) -> None:
    response = await upload_image(
        api, admin, f"{API}/{property_id}/media", sample(data), filename, content_type
    )

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] in {"invalid_upload", "validation_error"}
    if error["code"] == "invalid_upload":
        assert error["fields"]["file"] and filename not in response.text
    assert stored(storage) == [] and list(storage.incoming_dir().iterdir()) == []
    async with session_factory() as db:
        assert await db.scalar(text("SELECT count(*) FROM media_assets")) == 0


async def test_oversized_uploads_are_refused(
    api: AsyncClient, storage: LocalStorage, admin: dict[str, str], property_id: uuid.UUID
) -> None:
    path = f"{API}/{property_id}/media"
    too_big = image() + b"\x00" * LIMITS.max_image_bytes

    over_type_limit = await upload_image(api, admin, path, too_big)

    async def chunked() -> AsyncIterator[bytes]:
        yield b"--x\r\n"

    no_length = await api.post(
        path,
        content=chunked(),
        headers=admin | {"content-type": "multipart/form-data; boundary=x"},
    )
    declared_huge = await api.post(
        path,
        content=b"--x--\r\n",
        headers=admin
        | {"content-type": "multipart/form-data; boundary=x", "content-length": str(10**12)},
    )

    assert over_type_limit.json()["error"]["fields"] == {
        "file": ["The file is larger than the allowed size."]
    }
    for response, message in (
        (no_length, "Uploads need a Content-Length header."),
        (declared_huge, "The file is larger than the allowed size."),
    ):
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_upload"
        assert response.json()["error"]["fields"] == {"file": [message]}
        assert response.headers["x-request-id"] == response.json()["error"]["request_id"]
    assert stored(storage) == []


# --- Images: ordering, covers, parents --------------------------------------------------


async def test_reorder_cover_and_archive(
    api: AsyncClient, storage: LocalStorage, admin: dict[str, str], property_id: uuid.UUID
) -> None:
    path = f"{API}/{property_id}/media"
    ids = [(await upload_image(api, admin, path)).json()["id"] for _ in range(3)]

    reordered = await api.put(
        f"{path}/order", json={"media_ids": [ids[2], ids[0], ids[1]]}, headers=admin
    )
    partial = await api.put(f"{path}/order", json={"media_ids": [ids[2], ids[0]]}, headers=admin)
    foreign = await api.put(
        f"{path}/order", json={"media_ids": [*ids, str(uuid.uuid4())]}, headers=admin
    )
    duplicate = await api.put(
        f"{path}/order", json={"media_ids": [ids[0], ids[0], ids[1]]}, headers=admin
    )
    first_cover = await api.post(f"{path}/{ids[0]}/cover", headers=admin)
    second_cover = await api.post(f"{path}/{ids[1]}/cover", headers=admin)
    alt = await api.patch(f"{path}/{ids[1]}", json={"alt_text": "Garden view"}, headers=admin)
    key_change = await api.patch(
        f"{path}/{ids[1]}", json={"storage_key": "media/aa/" + "a" * 32}, headers=admin
    )
    archived = await api.delete(f"{path}/{ids[1]}", headers=admin)
    listed = await api.get(path, headers=admin)
    directory = await api.get(f"{API}?q=Rose", headers=admin)

    assert [m["id"] for m in reordered.json()] == [ids[2], ids[0], ids[1]]
    assert partial.json()["error"]["code"] == "invalid_relationship"
    assert foreign.json()["error"]["code"] == "invalid_relationship"
    assert duplicate.status_code == 422
    assert first_cover.json()["is_cover"] and second_cover.json()["is_cover"]
    assert alt.json()["alt_text"] == "Garden view"
    assert key_change.status_code == 422
    assert archived.json()["is_cover"] is False
    assert [m["id"] for m in listed.json()["items"]] == [ids[2], ids[0]]
    assert directory.json()["items"][0]["cover_media_id"] is None


async def test_concurrent_cover_and_order_changes_end_valid(
    api: AsyncClient,
    session_factory: Sessions,
    storage: LocalStorage,
    admin: dict[str, str],
    property_id: uuid.UUID,
) -> None:
    path = f"{API}/{property_id}/media"
    ids = [(await upload_image(api, admin, path)).json()["id"] for _ in range(4)]
    orders = [ids, list(reversed(ids)), ids[1:] + ids[:1]]

    covers = await asyncio.gather(*(api.post(f"{path}/{m}/cover", headers=admin) for m in ids))
    reorders = await asyncio.gather(
        *(api.put(f"{path}/order", json={"media_ids": o}, headers=admin) for o in orders)
    )

    assert all(r.status_code == 200 for r in [*covers, *reorders])
    async with session_factory() as db:
        assert await db.scalar(text("SELECT count(*) FROM media_assets WHERE is_cover")) == 1
    final = [m["id"] for m in (await api.get(path, headers=admin)).json()["items"]]
    assert final in orders
    positions = [m["display_order"] for m in (await api.get(path, headers=admin)).json()["items"]]
    assert positions == [0, 1, 2, 3]


async def test_parent_mismatches_are_not_found(
    api: AsyncClient,
    session_factory: Sessions,
    storage: LocalStorage,
    admin: dict[str, str],
    property_id: uuid.UUID,
) -> None:
    other = await make_property(session_factory)
    unit = (
        await api.post(f"{API}/{property_id}/units", json={"identifier": "A"}, headers=admin)
    ).json()
    unit_media = await upload_image(api, admin, f"{API}/{property_id}/units/{unit['id']}/media")
    property_media = await upload_image(api, admin, f"{API}/{property_id}/media")
    document = await upload_document(api, admin, f"{API}/{property_id}/documents")

    for path in (
        f"{API}/{property_id}/media/{unit_media.json()['id']}/content",
        f"{API}/{other}/media/{property_media.json()['id']}/content",
        f"{API}/{other}/units/{unit['id']}/media",
        f"{API}/{property_id}/units/{unit['id']}/media/{property_media.json()['id']}/content",
        f"{API}/{other}/documents/{document.json()['id']}",
        f"{API}/{property_id}/units/{unit['id']}/documents/{document.json()['id']}/content",
    ):
        response = await api.get(path, headers=admin)
        assert response.status_code == 404, path
    assert unit_media.status_code == 201
    assert unit_media.headers["location"].endswith(
        f"/units/{unit['id']}/media/{unit_media.json()['id']}/content"
    )
    assert (await api.get(unit_media.headers["location"], headers=admin)).status_code == 200


# --- Interrupted operations -------------------------------------------------------------


async def test_storage_failure_leaves_no_metadata(
    api: AsyncClient,
    session_factory: Sessions,
    storage: LocalStorage,
    admin: dict[str, str],
    property_id: uuid.UUID,
) -> None:
    class BrokenStorage(LocalStorage):
        async def save(self, key: str, source: Path) -> None:
            raise StorageError("disk full")

    app.dependency_overrides[get_storage] = lambda: BrokenStorage(storage.incoming_dir().parent)

    with server_errors_as_responses(api) as client:
        response = await upload_image(client, admin, f"{API}/{property_id}/media")

    assert response.status_code == 500 and response.json()["error"]["code"] == "internal_error"
    assert "disk full" not in response.text
    async with session_factory() as db:
        assert await db.scalar(text("SELECT count(*) FROM media_assets")) == 0
    assert stored(storage) == [] and list(storage.incoming_dir().iterdir()) == []


async def test_database_failure_removes_the_stored_object(
    api: AsyncClient,
    session_factory: Sessions,
    storage: LocalStorage,
    admin: dict[str, str],
    property_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(media_service, "record_audit_event", fail)

    with server_errors_as_responses(api) as client:
        response = await upload_document(client, admin, f"{API}/{property_id}/documents")

    assert response.status_code == 500 and response.json()["error"]["code"] == "internal_error"
    assert "database unavailable" not in response.text
    assert stored(storage) == []
    async with session_factory() as db:
        assert await db.scalar(text("SELECT count(*) FROM documents")) == 0


async def test_missing_stored_files_are_not_found(
    api: AsyncClient, storage: LocalStorage, admin: dict[str, str], property_id: uuid.UUID
) -> None:
    created = await upload_image(api, admin, f"{API}/{property_id}/media")
    for path in stored(storage):
        path.unlink()

    response = await api.get(created.headers["location"], headers=admin)

    assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"


# --- Documents --------------------------------------------------------------------------


async def test_document_lifecycle(
    api: AsyncClient,
    session_factory: Sessions,
    storage: LocalStorage,
    admin: dict[str, str],
    property_id: uuid.UUID,
) -> None:
    documents = f"{API}/{property_id}/documents"

    created = await upload_document(
        api, admin, documents, filename="Deed (signed).pdf", fields={"expiry_date": "2030-01-31"}
    )
    path = created.headers["location"]
    download = await api.get(f"{path}/content", headers=admin)
    updated = await api.patch(path, json={"version": 1, "title": "Signed deed"}, headers=admin)
    stale_replace = await api.put(
        f"{path}/content",
        files={"file": ("v2.pdf", PDF, "application/pdf")},
        data={"version": "1"},
        headers=admin,
    )
    replaced = await api.put(
        f"{path}/content",
        files={"file": ("v2.pdf", PDF + b"%%EOF\n", "application/pdf")},
        data={"version": "2"},
        headers=admin,
    )
    listed = await api.get(documents, headers=admin)
    archived = await api.delete(path, headers=admin)
    after = await api.get(documents, headers=admin)
    history = await api.get(f"{documents}?include_archived=true", headers=admin)

    assert created.status_code == 201, created.text
    assert (created.json()["title"], created.json()["expiry_date"]) == ("Title deed", "2030-01-31")
    assert download.content == PDF
    assert download.headers["content-type"] == "application/pdf"
    assert download.headers["cache-control"] == "private, no-store"
    assert download.headers["x-content-type-options"] == "nosniff"
    assert download.headers["content-disposition"].startswith(
        'attachment; filename="Deed (signed).pdf"'
    )
    assert updated.json()["version"] == 2
    assert stale_replace.json()["error"]["code"] == "stale_version"
    assert (replaced.json()["version"], replaced.json()["original_filename"]) == (3, "v2.pdf")
    assert len(stored(storage)) == 1
    assert "storage" not in listed.text
    assert archived.json()["archived_at"] is not None
    assert after.json()["items"] == [] and len(history.json()["items"]) == 1

    events = await audit_events(session_factory)
    codes = [e.event_code for e in events]
    assert {
        "document.uploaded",
        "document.downloaded",
        "document.updated",
        "document.replaced",
        "document.archived",
    } <= set(codes)
    rendered = json.dumps([e.details for e in events])
    for private in ("Deed (signed)", "Signed deed", "Title deed", "v2.pdf", "documents/"):
        assert private not in rendered


@pytest.mark.parametrize(
    "form",
    [
        {"category": "will"},
        {"title": "   "},
        {"expiry_date": "2030-02-30"},
    ],
)
async def test_document_metadata_is_validated(
    api: AsyncClient,
    storage: LocalStorage,
    admin: dict[str, str],
    property_id: uuid.UUID,
    form: dict[str, str],
) -> None:
    response = await upload_document(api, admin, f"{API}/{property_id}/documents", fields=form)

    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_error"
    assert stored(storage) == []


FILE_ROUTES: list[tuple[str, str, str, set[str]]] = [
    ("GET", "/media", "list", EVERYONE),
    ("POST", "/media", "image", WRITERS),
    ("GET", "/media/{media}/content", "none", EVERYONE),
    ("PATCH", "/media/{media}", "alt", WRITERS),
    ("PUT", "/media/order", "order", WRITERS),
    ("POST", "/media/{media}/cover", "none", WRITERS),
    ("DELETE", "/media/{media}", "none", WRITERS),
    ("GET", "/documents", "list", WRITERS),
    ("POST", "/documents", "document", WRITERS),
    ("GET", "/documents/{document}", "none", WRITERS),
    ("GET", "/documents/{document}/content", "none", WRITERS),
    ("PATCH", "/documents/{document}", "metadata", WRITERS),
    ("PUT", "/documents/{document}/content", "replace", WRITERS),
    ("DELETE", "/documents/{document}", "none", WRITERS),
]


@pytest.mark.parametrize("parent", ["property", "unit"])
@pytest.mark.parametrize("role", sorted(EVERYONE))
@pytest.mark.parametrize(("method", "path", "body", "allowed"), FILE_ROUTES)
async def test_file_routes_for_every_role_and_parent(
    api: AsyncClient,
    session_factory: Sessions,
    storage: LocalStorage,
    admin: dict[str, str],
    property_id: uuid.UUID,
    parent: str,
    role: str,
    method: str,
    path: str,
    body: str,
    allowed: set[str],
) -> None:
    base = f"{API}/{property_id}"
    if parent == "unit":
        unit = (await api.post(f"{base}/units", json={"identifier": "A"}, headers=admin)).json()
        base = f"{base}/units/{unit['id']}"
    media = (await upload_image(api, admin, f"{base}/media")).json()
    document = (await upload_document(api, admin, f"{base}/documents")).json()
    headers = await headers_for(api, session_factory, role)
    url = base + path.format(media=media["id"], document=document["id"])

    if body == "image":
        response = await upload_image(api, headers, url)
    elif body == "document":
        response = await upload_document(api, headers, url)
    elif body == "replace":
        response = await api.put(
            url,
            files={"file": ("v2.pdf", PDF, "application/pdf")},
            data={"version": "1"},
            headers=headers,
        )
    else:
        json_body = {
            "alt": {"alt_text": "View"},
            "order": {"media_ids": [media["id"]]},
            "metadata": {"version": 1, "title": "Deed"},
        }.get(body)
        response = await api.request(method, url, json=json_body, headers=headers)

    if role in allowed:
        assert response.status_code in {200, 201}, response.text
    else:
        assert_error(response, 403, "permission_denied")


async def test_file_mutations_require_csrf_with_cookies(
    api: AsyncClient, session_factory: Sessions, storage: LocalStorage, property_id: uuid.UUID
) -> None:
    user = await create_staff(session_factory, ["manager"])
    await login(api, user.email)
    path = f"{API}/{property_id}/media"

    refused = await upload_image(api, {}, path)
    accepted = await upload_image(api, csrf_header(api), path)
    downloaded = await api.get(accepted.headers["location"])

    assert_error(refused, 403, "csrf_failed")
    assert accepted.status_code == 201 and downloaded.status_code == 200
    assert stored(storage) and len(stored(storage)) == 1


def test_openapi_documents_multipart_uploads_and_downloads() -> None:
    paths = app.openapi()["paths"]
    for prefix in (f"{API}/{{property_id}}", f"{API}/{{property_id}}/units/{{unit_id}}"):
        for upload in (f"{prefix}/media", f"{prefix}/documents"):
            content = paths[upload]["post"]["requestBody"]["content"]
            assert "multipart/form-data" in content
            assert {"401", "403", "404", "422"} <= set(paths[upload]["post"]["responses"])
        assert (
            "application/pdf"
            in paths[f"{prefix}/documents/{{document_id}}/content"]["get"]["responses"]["200"][
                "content"
            ]
        )


# --- Authentication, header safety, and image audit privacy ------------------------------


UNAUTHENTICATED = [
    *((method, "/units" + path.removeprefix("/units")) for method, path, *_ in UNIT_ROUTES),
    *((method, path) for method, path, *_ in FILE_ROUTES),
    *((method, "/units/{unit}" + path) for method, path, *_ in FILE_ROUTES),
]


@pytest.mark.parametrize(("method", "path"), UNAUTHENTICATED)
async def test_unit_and_file_routes_require_authentication(
    api: AsyncClient, storage: LocalStorage, method: str, path: str
) -> None:
    url = f"{API}/{uuid.uuid4()}" + path.format(
        media=uuid.uuid4(), document=uuid.uuid4(), unit=uuid.uuid4()
    )
    files = {"file": ("x.png", image(), "image/png")} if method in {"POST", "PUT"} else None

    response = await api.request(method, url, files=files)

    assert_error(response, 401, "authentication_required")
    # Nothing is staged or stored for an unauthenticated upload.
    assert stored(storage) == [] and list(storage.incoming_dir().iterdir()) == []


@pytest.mark.parametrize(
    "filename",
    ['quote" ; filename="evil.png', "façade (rear).png", "日本語の写真.png", "a;b,c.png"],
)
async def test_download_disposition_cannot_be_broken_by_the_name(
    api: AsyncClient,
    storage: LocalStorage,
    admin: dict[str, str],
    property_id: uuid.UUID,
    filename: str,
) -> None:
    created = await upload_image(api, admin, f"{API}/{property_id}/media", filename=filename)
    assert created.status_code == 201, created.text

    download = await api.get(created.headers["location"], headers=admin)
    disposition = download.headers["content-disposition"]

    # Exactly one quoted ASCII fallback, with no quote, semicolon, or comma inside it.
    kind, fallback, encoded = (part.strip() for part in disposition.split(";"))
    assert kind == "inline"
    assert fallback.startswith('filename="') and fallback.count('"') == 2
    assert not set(fallback[len('filename="') : -1]) & set('";,\\')
    assert encoded.startswith("filename*=UTF-8''") and not set(encoded) & set(' ";,')
    assert download.content == image()


async def test_image_audit_events_hold_no_names_text_or_keys(
    api: AsyncClient,
    session_factory: Sessions,
    storage: LocalStorage,
    admin: dict[str, str],
    property_id: uuid.UUID,
) -> None:
    path = f"{API}/{property_id}/media"
    created = (
        await upload_image(
            api, admin, path, filename="owner-bedroom.png", alt_text="Olive's bedroom"
        )
    ).json()
    await api.patch(f"{path}/{created['id']}", json={"alt_text": "Main bedroom"}, headers=admin)
    await api.post(f"{path}/{created['id']}/cover", headers=admin)

    async with session_factory() as db:
        key = await db.scalar(
            text("SELECT storage_key FROM media_assets WHERE id = :id"), {"id": created["id"]}
        )
    events = [e for e in await audit_events(session_factory) if e.event_code.startswith("media.")]
    rendered = json.dumps([e.details for e in events])

    assert [e.event_code for e in events] == [
        "media.uploaded",
        "media.updated",
        "media.cover_changed",
    ]
    for private in ("owner-bedroom", "Olive", "Main bedroom", str(key)):
        assert private not in rendered
