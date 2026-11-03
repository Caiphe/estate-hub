import unicodedata
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from app.core.pagination import DEFAULT_PAGE_SIZE, PageLimit, PageOffset
from app.users.constants import (
    EMAIL_MAX_LENGTH,
    FULL_NAME_MAX_LENGTH,
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    RoleCode,
    UserStatus,
)

# Control characters plus line and paragraph separators never belong in a display name.
_FORBIDDEN_NAME_CATEGORIES = frozenset({"Cc", "Zl", "Zp"})


def _normalize_email(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


def _validate_full_name(value: str) -> str:
    if any(unicodedata.category(char) in _FORBIDDEN_NAME_CATEGORIES for char in value):
        raise ValueError("Name must not contain control characters.")
    return value


def _validate_password(value: SecretStr) -> SecretStr:
    # Length is counted in Unicode characters. Passwords are never trimmed or truncated.
    length = len(value.get_secret_value())
    if length < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters.")
    if length > PASSWORD_MAX_LENGTH:
        raise ValueError(f"Password must be at most {PASSWORD_MAX_LENGTH} characters.")
    return value


def _unique_roles(roles: list[RoleCode]) -> list[RoleCode]:
    return sorted(set(roles))


NormalizedEmail = Annotated[
    EmailStr,
    BeforeValidator(_normalize_email),
    Field(max_length=EMAIL_MAX_LENGTH),
]
FullName = Annotated[
    str,
    Field(min_length=1, max_length=FULL_NAME_MAX_LENGTH),
    BeforeValidator(lambda value: value.strip() if isinstance(value, str) else value),
    AfterValidator(_validate_full_name),
]
NewPassword = Annotated[SecretStr, AfterValidator(_validate_password)]
RoleCodes = Annotated[list[RoleCode], AfterValidator(_unique_roles)]


class StaffCreate(BaseModel):
    """Administrator input for creating an active staff account.

    The service hashes the password; it is never stored or returned as given.
    """

    # Rejected values (including passwords) must never be echoed into errors or logs.
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    email: NormalizedEmail
    full_name: FullName
    password: NewPassword
    roles: RoleCodes = Field(min_length=1)


class StaffUpdate(BaseModel):
    """Administrator input for a partial profile update. Omitted fields are unchanged.

    Status, roles, and passwords change only through their dedicated endpoints, so any
    other field is rejected.
    """

    # Rejected values (including passwords) must never be echoed into errors or logs.
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    email: NormalizedEmail | None = None
    full_name: FullName | None = None

    @model_validator(mode="after")
    def _reject_null_and_empty_updates(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null.")
        return self


class RoleAssignment(BaseModel):
    """The complete new role set for a staff member."""

    model_config = ConfigDict(extra="forbid")

    roles: RoleCodes = Field(min_length=1)


class StaffSort(StrEnum):
    FULL_NAME = "full_name"
    FULL_NAME_DESC = "-full_name"
    EMAIL = "email"
    EMAIL_DESC = "-email"
    CREATED_AT = "created_at"
    CREATED_AT_DESC = "-created_at"


class StaffListQuery(BaseModel):
    """Filters, ordering, and paging for the staff list. Unknown parameters are rejected."""

    model_config = ConfigDict(extra="forbid")

    status: UserStatus | None = None
    role: RoleCode | None = None
    q: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Case-insensitive search in email and full name.",
    )
    sort: StaffSort = StaffSort.FULL_NAME
    limit: PageLimit = DEFAULT_PAGE_SIZE
    offset: PageOffset = 0


class UserPublic(BaseModel):
    """Staff identity safe to return to authenticated staff."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    status: UserStatus
    roles: list[str]
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_validator("roles", mode="before")
    @classmethod
    def _role_codes(cls, roles: object) -> object:
        # ORM users carry Role objects; the API exposes only their codes.
        if isinstance(roles, list):
            return sorted(str(getattr(role, "code", role)) for role in roles)
        return roles
