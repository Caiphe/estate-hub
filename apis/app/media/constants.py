from enum import StrEnum

ORIGINAL_FILENAME_MAX_LENGTH = 255
ALT_TEXT_MAX_LENGTH = 500
DOCUMENT_TITLE_MAX_LENGTH = 200
MEDIA_TYPE_MAX_LENGTH = 100
STORAGE_KEY_MAX_LENGTH = 64
# "<namespace>/<2 hex>/<32 hex>": random, never derived from user input.
STORAGE_KEY_PATTERN = r"^(media|documents)/[0-9a-f]{2}/[0-9a-f]{32}$"


class FileType(StrEnum):
    """Detected from file signatures, never from names or Content-Type headers."""

    JPEG = "image/jpeg"
    PNG = "image/png"
    WEBP = "image/webp"
    PDF = "application/pdf"


IMAGE_TYPES = frozenset({FileType.JPEG, FileType.PNG, FileType.WEBP})
# Scans and photos of paperwork are common, so documents also accept images.
DOCUMENT_TYPES = frozenset({FileType.PDF, *IMAGE_TYPES})
EXTENSIONS: dict[FileType, frozenset[str]] = {
    FileType.JPEG: frozenset({"jpg", "jpeg"}),
    FileType.PNG: frozenset({"png"}),
    FileType.WEBP: frozenset({"webp"}),
    FileType.PDF: frozenset({"pdf"}),
}

# Inner filename segments that suggest something executable ("invoice.php.jpg").
DANGEROUS_EXTENSIONS = frozenset(
    {
        "exe", "dll", "com", "bat", "cmd", "msi", "scr", "ps1", "vbs", "js", "mjs", "jar",
        "sh", "bash", "py", "pl", "rb", "php", "phtml", "asp", "aspx", "jsp", "cgi",
        "htm", "html", "xhtml", "svg", "svgz", "xml", "hta", "app", "apk", "dmg",
    }
)  # fmt: skip


class DocumentCategory(StrEnum):
    TITLE_DEED = "title_deed"
    SALE_AGREEMENT = "sale_agreement"
    LEASE = "lease"
    CERTIFICATE = "certificate"
    INSURANCE = "insurance"
    INSPECTION_REPORT = "inspection_report"
    FLOOR_PLAN = "floor_plan"
    INVOICE = "invoice"
    OTHER = "other"
