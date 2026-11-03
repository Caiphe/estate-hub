import ipaddress
import unicodedata
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
)

from app.auth.constants import (
    CLIENT_IPV4_PREFIX,
    CLIENT_IPV6_PREFIX,
    TOKEN_TYPE,
    USER_AGENT_MAX_LENGTH,
)
from app.core.security.passwords import normalize_password
from app.users.constants import PASSWORD_MAX_LENGTH
from app.users.schemas import NewPassword


class TokenResponse(BaseModel):
    """OAuth2-compatible token metadata returned by login and refresh.

    The refresh token is never part of the body; browsers receive it as an HTTP-only
    cookie.
    """

    model_config = ConfigDict(frozen=True)

    access_token: str
    token_type: Literal["bearer"] = TOKEN_TYPE
    expires_in: int = Field(gt=0, description="Access-token lifetime in seconds.")


class UserIdentity(BaseModel):
    """The public identity of an authenticated staff member."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    email: EmailStr
    full_name: str
    roles: list[str] = Field(description="Role codes, for example `administrator`.")


class EffectivePermissions(BaseModel):
    """What the current user may do, computed by the server for navigation and display.

    The API enforces permissions on every request; clients must not treat this as
    authorization.
    """

    model_config = ConfigDict(frozen=True)

    roles: list[str]
    permissions: list[str]


class ClientMetadata(BaseModel):
    """Privacy-conscious request origin stored with a refresh session.

    Built from raw request values: the user agent is cleaned and truncated, and the
    client address is reduced to its network prefix. Invalid input becomes ``None``
    rather than failing sign-in.
    """

    model_config = ConfigDict(frozen=True)

    user_agent: str | None = None
    client_ip_prefix: str | None = None

    @classmethod
    def from_request_values(cls, user_agent: str | None, client_ip: str | None) -> ClientMetadata:
        return cls(
            user_agent=_summarize_user_agent(user_agent), client_ip_prefix=_ip_prefix(client_ip)
        )

    @field_validator("user_agent")
    @classmethod
    def _bounded_user_agent(cls, value: str | None) -> str | None:
        return _summarize_user_agent(value)


class PasswordChange(BaseModel):
    """Self-service password change.

    The new password must be 12-128 characters. Spaces and passphrases are allowed, and
    nothing is trimmed or truncated. Rejected values are never echoed in errors.
    """

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    current_password: SecretStr = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    new_password: NewPassword
    new_password_confirmation: SecretStr

    @field_validator("new_password")
    @classmethod
    def _differs_from_current(cls, value: SecretStr, info: ValidationInfo) -> SecretStr:
        current = info.data.get("current_password")
        if current is not None and normalize_password(
            value.get_secret_value()
        ) == normalize_password(current.get_secret_value()):
            raise ValueError("The new password must differ from the current password.")
        return value

    @field_validator("new_password_confirmation")
    @classmethod
    def _matches_new_password(cls, value: SecretStr, info: ValidationInfo) -> SecretStr:
        new = info.data.get("new_password")
        if new is not None and normalize_password(value.get_secret_value()) != normalize_password(
            new.get_secret_value()
        ):
            raise ValueError("The confirmation does not match the new password.")
        return value


def _summarize_user_agent(value: str | None) -> str | None:
    if value is None:
        return None
    printable = "".join(" " if unicodedata.category(char)[0] == "C" else char for char in value)
    summary = " ".join(printable.split())[:USER_AGENT_MAX_LENGTH]
    return summary or None


def _ip_prefix(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    prefix = CLIENT_IPV4_PREFIX if address.version == 4 else CLIENT_IPV6_PREFIX
    return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False))
