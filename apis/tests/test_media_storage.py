"""The storage contract, run against a temporary directory."""

import os
import re
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.media.constants import STORAGE_KEY_PATTERN
from app.media.storage import (
    InvalidStorageKeyError,
    LocalStorage,
    ObjectExistsError,
    ObjectMissingError,
    new_storage_key,
)


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


def staged(storage: LocalStorage, data: bytes) -> Path:
    path = storage.incoming_dir() / f"upload-{len(data)}"
    path.write_bytes(data)
    return path


async def read(storage: LocalStorage, key: str) -> bytes:
    return b"".join([chunk async for chunk in storage.stream(key)])


def test_keys_are_random_and_namespaced() -> None:
    keys = {new_storage_key("media") for _ in range(1000)}

    assert len(keys) == 1000
    assert all(re.fullmatch(STORAGE_KEY_PATTERN, key) for key in keys)
    assert new_storage_key("documents").startswith("documents/")


async def test_save_stream_exists_and_delete(storage: LocalStorage, tmp_path: Path) -> None:
    key = new_storage_key("media")
    source = staged(storage, b"x" * 200_000)

    await storage.save(key, source)

    assert not source.exists()
    assert await storage.exists(key)
    assert await read(storage, key) == b"x" * 200_000
    assert (tmp_path / "storage" / key).is_file()
    await storage.delete(key)
    await storage.delete(key)  # Idempotent.
    assert not await storage.exists(key)


async def test_existing_objects_are_never_overwritten(storage: LocalStorage) -> None:
    key = new_storage_key("documents")
    await storage.save(key, staged(storage, b"original"))
    second = staged(storage, b"replacement")

    with pytest.raises(ObjectExistsError):
        await storage.save(key, second)

    assert await read(storage, key) == b"original"
    assert second.exists()


async def test_missing_objects_raise_without_paths(storage: LocalStorage, tmp_path: Path) -> None:
    key = new_storage_key("media")

    with pytest.raises(ObjectMissingError) as error:
        await read(storage, key)

    assert str(tmp_path) not in str(error.value)
    assert key not in str(error.value)


@pytest.mark.parametrize(
    "key",
    [
        "../etc/passwd",
        "media/../../etc/passwd",
        "/etc/passwd",
        "media/ab/" + "a" * 31,
        "media/AB/" + "A" * 32,
        "other/ab/" + "a" * 32,
        "media/ab/" + "a" * 32 + "\x00",
        "media\\ab\\" + "a" * 32,
        "",
    ],
)
async def test_invalid_keys_are_refused(storage: LocalStorage, key: str) -> None:
    with pytest.raises(InvalidStorageKeyError):
        await storage.exists(key)
    with pytest.raises(InvalidStorageKeyError):
        await storage.delete(key)


def test_incoming_files_share_the_storage_filesystem(storage: LocalStorage, tmp_path: Path) -> None:
    # Staged uploads live under the root (the Docker media_data volume), so moving them
    # into place is a link on one filesystem rather than a copy across volumes.
    assert storage.incoming_dir().is_relative_to(tmp_path / "storage")


async def test_configured_root_round_trips_on_one_filesystem() -> None:
    """In Docker this root is the media_data volume (/app/storage). Staging and objects
    share its filesystem, so saving is an atomic link and survives API restarts."""
    storage = LocalStorage(get_settings().media_storage_root)
    key = new_storage_key("documents")
    source = staged(storage, b"%PDF-1.7\n%%EOF\n")
    root = storage.incoming_dir().parent
    try:
        await storage.save(key, source)
        assert await read(storage, key) == b"%PDF-1.7\n%%EOF\n"
        assert os.stat(root / key).st_dev == os.stat(storage.incoming_dir()).st_dev
        assert os.stat(root / key).st_nlink == 1  # Linked in, then the staged name removed.
    finally:
        await storage.delete(key)
