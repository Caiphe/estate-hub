from enum import StrEnum


class AuditEventCode(StrEnum):
    # Authentication and security
    AUTH_LOGIN_SUCCEEDED = "auth.login_succeeded"
    AUTH_LOGIN_FAILED = "auth.login_failed"
    AUTH_RATE_LIMITED = "auth.rate_limited"
    AUTH_REFRESH_TOKEN_REUSED = "auth.refresh_token_reused"
    AUTH_LOGOUT = "auth.logout"
    AUTH_PASSWORD_CHANGED = "auth.password_changed"
    AUTH_PERMISSION_DENIED = "auth.permission_denied"
    # Staff administration
    STAFF_BOOTSTRAP_ADMIN_CREATED = "staff.bootstrap_admin_created"
    STAFF_CREATED = "staff.created"
    STAFF_PROFILE_UPDATED = "staff.profile_updated"
    STAFF_ROLES_CHANGED = "staff.roles_changed"
    STAFF_DISABLED = "staff.disabled"
    STAFF_REACTIVATED = "staff.reactivated"
    STAFF_SESSIONS_REVOKED = "staff.sessions_revoked"
