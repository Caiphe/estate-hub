"""Stable error codes for the property catalog.

Codes are public and shared by reference data, contacts, properties, ownership, units,
media, and documents. Services raise ``CatalogError`` subclasses; routes translate them
with ``CATALOG_ERRORS``. Messages are generic: specifics go in ``fields``, never values
from private records.
"""

from dataclasses import dataclass
from enum import StrEnum

from fastapi import status

from app.auth.constants import AuthErrorCode


class CatalogErrorCode(StrEnum):
    # The same code as request-shape validation; raised when a rule needs stored state,
    # such as a PATCH that would leave a contact with no contact method.
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    DUPLICATE_REFERENCE = "duplicate_reference"
    INVALID_RELATIONSHIP = "invalid_relationship"
    ARCHIVED_RECORD = "archived_record"
    CONFLICT = "conflict"
    DEPENDENCY_CONFLICT = "dependency_conflict"
    STALE_VERSION = "stale_version"
    INVALID_UPLOAD = "invalid_upload"
    # The same public code as every other denial; raised as auth's PermissionDeniedError.
    PERMISSION_DENIED = AuthErrorCode.PERMISSION_DENIED.value


@dataclass(frozen=True, slots=True)
class CatalogErrorSpec:
    status_code: int
    message: str


CATALOG_ERRORS: dict[CatalogErrorCode, CatalogErrorSpec] = {
    CatalogErrorCode.VALIDATION_ERROR: CatalogErrorSpec(
        status.HTTP_422_UNPROCESSABLE_CONTENT, "The request contains invalid data."
    ),
    # Also returned for a record under the wrong parent, so IDs cannot be probed across
    # properties.
    CatalogErrorCode.NOT_FOUND: CatalogErrorSpec(
        status.HTTP_404_NOT_FOUND, "The requested record was not found."
    ),
    CatalogErrorCode.DUPLICATE_REFERENCE: CatalogErrorSpec(
        status.HTTP_409_CONFLICT, "A record with this value already exists."
    ),
    # A referenced record is unknown, inactive, or incompatible (for example a subtype of
    # another type). It is part of the request, so it is a field error.
    CatalogErrorCode.INVALID_RELATIONSHIP: CatalogErrorSpec(
        status.HTTP_422_UNPROCESSABLE_CONTENT, "A referenced record cannot be used here."
    ),
    CatalogErrorCode.ARCHIVED_RECORD: CatalogErrorSpec(
        status.HTTP_409_CONFLICT, "The record is archived. Restore it before changing it."
    ),
    CatalogErrorCode.CONFLICT: CatalogErrorSpec(
        status.HTTP_409_CONFLICT, "The change conflicts with the current state of the record."
    ),
    CatalogErrorCode.DEPENDENCY_CONFLICT: CatalogErrorSpec(
        status.HTTP_409_CONFLICT, "Other records depend on this one, so it cannot be changed."
    ),
    CatalogErrorCode.STALE_VERSION: CatalogErrorSpec(
        status.HTTP_409_CONFLICT,
        "The record was changed by someone else. Reload it and review the changes.",
    ),
    CatalogErrorCode.INVALID_UPLOAD: CatalogErrorSpec(
        status.HTTP_422_UNPROCESSABLE_CONTENT, "The file cannot be accepted."
    ),
    CatalogErrorCode.PERMISSION_DENIED: CatalogErrorSpec(
        status.HTTP_403_FORBIDDEN, "You do not have permission to perform this action."
    ),
}


class CatalogError(Exception):
    """A catalog business failure with a stable public code and optional field errors."""

    code = CatalogErrorCode.CONFLICT

    def __init__(self, fields: dict[str, list[str]] | None = None) -> None:
        super().__init__(self.code.value)
        self.fields = fields

    @property
    def status_code(self) -> int:
        return CATALOG_ERRORS[self.code].status_code

    @property
    def message(self) -> str:
        return CATALOG_ERRORS[self.code].message


class CatalogValidationError(CatalogError):
    code = CatalogErrorCode.VALIDATION_ERROR


class CatalogNotFoundError(CatalogError):
    code = CatalogErrorCode.NOT_FOUND


class DuplicateReferenceError(CatalogError):
    code = CatalogErrorCode.DUPLICATE_REFERENCE


class InvalidRelationshipError(CatalogError):
    code = CatalogErrorCode.INVALID_RELATIONSHIP


class ArchivedRecordError(CatalogError):
    code = CatalogErrorCode.ARCHIVED_RECORD


class CatalogConflictError(CatalogError):
    code = CatalogErrorCode.CONFLICT


class DependencyConflictError(CatalogError):
    code = CatalogErrorCode.DEPENDENCY_CONFLICT


class StaleVersionError(CatalogError):
    code = CatalogErrorCode.STALE_VERSION


class InvalidUploadError(CatalogError):
    code = CatalogErrorCode.INVALID_UPLOAD
