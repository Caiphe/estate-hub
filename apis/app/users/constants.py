from dataclasses import dataclass
from enum import StrEnum

EMAIL_MAX_LENGTH = 254
FULL_NAME_MAX_LENGTH = 200
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
ROLE_CODE_MAX_LENGTH = 50
ROLE_NAME_MAX_LENGTH = 100
ROLE_DESCRIPTION_MAX_LENGTH = 500


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class RoleCode(StrEnum):
    """Version-one role codes. Permissions for each role are defined in code, not data."""

    ADMINISTRATOR = "administrator"
    MANAGER = "manager"
    AGENT = "agent"
    ACCOUNTANT = "accountant"


@dataclass(frozen=True, slots=True)
class RoleDefinition:
    code: RoleCode
    name: str
    description: str


INITIAL_ROLES: tuple[RoleDefinition, ...] = (
    RoleDefinition(
        RoleCode.ADMINISTRATOR,
        "Administrator",
        "Full access, staff accounts, roles, reference data, and system configuration.",
    ),
    RoleDefinition(
        RoleCode.MANAGER,
        "Manager",
        "Properties, listings, deals, rentals, maintenance, reports, and approvals.",
    ),
    RoleDefinition(
        RoleCode.AGENT,
        "Agent",
        "Assigned properties, listings, contacts, inquiries, viewings, offers, and deals.",
    ),
    RoleDefinition(
        RoleCode.ACCOUNTANT,
        "Accountant",
        "Payment records, rent schedules, expenses, financial reports, and read-only "
        "property context.",
    ),
)
