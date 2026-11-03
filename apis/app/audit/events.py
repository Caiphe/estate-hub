from enum import StrEnum


class AuditEventCode(StrEnum):
    STAFF_CREATED = "staff.created"
    STAFF_PROFILE_UPDATED = "staff.profile_updated"
    STAFF_ROLES_CHANGED = "staff.roles_changed"
    STAFF_DISABLED = "staff.disabled"
    STAFF_REACTIVATED = "staff.reactivated"
    STAFF_SESSIONS_REVOKED = "staff.sessions_revoked"
