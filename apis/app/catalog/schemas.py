"""Reference-data schemas: administrator writes, administrator views, form options, and
the short summaries embedded in property and unit responses."""

from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.catalog.constants import (
    AMENITY_CATEGORY_MAX_LENGTH,
    DISPLAY_ORDER_MAX,
    REFERENCE_DESCRIPTION_MAX_LENGTH,
    REFERENCE_NAME_MAX_LENGTH,
)
from app.catalog.fields import required_label, text, unique_ids


def _category(value: object) -> object:
    normalized = text(value)
    return normalized.lower() if isinstance(normalized, str) else normalized


ReferenceName = Annotated[
    str, Field(min_length=1, max_length=REFERENCE_NAME_MAX_LENGTH), BeforeValidator(required_label)
]
ReferenceDescription = Annotated[
    Annotated[str, Field(max_length=REFERENCE_DESCRIPTION_MAX_LENGTH)] | None,
    BeforeValidator(text),
]
DisplayOrder = Annotated[int, Field(ge=0, le=DISPLAY_ORDER_MAX)]
AmenityCategory = Annotated[
    Annotated[
        str,
        Field(
            pattern=r"^[a-z][a-z_]*$",
            max_length=AMENITY_CATEGORY_MAX_LENGTH,
            description="A short grouping code such as `outdoor` or `security`.",
        ),
    ]
    | None,
    BeforeValidator(_category),
]


# --- Writes (administrators) -------------------------------------------------------------


class _ReferenceWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReferenceCreate(_ReferenceWrite):
    """A property type or a subtype. A subtype's parent type comes from the URL."""

    name: ReferenceName
    description: ReferenceDescription = None
    display_order: DisplayOrder = 0


class AmenityCreate(ReferenceCreate):
    category: AmenityCategory = None


class ReferenceUpdate(_ReferenceWrite):
    """Partial update; ``null`` clears ``description``. Activity changes only through
    disable/reactivate, and a subtype never changes its parent type."""

    name: ReferenceName | None = None
    description: ReferenceDescription = None
    display_order: DisplayOrder | None = None

    @model_validator(mode="after")
    def _has_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        for name in ("name", "display_order"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null.")
        return self

    def changes(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.model_fields_set}


class AmenityUpdate(ReferenceUpdate):
    category: AmenityCategory = None


class ReferenceOrder(_ReferenceWrite):
    """The complete new order of a reference list (types, one type's subtypes, or
    amenities). Positions become ``display_order`` values 0, 10, 20, …"""

    ids: Annotated[list[UUID], Field(min_length=1, max_length=1000), AfterValidator(unique_ids)]


class ReferenceListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_inactive: bool = Field(
        default=False,
        description="Include disabled records (requires reference_data:manage).",
    )


# --- Read shapes ------------------------------------------------------------------------
#
# One shape for every reader. Lists hold active records unless an administrator asks for
# disabled ones too; ``is_active`` tells forms which existing values can no longer be
# newly chosen.


class _ReferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PropertySubtypeRead(_ReferenceRead):
    property_type_id: UUID


class PropertyTypeRead(_ReferenceRead):
    subtypes: list[PropertySubtypeRead]


class AmenityRead(_ReferenceRead):
    category: str | None


# --- Summaries embedded in other responses ----------------------------------------------


class PropertyTypeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    is_active: bool


class SubtypeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    property_type_id: UUID
    is_active: bool


class AmenitySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    category: str | None
    is_active: bool
