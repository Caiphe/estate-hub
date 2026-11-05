"""Private staff schemas for contacts. Every field here is personal data: none of these
schemas may be reused in public output, and audit metadata never copies their values."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    model_validator,
)
from pydantic_core import PydanticCustomError

from app.auth.permissions import Permission
from app.auth.policy import Actor, has_permissions
from app.catalog.fields import (
    OptionalAddressLine,
    OptionalCountryCode,
    OptionalLocality,
    OptionalRegion,
    PostalCode,
    required_label,
)
from app.catalog.text import normalize_label, normalize_optional_text
from app.contacts.constants import (
    CONTACT_NOTES_MAX_LENGTH,
    DISPLAY_NAME_MAX_LENGTH,
    EMAIL_MAX_LENGTH,
    ORGANIZATION_NAME_MAX_LENGTH,
    ContactKind,
    ContactStatus,
)
from app.contacts.models import Contact
from app.contacts.normalization import (
    InvalidTelephoneError,
    normalize_email,
    normalize_telephone,
)
from app.contacts.rules import contact_rule_errors
from app.core.pagination import DEFAULT_PAGE_SIZE, PageLimit, PageOffset


def _label(value: object) -> object:
    """Trim and collapse whitespace; blank optional text becomes None."""
    if not isinstance(value, str):
        return value
    return normalize_label(value) or None


def _text(value: object) -> object:
    return normalize_optional_text(value) if isinstance(value, str) else value


def _email(value: object) -> object:
    return (normalize_email(value) or None) if isinstance(value, str) else value


def _telephone(value: object) -> object:
    if not isinstance(value, str) or not value.strip():
        return None if isinstance(value, str) else value
    try:
        return normalize_telephone(value)
    except InvalidTelephoneError as exc:
        raise PydanticCustomError("telephone", str(exc)) from None


# Length and format constraints sit on the inner type so they never apply to None. The
# outer BeforeValidator normalizes first and turns blank optional text into None.
DisplayName = Annotated[
    str, Field(min_length=1, max_length=DISPLAY_NAME_MAX_LENGTH), BeforeValidator(required_label)
]
OrganizationName = Annotated[
    Annotated[str, Field(max_length=ORGANIZATION_NAME_MAX_LENGTH)] | None,
    BeforeValidator(_label),
]
Email = Annotated[
    Annotated[EmailStr, Field(max_length=EMAIL_MAX_LENGTH)] | None, BeforeValidator(_email)
]
Telephone = Annotated[str | None, BeforeValidator(_telephone)]
Notes = Annotated[
    Annotated[str, Field(max_length=CONTACT_NOTES_MAX_LENGTH)] | None, BeforeValidator(_text)
]


class _ContactFieldsInput(BaseModel):
    # Rejected values (emails, numbers, notes) must never be echoed into errors or logs.
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    organization_name: OrganizationName = None
    email: Email = None
    telephone: Telephone = None
    alternative_telephone: Telephone = None
    address_line_1: OptionalAddressLine = None
    address_line_2: OptionalAddressLine = None
    locality: OptionalLocality = None
    region: OptionalRegion = None
    postal_code: PostalCode = None
    country_code: OptionalCountryCode = None
    internal_notes: Notes = None


class ContactCreate(_ContactFieldsInput):
    kind: ContactKind
    display_name: DisplayName

    @model_validator(mode="after")
    def _contact_rules(self) -> Self:
        errors = contact_rule_errors(self)
        if errors:
            raise ValueError(
                " ".join(message for messages in errors.values() for message in messages)
            )
        return self


class ContactUpdate(_ContactFieldsInput):
    """Partial update. Omitted fields are unchanged; explicit ``null`` clears a field.

    ``kind`` cannot change. ``version`` must match the stored record, so a stale client
    receives ``stale_version`` instead of overwriting newer changes. Cross-field rules are
    checked by the service against the merged record.
    """

    version: int = Field(ge=1)
    display_name: DisplayName | None = None

    @model_validator(mode="after")
    def _has_changes(self) -> Self:
        if not self.model_fields_set - {"version"}:
            raise ValueError("At least one field must be provided.")
        if "display_name" in self.model_fields_set and self.display_name is None:
            raise ValueError("display_name cannot be null.")
        return self

    def changes(self) -> dict[str, object]:
        """Supplied fields only, with explicit nulls preserved."""
        return {name: getattr(self, name) for name in self.model_fields_set - {"version"}}


class ContactSummary(BaseModel):
    """A contact row for staff with ``contacts:read``. Includes email and telephone."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: ContactKind
    display_name: str
    organization_name: str | None
    email: str | None
    telephone: str | None
    status: ContactStatus
    updated_at: datetime


class ContactDetail(ContactSummary):
    alternative_telephone: str | None
    address_line_1: str | None
    address_line_2: str | None
    locality: str | None
    region: str | None
    postal_code: str | None
    country_code: str | None
    internal_notes: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="Staff note; present only with properties:read_internal.",
    )
    archived_at: datetime | None
    created_at: datetime
    version: int


def contact_view(actor: Actor, contact: Contact) -> ContactDetail:
    detail = ContactDetail.model_validate(contact)
    if not has_permissions(actor, Permission.PROPERTIES_READ_INTERNAL):
        detail.internal_notes = None
    return detail


class ContactSort(StrEnum):
    DISPLAY_NAME = "display_name"
    DISPLAY_NAME_DESC = "-display_name"
    CREATED_AT = "created_at"
    CREATED_AT_DESC = "-created_at"
    UPDATED_AT = "updated_at"
    UPDATED_AT_DESC = "-updated_at"


class ContactListQuery(BaseModel):
    """Filters, ordering, and paging for the contact list. Unknown parameters are rejected."""

    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Case-insensitive search in name, organization, email, and telephone.",
    )
    kind: ContactKind | None = None
    include_archived: bool = False
    sort: ContactSort = ContactSort.DISPLAY_NAME
    limit: PageLimit = DEFAULT_PAGE_SIZE
    offset: PageOffset = 0
