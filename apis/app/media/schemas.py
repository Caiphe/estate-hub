"""Staff schemas for media and documents. No output schema has a storage key or path."""

from datetime import date, datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.catalog.fields import required_label
from app.catalog.text import normalize_optional_text
from app.media.constants import ALT_TEXT_MAX_LENGTH, DOCUMENT_TITLE_MAX_LENGTH, DocumentCategory

MAX_REORDER_ITEMS = 500


def _unique(ids: list[UUID]) -> list[UUID]:
    if len(set(ids)) != len(ids):
        raise ValueError("IDs must not repeat.")
    return ids


AltText = Annotated[
    Annotated[str, Field(max_length=ALT_TEXT_MAX_LENGTH)] | None,
    BeforeValidator(lambda v: normalize_optional_text(v) if isinstance(v, str) else v),
]
DocumentTitle = Annotated[
    str, Field(min_length=1, max_length=DOCUMENT_TITLE_MAX_LENGTH), BeforeValidator(required_label)
]


class MediaUpdate(BaseModel):
    """Only staff-authored metadata changes; the file, its key, and its type never do."""

    model_config = ConfigDict(extra="forbid")

    alt_text: AltText = None

    @model_validator(mode="after")
    def _has_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        return self


class MediaOrder(BaseModel):
    """The complete new order of a parent's active images."""

    model_config = ConfigDict(extra="forbid")

    media_ids: Annotated[
        list[UUID], Field(min_length=1, max_length=MAX_REORDER_ITEMS), AfterValidator(_unique)
    ]


class MediaPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    property_id: UUID | None
    unit_id: UUID | None
    original_filename: str
    media_type: str
    byte_size: int
    width: int
    height: int
    display_order: int
    alt_text: str | None
    is_cover: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DocumentCreate(BaseModel):
    """Metadata sent with a document upload."""

    model_config = ConfigDict(extra="forbid")

    category: DocumentCategory
    title: DocumentTitle
    expiry_date: date | None = None


class DocumentUpdate(BaseModel):
    """Partial metadata update; ``null`` clears ``expiry_date``. ``version`` must match."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    category: DocumentCategory | None = None
    title: DocumentTitle | None = None
    expiry_date: date | None = None

    @model_validator(mode="after")
    def _has_changes(self) -> Self:
        if not self.model_fields_set - {"version"}:
            raise ValueError("At least one field must be provided.")
        for name in ("category", "title"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null.")
        return self

    def changes(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.model_fields_set - {"version"}}


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    property_id: UUID | None
    unit_id: UUID | None
    category: DocumentCategory
    title: str
    original_filename: str
    media_type: str
    byte_size: int
    expiry_date: date | None
    archived_at: datetime | None
    updated_at: datetime
    version: int


class DocumentDetail(DocumentSummary):
    uploaded_by_id: UUID | None
    updated_by_id: UUID | None
    archived_by_id: UUID | None
    created_at: datetime
