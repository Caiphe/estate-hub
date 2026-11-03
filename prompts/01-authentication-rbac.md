# Prompt 01: Authentication, Staff Users, and RBAC

## Objective

Give EstateHub secure staff authentication, session management, role-based authorization, and auditable staff administration.

## Scope

- SQLAlchemy models and Alembic migration for users, roles, user-role membership, refresh sessions, and audit events.
- Initial roles: administrator, manager, agent, and accountant.
- OAuth2 password flow with Argon2id password hashing.
- Short-lived JWT access tokens and rotated, revocable refresh tokens.
- Secure browser cookie and CSRF behavior described in the design specification.
- Endpoints for login, refresh, logout, current user, password change, and administrator-managed staff accounts.
- Protected Next.js route group, login screen, session bootstrap, logout, and a minimal staff dashboard.
- Rate limiting for authentication attempts using Redis.

Do not add public customer accounts or social login.

## Required tests

- Correct and incorrect login behavior.
- Disabled-user behavior.
- Refresh rotation, reuse detection, expiry, revocation, and logout.
- Password hashing and password-change session invalidation.
- Every role's allowed and forbidden staff-administration actions.
- CSRF and cookie flags in production configuration.
- Playwright login, protected-route redirect, logout, and administrator user-management smoke flow.

## Acceptance criteria

- No protected API operation relies only on frontend checks.
- No raw refresh token or password is stored.
- Seed/bootstrap procedure creates the first administrator safely and is documented.
- Authentication errors do not disclose whether an account exists.
- Audit events cover login security events and staff/permission changes.
- All Prompt 00 checks still pass.
