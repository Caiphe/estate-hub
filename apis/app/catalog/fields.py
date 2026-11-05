"""Pydantic field types shared by catalog request schemas.

Each type normalizes text the same way the ORM validators and database checks expect,
so a value that passes here is stored unchanged. Length and format constraints sit on
the inner type so they never apply to ``None``; the outer ``BeforeValidator`` runs first
and turns blank optional text into ``None``.
"""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BeforeValidator, Field

from app.catalog.text import normalize_label, normalize_optional_text
from app.properties.constants import (
    ADDRESS_LINE_MAX_LENGTH,
    LOCALITY_MAX_LENGTH,
    POSTAL_CODE_MAX_LENGTH,
    REGION_MAX_LENGTH,
)

SMALLINT_MAX = 32_767
MAX_ASSIGNED_IDS = 100


def label(value: object) -> object:
    """Trim and collapse whitespace; blank becomes ``None`` (rejected if required)."""
    return (normalize_label(value) or None) if isinstance(value, str) else value


def required_label(value: object) -> object:
    """Trim and collapse whitespace, keeping blank as "" so length rules report it."""
    return normalize_label(value) if isinstance(value, str) else value


def text(value: object) -> object:
    """Trim free text; blank becomes ``None``."""
    return normalize_optional_text(value) if isinstance(value, str) else value


def unique_ids(ids: list[UUID]) -> list[UUID]:
    if len(set(ids)) != len(ids):
        raise ValueError("IDs must not repeat.")
    return ids


AddressLine = Annotated[
    str, Field(min_length=1, max_length=ADDRESS_LINE_MAX_LENGTH), BeforeValidator(required_label)
]
OptionalAddressLine = Annotated[
    Annotated[str, Field(max_length=ADDRESS_LINE_MAX_LENGTH)] | None, BeforeValidator(label)
]
Locality = Annotated[
    str, Field(min_length=1, max_length=LOCALITY_MAX_LENGTH), BeforeValidator(required_label)
]
OptionalLocality = Annotated[
    Annotated[str, Field(max_length=LOCALITY_MAX_LENGTH)] | None, BeforeValidator(label)
]
Region = Annotated[
    str, Field(min_length=1, max_length=REGION_MAX_LENGTH), BeforeValidator(required_label)
]
OptionalRegion = Annotated[
    Annotated[str, Field(max_length=REGION_MAX_LENGTH)] | None, BeforeValidator(label)
]
PostalCode = Annotated[
    Annotated[str, Field(max_length=POSTAL_CODE_MAX_LENGTH), AfterValidator(str.upper)] | None,
    BeforeValidator(label),
]
_COUNTRY = Field(
    pattern=r"^[A-Za-z]{2}$",
    description="ISO 3166-1 alpha-2 code, such as GB. Checked for shape only.",
)
CountryCode = Annotated[str, BeforeValidator(text), _COUNTRY, AfterValidator(str.upper)]
OptionalCountryCode = Annotated[
    Annotated[str, _COUNTRY, AfterValidator(str.upper)] | None, BeforeValidator(text)
]

Latitude = Annotated[
    Decimal, Field(ge=-90, le=90, max_digits=8, decimal_places=6, description="WGS 84 degrees.")
]
Longitude = Annotated[
    Decimal, Field(ge=-180, le=180, max_digits=9, decimal_places=6, description="WGS 84 degrees.")
]
Count = Annotated[int, Field(ge=0, le=SMALLINT_MAX)]
Bathrooms = Annotated[
    Decimal,
    Field(ge=0, lt=1000, multiple_of=Decimal("0.5"), description="Whole or half bathrooms."),
]
Area = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
IdSet = Annotated[
    list[UUID],
    Field(max_length=MAX_ASSIGNED_IDS, description="Replaces the whole set."),
    AfterValidator(unique_ids),
]
