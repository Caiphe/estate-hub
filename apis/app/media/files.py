"""Upload inspection. Nothing the browser says about a file is trusted.

An upload is streamed into a private temporary file with the size limit enforced on
every chunk. Its type comes from its first bytes (an allow-list of signatures); images
are then fully decoded with Pillow, which rejects truncated or corrupt data and anything
over the pixel limit. The original filename is only kept as a label: it must be a plain
name whose extension matches the content, and it never reaches a storage path.
"""

import asyncio
import os
import tempfile
import unicodedata
import warnings
from collections.abc import AsyncIterable, Collection
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.media.constants import (
    DANGEROUS_EXTENSIONS,
    EXTENSIONS,
    IMAGE_TYPES,
    ORIGINAL_FILENAME_MAX_LENGTH,
    FileType,
)

HEADER_BYTES = 16
_PILLOW_FORMATS = {FileType.JPEG: "JPEG", FileType.PNG: "PNG", FileType.WEBP: "WEBP"}


class UploadRejectedError(ValueError):
    """The file cannot be accepted. ``reason`` is a short code; messages never quote input."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def detect_file_type(header: bytes) -> FileType | None:
    if header.startswith(b"\xff\xd8\xff"):
        return FileType.JPEG
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return FileType.PNG
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return FileType.WEBP
    if header.startswith(b"%PDF-"):
        return FileType.PDF
    return None


def validate_filename(filename: str | None, file_type: FileType) -> str:
    """Return the label to keep, or reject the name.

    Rejects path separators, traversal, control characters, dangerous inner extensions,
    and a final extension that does not match the detected content.
    """
    if filename is None:
        raise UploadRejectedError("filename_missing", "The file needs a name.")
    name = unicodedata.normalize("NFC", filename).strip()
    if not name or len(name) > ORIGINAL_FILENAME_MAX_LENGTH:
        raise UploadRejectedError("filename_length", "The file name is empty or too long.")
    if "/" in name or "\\" in name or name in {".", ".."} or name.startswith("."):
        raise UploadRejectedError("filename_path", "The file name must not contain a path.")
    if any(unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"} for char in name):
        raise UploadRejectedError("filename_characters", "The file name has invalid characters.")
    stem, _, extension = name.rpartition(".")
    if not stem or extension.lower() not in EXTENSIONS[file_type]:
        raise UploadRejectedError(
            "extension_mismatch", "The file extension does not match its contents."
        )
    inner = {part.lower() for part in stem.split(".")[1:]}
    if inner & DANGEROUS_EXTENSIONS:
        raise UploadRejectedError("double_extension", "The file name has a disallowed extension.")
    return name


@dataclass(frozen=True, slots=True)
class StagedFile:
    path: Path
    file_type: FileType
    byte_size: int
    width: int | None = None
    height: int | None = None


async def stage_upload(
    chunks: AsyncIterable[bytes],
    *,
    allowed: Collection[FileType],
    max_bytes: int,
    declared_size: int | None = None,
    directory: Path | None = None,
) -> StagedFile:
    """Stream ``chunks`` into a temporary file and identify it. The caller deletes it.

    ``declared_size`` (such as a Content-Length) is checked before reading, and the real
    size on every chunk, so an oversized or lying upload is cut off without being stored.
    """
    if declared_size is not None and declared_size > max_bytes:
        raise UploadRejectedError("too_large", "The file is larger than the allowed size.")
    # Disk I/O runs in worker threads so a slow disk never blocks the event loop.
    descriptor, name = await asyncio.to_thread(tempfile.mkstemp, prefix="upload-", dir=directory)
    path = Path(name)
    try:
        size = 0
        header = b""
        handle = await asyncio.to_thread(os.fdopen, descriptor, "wb")
        try:
            async for chunk in chunks:
                size += len(chunk)
                if size > max_bytes:
                    raise UploadRejectedError(
                        "too_large", "The file is larger than the allowed size."
                    )
                if len(header) < HEADER_BYTES:
                    header += chunk[: HEADER_BYTES - len(header)]
                await asyncio.to_thread(handle.write, chunk)
        finally:
            await asyncio.to_thread(handle.close)
        if size == 0:
            raise UploadRejectedError("empty", "The file is empty.")
        file_type = detect_file_type(header)
        if file_type is None or file_type not in allowed:
            raise UploadRejectedError("unsupported_type", "This file type is not accepted.")
        return StagedFile(path, file_type, size)
    except BaseException:
        await discard(path)
        raise


async def discard(path: Path) -> None:
    await asyncio.to_thread(path.unlink, missing_ok=True)


def inspect_image(staged: StagedFile, *, max_pixels: int) -> StagedFile:
    """Fully decode an image (blocking: run in a thread) and return it with dimensions."""
    if staged.file_type not in IMAGE_TYPES:
        return staged
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(staged.path, formats=[_PILLOW_FORMATS[staged.file_type]]) as image:
                width, height = image.size
                if width < 1 or height < 1 or width * height > max_pixels:
                    raise UploadRejectedError("too_many_pixels", "The image is too large.")
                image.load()
    except UploadRejectedError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Warning) as exc:
        raise UploadRejectedError("malformed", "The image is damaged or incomplete.") from exc
    return StagedFile(staged.path, staged.file_type, staged.byte_size, width, height)


def check_pdf(staged: StagedFile) -> None:
    """A PDF must end with an end-of-file marker; a truncated upload does not."""
    if staged.file_type != FileType.PDF:
        return
    with staged.path.open("rb") as handle:
        handle.seek(max(0, staged.byte_size - 1024))
        tail = handle.read()
    if b"%%EOF" not in tail:
        raise UploadRejectedError("malformed", "The document is damaged or incomplete.")
