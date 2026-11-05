"""Object storage behind a small interface, so object storage can replace the local
volume later without changing domain code.

Keys are generated here from a CSPRNG and validated on every call; callers never build
paths. The local implementation writes uploads to ``<root>/.incoming`` (the same
filesystem as the objects) and links them into place, so an object appears atomically
and an existing object is never overwritten.
"""

import asyncio
import errno
import os
import re
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal, Protocol

from app.media.constants import STORAGE_KEY_PATTERN

Namespace = Literal["media", "documents"]
CHUNK_SIZE = 64 * 1024
_KEY = re.compile(STORAGE_KEY_PATTERN)


class StorageError(Exception):
    """A storage operation failed. Messages never contain paths."""


class InvalidStorageKeyError(StorageError):
    pass


class ObjectExistsError(StorageError):
    pass


class ObjectMissingError(StorageError):
    pass


def new_storage_key(namespace: Namespace) -> str:
    token = secrets.token_hex(16)
    return f"{namespace}/{token[:2]}/{token}"


def check_key(key: str) -> str:
    if not _KEY.fullmatch(key):
        raise InvalidStorageKeyError("The storage key is invalid.")
    return key


class ObjectStorage(Protocol):
    def incoming_dir(self) -> Path:
        """Where upload intake writes temporary files (same filesystem as objects)."""
        ...

    async def save(self, key: str, source: Path) -> None:
        """Move ``source`` into storage under ``key``; never overwrites."""
        ...

    def stream(self, key: str) -> AsyncIterator[bytes]: ...

    async def exists(self, key: str) -> bool: ...

    async def delete(self, key: str) -> None:
        """Remove an object. Missing objects are ignored."""
        ...


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def incoming_dir(self) -> Path:
        path = self._root / ".incoming"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _path(self, key: str) -> Path:
        path = (self._root / check_key(key)).resolve()
        # Defence in depth: the key pattern already excludes "..", separators, and NULs.
        if not path.is_relative_to(self._root):
            raise InvalidStorageKeyError("The storage key is invalid.")
        return path

    async def save(self, key: str, source: Path) -> None:
        target = self._path(key)

        def work() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                # link() fails if the target exists: an atomic "create, never replace".
                os.link(source, target)
            except FileExistsError:
                raise ObjectExistsError("An object with this key already exists.") from None
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    raise StorageError("The object could not be stored.") from exc
                _copy_exclusive(source, target)
            source.unlink(missing_ok=True)

        await asyncio.to_thread(work)

    async def stream(self, key: str) -> AsyncIterator[bytes]:
        path = self._path(key)
        try:
            handle = await asyncio.to_thread(path.open, "rb")
        except FileNotFoundError:
            raise ObjectMissingError("The stored object is missing.") from None
        try:
            while chunk := await asyncio.to_thread(handle.read, CHUNK_SIZE):
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)


def _copy_exclusive(source: Path, target: Path) -> None:
    """Fallback when source and target are on different filesystems."""
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    except FileExistsError:
        raise ObjectExistsError("An object with this key already exists.") from None
    try:
        with os.fdopen(descriptor, "wb") as out, source.open("rb") as src:
            while chunk := src.read(CHUNK_SIZE):
                out.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
