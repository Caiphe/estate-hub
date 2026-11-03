"""Permission codes and the version-one role-permission matrix.

Permissions live in code, not in the database: role rows only name a role. Changing the
matrix is a reviewed code change, and `tests/test_authorization.py` pins every cell.
"""

from collections.abc import Iterable, Mapping
from enum import StrEnum
from types import MappingProxyType

from app.users.constants import RoleCode


class Permission(StrEnum):
    # Staff accounts
    STAFF_READ = "staff:read"
    STAFF_CREATE = "staff:create"
    STAFF_UPDATE = "staff:update"
    STAFF_DISABLE = "staff:disable"
    STAFF_REACTIVATE = "staff:reactivate"
    STAFF_ASSIGN_ROLES = "staff:assign_roles"
    STAFF_REVOKE_SESSIONS = "staff:revoke_sessions"
    # Authentication and security audit events
    AUDIT_READ = "audit:read"
    # Future domain areas: stable names now, enforced by later prompts.
    PROPERTIES_READ = "properties:read"
    PROPERTIES_MANAGE = "properties:manage"
    LISTINGS_READ = "listings:read"
    LISTINGS_MANAGE = "listings:manage"
    LISTINGS_PUBLISH = "listings:publish"
    CONTACTS_READ = "contacts:read"
    CONTACTS_MANAGE = "contacts:manage"
    DEALS_READ = "deals:read"
    DEALS_MANAGE = "deals:manage"
    RENTALS_READ = "rentals:read"
    RENTALS_MANAGE = "rentals:manage"
    PAYMENTS_READ = "payments:read"
    PAYMENTS_MANAGE = "payments:manage"
    EXPENSES_READ = "expenses:read"
    EXPENSES_MANAGE = "expenses:manage"
    MAINTENANCE_READ = "maintenance:read"
    MAINTENANCE_MANAGE = "maintenance:manage"
    REPORTS_OPERATIONAL = "reports:operational"
    REPORTS_FINANCIAL = "reports:financial"
    CONFIGURATION_MANAGE = "configuration:manage"


P = Permission

ROLE_PERMISSIONS: Mapping[RoleCode, frozenset[Permission]] = MappingProxyType(
    {
        RoleCode.ADMINISTRATOR: frozenset(Permission),
        # Operational management. Can see staff (to assign work) but not administer
        # accounts, roles, or sessions.
        RoleCode.MANAGER: frozenset(
            {
                P.STAFF_READ,
                P.PROPERTIES_READ,
                P.PROPERTIES_MANAGE,
                P.LISTINGS_READ,
                P.LISTINGS_MANAGE,
                P.LISTINGS_PUBLISH,
                P.CONTACTS_READ,
                P.CONTACTS_MANAGE,
                P.DEALS_READ,
                P.DEALS_MANAGE,
                P.RENTALS_READ,
                P.RENTALS_MANAGE,
                P.PAYMENTS_READ,
                P.EXPENSES_READ,
                P.MAINTENANCE_READ,
                P.MAINTENANCE_MANAGE,
                P.REPORTS_OPERATIONAL,
                P.REPORTS_FINANCIAL,
            }
        ),
        # Sales work. Restricting agents to *assigned* records is row-level scoping that
        # the domain prompts add on top of these permissions.
        RoleCode.AGENT: frozenset(
            {
                P.PROPERTIES_READ,
                P.LISTINGS_READ,
                P.LISTINGS_MANAGE,
                P.CONTACTS_READ,
                P.CONTACTS_MANAGE,
                P.DEALS_READ,
                P.DEALS_MANAGE,
            }
        ),
        # Financial work with read-only property and rental context.
        RoleCode.ACCOUNTANT: frozenset(
            {
                P.PROPERTIES_READ,
                P.RENTALS_READ,
                P.PAYMENTS_READ,
                P.PAYMENTS_MANAGE,
                P.EXPENSES_READ,
                P.EXPENSES_MANAGE,
                P.REPORTS_FINANCIAL,
            }
        ),
    }
)


def permissions_for_roles(role_codes: Iterable[str]) -> frozenset[Permission]:
    """Union of the permissions of every known role. Unknown role codes grant nothing."""
    granted: set[Permission] = set()
    for code in role_codes:
        try:
            role = RoleCode(code)
        except ValueError:
            continue
        granted |= ROLE_PERMISSIONS[role]
    return frozenset(granted)


def render_matrix_markdown() -> str:
    """The matrix as a Markdown table; the README embeds this exact text."""
    roles = list(RoleCode)
    lines = [
        "| Permission | " + " | ".join(role.value for role in roles) + " |",
        "| --- |" + " :---: |" * len(roles),
    ]
    for permission in Permission:
        cells = ("✓" if permission in ROLE_PERMISSIONS[role] else "" for role in roles)
        lines.append(f"| `{permission.value}` | " + " | ".join(cells) + " |")
    return "\n".join(lines)
