# EstateHub API

The backend is a modular FastAPI application using Pydantic v2, SQLAlchemy 2.x, PostgreSQL, Alembic, Redis, and Celery.

The foundation currently exposes liveness and readiness endpoints. Business modules are added through the sequential prompts at the repository root.

## Dependencies

Dependencies are declared in `pyproject.toml` and pinned in `uv.lock`. Docker images install with `uv sync --locked`, so the build fails if the lock is stale. After changing dependencies, regenerate the lock (no local uv install needed):

```bash
docker run --rm -v "$PWD":/app -w /app ghcr.io/astral-sh/uv:0.9-python3.14-bookworm-slim uv lock
```

## Conventions

- `GET /api/v1/health/live` reports process health only; `GET /api/v1/health/ready` returns 503 unless PostgreSQL and Redis are reachable.
- Every response carries an `X-Request-ID` header. A client-supplied ID is reused only if it is 1–128 characters of `A-Z a-z 0-9 . _ -`; otherwise a UUID is generated.
- All errors use the standard body `{"error": {"code", "message", "fields", "request_id"}}` (see `app/core/errors.py`). Unhandled exceptions are logged and returned as a generic `internal_error`.
- Migrations are reviewed by hand after autogeneration. They copy values such as enum members and seed rows instead of importing application code, and they write every constraint name explicitly. `tests/test_auth_migration.py` upgrades a temporary database, compares it with the models, runs `alembic check`, and downgrades and upgrades again.
- The four initial roles are seeded by migration `20261103_0001` with fixed IDs (`uuid5(NAMESPACE_URL, "urn:estatehub:role:<code>")`). Role permissions live in code, not in the database.
- `ESTATEHUB_CORS_ORIGINS` must list explicit origins. Wildcards are rejected, and staging/production require HTTPS origins.

## Authentication contract

Staff authentication is being built in stages (see `prompts/01-authentication-rbac.md`). The contracts below are fixed now; the endpoints arrive in later stages.

### Transport

- **Login** (`POST /api/v1/auth/token`) accepts OAuth2 password-form fields (`application/x-www-form-urlencoded` with `username` = email and `password`).
- Login and refresh return OAuth2-compatible token metadata (`app/auth/schemas.py::TokenResponse`): `{"access_token", "token_type": "bearer", "expires_in"}`. The refresh token is never in a response body.
- Browsers receive three cookies: the access token and the refresh token (both `HttpOnly`), and a CSRF token that frontend JavaScript can read.
- API clients and the OpenAPI UI may instead send `Authorization: Bearer <access token>`.
- Cookie-authenticated unsafe requests (anything except `GET`, `HEAD`, `OPTIONS`) must send the CSRF cookie value in the `X-CSRF-Token` header. Bearer-authenticated requests are exempt.
- The authenticated identity shape is `app/auth/schemas.py::UserIdentity`: `id`, `email`, `full_name`, `roles`.

### Error codes

Errors use the standard body (`app/core/errors.py::ErrorResponse`). Authentication codes are defined in `app/auth/constants.py`:

| Code | Status | Meaning |
| --- | --- | --- |
| `invalid_credentials` | 401 | Login failed. Unknown email, wrong password, and disabled account all return this. |
| `authentication_required` | 401 | No access token was supplied. |
| `invalid_token` | 401 | The access token is malformed, tampered with, or no longer valid for its user. |
| `token_expired` | 401 | The access token expired; the client should refresh. |
| `invalid_session` | 401 | The refresh session is unknown, expired, revoked, or reused. Sign in again. |
| `csrf_failed` | 403 | The CSRF header is missing or does not match the cookie. |
| `permission_denied` | 403 | Authenticated, but the role does not allow the action. |
| `auth_rate_limited` | 429 | Too many attempts; see `Retry-After`. |
| `auth_service_unavailable` | 503 | A dependency needed for sign-in (Redis) is unavailable. |

Messages are generic and never reveal whether an account exists. Detailed reasons are recorded only in audit events.

### Endpoints

| Endpoint | Input | Success | Failure |
| --- | --- | --- | --- |
| `POST /api/v1/auth/token` | Form `username`, `password` | `200` `TokenResponse`, sets all three cookies, `Cache-Control: no-store` | `401 invalid_credentials` (identical for unknown, wrong, or disabled), no cookies |
| `POST /api/v1/auth/refresh` | Refresh cookie and `X-CSRF-Token` header | `200` `TokenResponse`, replaces all three cookies | `403 csrf_failed` (cookies kept), or `401 invalid_session` with cookies cleared |
| `POST /api/v1/auth/logout` | Refresh cookie and `X-CSRF-Token` header, if signed in | `204`, session revoked, cookies cleared, idempotent | `403 csrf_failed` when a refresh cookie is sent without a valid header |

| `GET /api/v1/auth/me` | Access token (bearer or cookie) | `200` `UserPublic`: id, email, name, status, role codes, timestamps | `401` `authentication_required`, `token_expired`, or `invalid_token` |
| `POST /api/v1/auth/change-password` | JSON `current_password`, `new_password`, `new_password_confirmation`; CSRF header when cookie-authenticated | `204`; password replaced, all sessions revoked, token version incremented, cookies cleared | `422 validation_error` or `422 current_password_incorrect` with field errors; nothing changes |

**Password policy.** 12–128 Unicode characters. Spaces and passphrases are allowed, nothing is trimmed or truncated, and input is NFKC-normalized before hashing and comparison. The new password must differ from the current one, and the confirmation must match. Errors name the field and never echo values. Checking against breached-password lists is deferred: it needs either an offline list or a privacy-preserving lookup, and no password may be sent to an external service.

A password change is one transaction: the user row is locked, the current password verified, the new hash written, every refresh session revoked (`password_changed`), and the token version incremented. If any step fails, nothing changes and the old password keeps working.

Refresh accepts the cookie only. API clients using bearer tokens sign in again when the 15-minute access token expires.

**Cookies.** Access (`HttpOnly`, path `/`, 15 minutes); refresh (`HttpOnly`, path `/api/v1/auth`, until the session family expires); CSRF (readable by scripts, path `/`, same lifetime as refresh). `Secure`, `SameSite`, and `Domain` come from settings. Deletion repeats the same attributes.

**Authenticated requests** (`app/auth/dependencies.py::get_current_identity`). If an `Authorization` header is present it is used exclusively; a non-Bearer or invalid value fails and never falls back to the cookie. Otherwise the access cookie is used, and unsafe methods also need `X-CSRF-Token` to match the CSRF cookie. Missing, duplicated, malformed, or mismatched values return `403 csrf_failed`. The user is reloaded on each request, and a disabled account or changed token version returns `401 invalid_token`.

If the auth secrets are missing in development, auth endpoints return `503 auth_service_unavailable` and log the cause. SQL echo (`ESTATEHUB_DEBUG`) never logs bound parameters.

### Security primitives

`app/core/security/` contains pure functions with no FastAPI, database, Redis, or cookie dependencies:

- `passwords.py`: Argon2id via `pwdlib` (t=3, m=64 MiB, p=4). Input is NFKC-normalized and never trimmed or truncated. `verify_password` returns a replacement hash when the stored hash uses outdated parameters. `verify_dummy_password` spends the same work for unknown accounts.
- `access_tokens.py`: HS256/384/512 JWTs via PyJWT with claims `iss`, `aud`, `sub` (user UUID), `iat`, `nbf`, `exp`, `jti`, `typ="access"`, and `ver` (token version). Role codes are not included; authorization reads current roles from the database. Only the configured algorithm is accepted, and time claims are checked against an injectable clock.
- `opaque_tokens.py`: refresh and CSRF tokens are 256-bit `secrets.token_urlsafe` values. Refresh tokens are stored as HMAC-SHA256 hex digests keyed by `REFRESH_TOKEN_HASH_SECRET`. Comparisons are constant-time.
- Failures raise `app/core/security/exceptions.py` types carrying a non-sensitive `reason` code. Library exceptions are not chained.

### Session service

`app/auth/service.py::AuthService` handles login (`authenticate`), refresh rotation (`refresh`), `logout`, and `revoke_all_sessions`. Each method is one transaction that commits on success and rolls back on failure. Repositories (`app/auth/repository.py`, `app/users/repository.py`) never commit. `invalidate_user_sessions` revokes every session and increments the token version without committing, for use inside other workflows' transactions.

- **Refresh rotation:** the session row is locked (`SELECT … FOR UPDATE`), the parent is revoked as `rotated`, and one child is created in the same family. The child keeps the family's absolute expiry, so refreshing never extends a login beyond `REFRESH_SESSION_TTL_DAYS`.
- **Reuse within 10 seconds of rotation:** the request fails with a conflict and gets no tokens. This covers two tabs refreshing at once.
- **Reuse after that:** the whole family is revoked (`reuse_detected`), the revocation is committed, and `ReusedRefreshTokenError` carries the user and family IDs for auditing.
- **Errors** (`app/auth/errors.py`) carry an internal `reason` and a `public_code`. Unknown email, wrong password, and disabled account all map to `invalid_credentials`; every refresh failure maps to `invalid_session`.
- **Tests** that need PostgreSQL use the `migrated_database_url`, `db_engine`, and `session_factory` fixtures in `tests/conftest.py`. These create one temporary migrated database per test run and clear its rows after each test.

### Configuration

All settings use the `ESTATEHUB_` prefix and are documented in `.env.example`.

| Setting | Default | Rule |
| --- | --- | --- |
| `JWT_ISSUER` / `JWT_AUDIENCE` | `estatehub-api` / `estatehub-staff` | |
| `JWT_ALGORITHM` | `HS256` | `HS256`, `HS384`, or `HS512` only |
| `ACCESS_TOKEN_TTL_MINUTES` | `15` | 1–60 |
| `REFRESH_SESSION_TTL_DAYS` | `7` | 1–30, and longer than the access-token lifetime |
| `JWT_SECRET_KEY`, `REFRESH_TOKEN_HASH_SECRET` | unset | At least 32 characters and different from each other |
| `AUTH_*_COOKIE_NAME` | `estatehub_access` / `estatehub_refresh` / `estatehub_csrf` | Valid cookie tokens and distinct (case-insensitive) |
| `AUTH_COOKIE_SECURE` | `true` | `.env.example` sets `false` for local HTTP |
| `AUTH_COOKIE_SAME_SITE` | `lax` | `none` requires `Secure` |
| `AUTH_COOKIE_DOMAIN` | unset (host-only) | Bare host name |
| `AUTH_ACCESS_COOKIE_PATH` / `AUTH_REFRESH_COOKIE_PATH` | `/` / `/api/v1/auth` | The refresh path must be inside the API prefix |
| `AUTH_LOGIN_*`, `AUTH_REFRESH_*`, `AUTH_PASSWORD_CHANGE_*` | see `.env.example` | Positive values; windows of at most 1 day |

Development and test may leave the secrets unset; later stages will need them to issue tokens. In `staging` and `production`, startup fails if a secret is missing, shorter than 32 characters, low in variety, contains a placeholder fragment such as `change-me` or `dev-only`, or equals the other secret. Startup also fails there if `AUTH_COOKIE_SECURE` is not `true`. Cookies named with `__Secure-` require `Secure`; `__Host-` additionally requires path `/` and no domain.

Secrets are `SecretStr` values. They are masked in `repr`, logs, and serialized settings, and they never appear in validation errors or OpenAPI.

## Authorization

Permissions are defined in code (`app/auth/permissions.py`). Role rows in the database only name a role. A user's permissions are the union of their roles' permissions, recomputed from PostgreSQL on every request. Access tokens carry no roles or permissions, so a role change or a disabled account applies to the very next request.

| Permission | administrator | manager | agent | accountant |
| --- | :---: | :---: | :---: | :---: |
| `staff:read` | ✓ | ✓ |  |  |
| `staff:create` | ✓ |  |  |  |
| `staff:update` | ✓ |  |  |  |
| `staff:disable` | ✓ |  |  |  |
| `staff:reactivate` | ✓ |  |  |  |
| `staff:assign_roles` | ✓ |  |  |  |
| `staff:revoke_sessions` | ✓ |  |  |  |
| `audit:read` | ✓ |  |  |  |
| `properties:read` | ✓ | ✓ | ✓ | ✓ |
| `properties:create` | ✓ | ✓ |  |  |
| `properties:update` | ✓ | ✓ |  |  |
| `properties:archive` | ✓ | ✓ |  |  |
| `properties:read_internal` | ✓ | ✓ | ✓ |  |
| `property_units:manage` | ✓ | ✓ |  |  |
| `property_media:manage` | ✓ | ✓ |  |  |
| `property_documents:read` | ✓ | ✓ |  |  |
| `property_documents:manage` | ✓ | ✓ |  |  |
| `property_ownership:read` | ✓ | ✓ | ✓ |  |
| `property_ownership:manage` | ✓ | ✓ |  |  |
| `contacts:read` | ✓ | ✓ | ✓ |  |
| `contacts:manage` | ✓ | ✓ | ✓ |  |
| `reference_data:manage` | ✓ |  |  |  |
| `listings:read` | ✓ | ✓ | ✓ |  |
| `listings:manage` | ✓ | ✓ | ✓ |  |
| `listings:publish` | ✓ | ✓ |  |  |
| `deals:read` | ✓ | ✓ | ✓ |  |
| `deals:manage` | ✓ | ✓ | ✓ |  |
| `rentals:read` | ✓ | ✓ |  | ✓ |
| `rentals:manage` | ✓ | ✓ |  |  |
| `payments:read` | ✓ | ✓ |  | ✓ |
| `payments:manage` | ✓ |  |  | ✓ |
| `expenses:read` | ✓ | ✓ |  | ✓ |
| `expenses:manage` | ✓ |  |  | ✓ |
| `maintenance:read` | ✓ | ✓ |  |  |
| `maintenance:manage` | ✓ | ✓ |  |  |
| `reports:operational` | ✓ | ✓ |  |  |
| `reports:financial` | ✓ | ✓ |  | ✓ |
| `configuration:manage` | ✓ |  |  |  |

<!-- Generated by app.auth.permissions.render_matrix_markdown(); tests/test_authorization.py fails if this table and the code differ. -->

- **Fail closed.** No roles means no permissions. Unknown role codes grant nothing. A disabled user has no permissions. Requiring an empty permission set, or passing a raw string, is a programming error.
- **No deny rules** in version 1; roles only add permissions.
- **Only administrators** hold any `staff:*` permission other than `staff:read`. Managers can read staff (to assign work) but cannot administer accounts, roles, or sessions.
- Agents' restriction to *assigned* records is row-level scoping, added by the domain prompts on top of these permissions.
- **One policy layer.** `app/auth/policy.py` (`Actor`, `require_permissions`, `require_any_permission`) is framework-free, so services enforce the same rules as routes. `AuthService.revoke_all_sessions(actor, …)` lets anyone revoke their own sessions; revoking anyone else's requires `staff:revoke_sessions`.
- **HTTP guards.** Routes use `Depends(require_permissions(Permission.X))` or `Depends(require_any_permission(...))` from `app/auth/dependencies.py`. Authentication failures return `401` (with `WWW-Authenticate`); authenticated requests lacking a permission return `403 permission_denied`. Denials are logged with user ID, required permissions, method, path, and request ID, never tokens or payloads.
- **Self-service routes** (`/auth/me`, `/auth/me/permissions`, `/auth/change-password`) need authentication only. `/auth/me/permissions` returns the user's roles and permissions so the frontend can hide navigation. It grants nothing; every endpoint checks for itself.

## Staff management

All routes are under `/api/v1/staff`. Each requires the matching permission from the matrix above; the service checks it again, so non-HTTP callers cannot skip it. Cookie-authenticated mutations need `X-CSRF-Token`.

| Endpoint | Permission | Success |
| --- | --- | --- |
| `GET /staff?status=&role=&q=&sort=&limit=&offset=` | `staff:read` | `200` `Page[UserPublic]` (`items`, `total`, `limit`, `offset`) |
| `GET /staff/{user_id}` | `staff:read` | `200` `UserPublic` |
| `POST /staff` (`email`, `full_name`, `password`, `roles`) | `staff:create` | `201` `UserPublic` with `Location` |
| `PATCH /staff/{user_id}` (`email`, `full_name` only) | `staff:update` | `200` `UserPublic` |
| `PUT /staff/{user_id}/roles` (`roles`) | `staff:assign_roles` | `200` `UserPublic` |
| `POST /staff/{user_id}/disable` | `staff:disable` | `200` `UserPublic` |
| `POST /staff/{user_id}/reactivate` | `staff:reactivate` | `200` `UserPublic` |
| `POST /staff/{user_id}/revoke-sessions` | `staff:revoke_sessions` | `204` |

- **Listing:** `limit` is 1–100 (default 25). `q` is a literal, case-insensitive search of email and name. `sort` is `full_name` (default), `email`, or `created_at`, with an optional `-` prefix for descending. The user ID breaks ties, so pages never overlap. Unknown parameters are rejected.
- **Validation:** unknown fields are rejected everywhere; `PATCH` refuses `status`, `roles`, and `password`. Emails are trimmed and lowercased, and a duplicate returns `409 email_already_exists`. Role codes must exist in the database; at least one is required.
- **Role changes** increment the token version, so the user's current access tokens stop working and the next refresh carries the new roles.
- **Disable** sets `disabled`, increments the token version, and revokes every refresh session in one transaction. **Reactivate** restores sign-in without restoring old sessions. Both are idempotent.
- **Administrator safeguards:** an administrator cannot disable themselves or remove their own `administrator` role (`409 self_lockout`). Nobody can disable or demote the last active administrator (`409 last_administrator`). Both checks run under a transaction-scoped PostgreSQL advisory lock, so two concurrent requests cannot each remove "the other" administrator.
- **Audit events** are written in the same transaction as the change: `staff.created` (roles), `staff.profile_updated` (changed field names), `staff.roles_changed` (before/after codes), `staff.disabled` and `staff.sessions_revoked` (revoked session count), and `staff.reactivated`. Each includes the actor, the target user ID, and the request ID. A request that changes nothing, or fails, writes no event. Passwords and hashes are never recorded.



## Property catalog contract

Prompt 02 builds the property catalog in stages. Stage 1 fixes the contract below in code before any model or route exists: `app/catalog/contracts.py` (route inventory and permission map), `app/catalog/errors.py` (error codes), and `app/audit/metadata.py` (audit allow-lists). `tests/test_catalog_contracts.py` checks naming and statuses, and checks that every route a later stage registers appears here.

- **Resources.** Plural kebab-case collections under `/api/v1`; IDs are `{<resource>_id}` path parameters. Units, media, documents, and owners are nested under their parent. A record requested under the wrong parent is `404 not_found`.
- **Archive, not delete.** `DELETE /properties/{property_id}` archives the property and returns it (`200`). Archived properties, units, and contacts return through an explicit `POST …/restore`. Ending an ownership link, and archiving an image or a document, is final: add a new link or upload again. Hard deletion is not part of ordinary CRUD.
- **Reference data** (property types, subtypes, amenities) is never deleted: `disable` and `reactivate` replace it, and `PUT …/order` replaces a whole ordering. Only administrators manage it, as the design specification assigns.
- **Permission first.** Each route's permission is checked before any record is loaded, so a caller without it receives `403` whether or not the ID exists. Services check the same permission again.
- **Field-level permissions** filter responses instead of guarding routes:

| Permission | Controls |
| --- | --- |
| `properties:read_internal` | Internal notes on property and unit responses. |
| `property_ownership:read` | Owner summaries inside property detail. |
| `contacts:read` | Owner email, telephone, and address inside ownership responses. |
| `properties:archive` | Archived properties in `GET /properties` (`include_archived=true`). |
| `reference_data:manage` | Disabled records in reference-data lists (`include_inactive`). |

### Reference data

`property_types`, `property_subtypes`, and `amenities` (`app/catalog/models.py`, revision `20261104_0002`) are administrator-managed data, not source-code enums.

- **Case-insensitive names.** Names are stored trimmed with inner whitespace collapsed (the database rejects anything else). PostgreSQL derives `name_key = lower(name)` as a stored generated column with an ordinary unique constraint: per table for types and amenities, per parent type for subtypes. "House" and "HOUSE" therefore conflict, while a commercial "House" may coexist with a residential one. `lower()` follows the database collation; it is not full Unicode case folding.
- **Subtypes** belong to exactly one type (`NOT NULL`, `ON DELETE RESTRICT`) and cannot move to another. A unique `(property_type_id, id)` pair lets later tables reference type and subtype together, so the database itself rejects a subtype of a different type.
- **Disable, don't delete.** `is_active = false` keeps a row valid wherever it is already used; services refuse it for new assignments. A disabled type also makes its subtypes unselectable.
- **Ordering** is always `display_order` (0–10000), then `name_key`, then `id`.
- **Seed.** The migration seeds four types (Residential, Student accommodation, Commercial, Land), 16 subtypes, and 14 amenities with categories. IDs are `uuid5(NAMESPACE_URL, "urn:estatehub:<kind>:<slug>")`, identical in every environment. Inserts use `ON CONFLICT DO NOTHING`, so re-running them adds nothing and never overwrites an administrator's rename or disable. Holiday and other rental categories are listing terms (prompt 03), not property types.
- **Downgrade** drops the three tables and their data, and leaves authentication data intact. It is tested, like the authentication revision.

### Properties

`properties` and `property_amenities` (`app/properties/models.py`, revision `20261104_0003`) describe the physical asset only. Prices, sale/rent terms, rental categories, and publication belong to listings (prompt 03).

- **Server-controlled fields.** `reference` (`PR-100001`, `PR-100002`, …) comes from the `property_reference_seq` sequence through a column default, so concurrent creates cannot collide; the ORM refuses to set it. Timestamps, staff IDs, archive metadata, and `version` are also set by the server.
- **Lifecycle.** `status` is `draft` (default), `active`, `inactive`, or `archived`. Archival is this one state, with `archived_at` and `archived_by_id`; a check keeps `status = 'archived'` and `archived_at` in step. Related tables never carry their own archived flag.
- **Optimistic concurrency.** `version` starts at 1. Every ORM update adds `AND version = :expected` and increments it, so a stale writer changes nothing and raises `StaleDataError`.
- **Classification.** `property_type_id` is required and `property_subtype_id` optional. A composite foreign key to `property_subtypes (property_type_id, id)` makes the database reject a subtype of another type. Whether a disabled type, subtype, or amenity may be *newly* assigned depends on what the property already uses, so `app/properties/rules.py` checks it in services; disabled references already in use stay valid.
- **Address.** Line 1, locality, and region are required; strings are trimmed with whitespace collapsed and cannot be blank. Postal codes are uppercased. `country_code` is two uppercase letters (ISO 3166-1 alpha-2), checked structurally only: nothing claims the address exists.
- **Coordinates** are `NUMERIC(8,6)` / `NUMERIC(9,6)`, within ±90 / ±180, and both present or both absent.
- **Facts.** Counts are non-negative integers. `bathrooms` is `NUMERIC(4,1)` in whole or half units. `land_area` and `floor_area` are `NUMERIC(12,2)` and share one `area_unit` (`square_metre` or `square_foot`), required exactly when an area is present.
- **Amenities** link through `property_amenities` (composite primary key, so no duplicates). Deleting an amenity in use is refused; amenities are disabled instead.
- **Indexes** cover the reference (unique), status, classification, location filters (`country_code, region, locality`), case-insensitive search (a `pg_trgm` GIN index on reference, name, locality, and region), and unarchived lists (partial index on `updated_at, id`). The migration creates the `pg_trgm` extension, which is trusted, so a database owner can install it; downgrade leaves it installed.
- `internal_notes` is staff-only and must never appear in a public schema.

### Contacts and ownership

`contacts` (`app/contacts/`) and `property_ownerships` (`app/properties/`), revision `20261104_0004`.

- **One contact table.** A contact is a `person` or an `organization` and can later act as seller, buyer, tenant, or prospect; there is no owner-only table. A person may name the `organization_name` they represent; an organization uses its `display_name`.
- **Reachable.** Every contact has an email, a telephone number, or a correspondence address (line 1, locality, and country; other address fields require these). An alternative telephone needs a different main number.
- **Normalization.** Emails are trimmed and lowercased. Telephones keep digits and an optional leading `+` (spaces, dots, hyphens, and brackets removed; `00` becomes `+`), 6–15 digits. There is no numbering-plan validation, so a number without `+` is stored as entered.
- **Privacy.** Contact schemas are private staff schemas. `ContactSummary` (lists) has no address or notes; `ContactDetail` adds them for `contacts:read`. Validation errors never echo input. In ownership responses, the owner's email, telephone, and status appear only for callers with `contacts:read`; `property_ownership:read` alone shows the display name and kind.
- **Concurrency.** `PATCH` requires the contact's current `version` (`stale_version` otherwise). Rules that need stored state, such as reachability, are re-checked on the merged record.
- **Archiving** a contact is refused (`dependency_conflict`) while an unended ownership link has no end date or one that has not passed. Restore is explicit.
- **Ownership.** A contact may own many properties and a property many owners. Shares are `NUMERIC(5,2)` percentages (0 < share ≤ 100) or unknown. `end_date ≥ start_date`. A partial unique index allows one *current* link per property and contact. Ending a link (`DELETE`) sets `archived_at`; ended links are history and never change.
- **Share rule.** On any single day, the known shares of the links in force that day total at most 100 (`conflict` otherwise), so sequential owners may each hold 100%. Unknown shares are not counted and are never assumed. The owners list reports today's `known_total`, `unknown_count`, and `complete` (true only when every share is known and they total exactly 100).
- **Races.** Every ownership change first locks the property row (`FOR UPDATE`), so concurrent changes to one property's owners run one at a time. Adding an owner holds `FOR SHARE` on the contact, which conflicts with the archive lock, so a contact cannot be archived while being linked.
- **Audit.** `contact.*` events record the kind, changed field names, and version; `property.owner_*` events record the ownership and contact IDs and changed field names. Neither records emails, telephones, addresses, shares, or notes.

### Units and management mode

`units` and `unit_amenities` (`app/properties/`), plus `properties.management_mode`, revision `20261104_0005`.

- **One representation.** `properties.management_mode` is `whole` (default; managed and later listed as one space), `units` (managed through its units), or `mixed` (both). Existing properties became `whole`. A `whole` property never has active units: creating or restoring a unit there is `conflict`, and switching a property to `whole` while it has active units is `dependency_conflict` (`app/properties/rules.py`; the property service applies it in stage 8). Standalone properties need no units.
- **Units** have a required `identifier` (such as "Flat 2B"), unique among a property's active units ignoring case: a stored `identifier_key = lower(identifier)` with a partial unique index. Archived units keep their identifier, so restoring one whose identifier was reused is `duplicate_reference`. Optional name, floor label, description, bedrooms, half-unit bathrooms, capacity, floor area with its unit, furnished state, internal notes, and amenities (`unit_amenities`). `status` is the operational state: `available` (default), `occupied`, or `unavailable`.
- **No nesting, no moves.** A unit belongs to exactly one property and never to another unit. It never moves between properties; a unit requested under another property is `not_found`.
- **Subtype rule.** A unit's subtype must belong to its property's type (`invalid_relationship` otherwise). Disabled subtypes and amenities cannot be newly assigned but stay valid where already used. For a mixed-use building, classify the property with a type whose subtypes cover its units (an administrator can add, for example, "Mixed use" with "Apartment" and "Shop").
- **Archival.** Archiving a unit keeps it as history; later listing, lease, and booking prompts add their dependency checks to `UnitService.archive_unit`. Archiving a property changes no unit, but normal unit lists then exclude them; `include_archived` shows every unit. Units of an archived property cannot be changed.
- **Concurrency.** Unit changes lock the property row first, like ownership changes. `PATCH` requires the unit's `version`; any change, including amenities only, increments it.
- **Privacy.** `internal_notes` appear only for `properties:read_internal`.
- **Query shape.** `PropertyRepository.get_detail` loads the property, its classification and amenities, and every unit with its subtype and amenities in a fixed number of queries; a test asserts the count does not grow with the number of units.

### Media and private documents

`media_assets` and `documents` (`app/media/`), revision `20261104_0006`. File bytes never live in PostgreSQL.

- **Storage.** `app/media/storage.py` defines a small `ObjectStorage` interface (`save`, `stream`, `exists`, `delete`) with a local-disk implementation; object storage can replace it later without domain changes. The root is `ESTATEHUB_MEDIA_STORAGE_ROOT` (`storage`, which is `/app/storage` in Docker, the `media_data` volume), so files survive API restarts and image rebuilds. Nothing under it is served statically: every download goes through an authorized service call (routes arrive in stage 11).
- **Keys** are `<media|documents>/<2 hex>/<32 hex>` from a CSPRNG, validated on every call, and never built from a filename. Uploads are staged in `<root>/.incoming` on the same filesystem and hard-linked into place, so an object appears atomically and an existing object is never overwritten (`ObjectExistsError`).
- **Accepted formats.** Images: JPEG, PNG, WebP. Documents: PDF, plus JPEG/PNG/WebP scans. Office formats, archives, HTML, SVG, and executables are refused.
- **Upload checks** (`app/media/files.py`). The declared size is refused early and the real size on every chunk, so an oversized stream is cut off. The type comes from the file signature; the client's `Content-Type` is never used. Images are fully decoded with Pillow, which rejects truncated or corrupt data, and images over the pixel limit are refused before decoding. PDFs need a header and an end-of-file marker. The filename is a display label only: it must be a plain name (no path, traversal, leading dot, or control characters), its extension must match the content, and inner executable extensions (`invoice.php.png`) are refused. Empty files are refused. Errors are `invalid_upload` with a generic message that never echoes the name or contents.
- **Limits** (`.env.example`): `ESTATEHUB_MEDIA_MAX_IMAGE_BYTES` (10 MiB), `ESTATEHUB_MEDIA_MAX_DOCUMENT_BYTES` (25 MiB), `ESTATEHUB_MEDIA_MAX_IMAGE_PIXELS` (50 million).
- **Consistency.** Rows are flushed first, then the file is stored, then the transaction commits. If storing fails, the transaction rolls back and no metadata remains. If anything fails after storing, including the commit, the stored object is deleted. Only an object this request stored is ever deleted. The staged file is always removed. Replacing a document deletes the old object only after the new one is committed.
- **Parents.** Each file belongs to exactly one property or unit (`num_nonnulls(property_id, unit_id) = 1`) and never moves. A file requested under another parent is `not_found`. Changes lock the parent property row, including for unit files, and are refused while the property or unit is archived.
- **Images** have width, height, alt text, and `display_order`, ordered by `display_order`, then creation time, then ID. Reordering takes the complete set of active image IDs (duplicates or foreign IDs are `invalid_relationship`). A partial unique index allows one cover per parent, and setting a cover clears the previous one in the same transaction. Archiving an image also removes its cover status. Metadata updates change only alt text, never the file, key, or type.
- **Documents** have a category (`title_deed`, `sale_agreement`, `lease`, `certificate`, `insurance`, `inspection_report`, `floor_plan`, `invoice`, `other`), title, and optional expiry date. Metadata, download, replacement, and archive each require `property_documents:read` or `:manage`; agents and accountants have neither. Updates and replacements require the current `version`. Downloads are audited (`document.downloaded`).
- **Archival** is final and idempotent for both images and documents. Archived files leave normal lists but keep their stored object as history.
- **Missing objects.** If metadata exists but the object does not, downloads return `not_found` and an error is logged without any path.
- **Privacy.** No response schema has a storage key or path. Audit metadata holds parent IDs, detected media types, sizes, categories, and changed field names, never filenames, titles, alt text, keys, or contents.
- **Background work.** Uploads are processed synchronously and need no Celery task. Thumbnails, if added later, must be idempotent tasks with bounded retries.

### Schemas and validation boundaries

Every operation has its own Pydantic v2 schema. No schema is shared between input and output, and none is reused as an ORM model.

| Group | Schemas (module) |
| --- | --- |
| Reference data | `ReferenceCreate`, `AmenityCreate`, `ReferenceUpdate`, `AmenityUpdate`, `ReferenceOrder`, `ReferenceListQuery`; read shapes `PropertyTypeRead`, `PropertySubtypeRead`, `AmenityRead` (`app/catalog/schemas.py`) |
| Contacts | `ContactCreate`, `ContactUpdate`, `ContactListQuery`, `ContactSummary`, `ContactDetail` (`app/contacts/schemas.py`) |
| Ownership | `OwnershipCreate`, `OwnershipUpdate`, `OwnershipPublic`, `PropertyOwners` (`app/properties/schemas.py`) |
| Properties | `PropertyCreate`, `PropertyUpdate`, `PropertyListQuery`, `PropertySummary`, `PropertyDetail`, `PublicProperty` (`app/properties/schemas.py`) |
| Units | `UnitCreate`, `UnitUpdate`, `UnitSummary`, `UnitDetail` (`app/properties/schemas.py`) |
| Media and documents | `MediaUpdate`, `MediaOrder`, `MediaPublic`, `DocumentCreate`, `DocumentUpdate`, `DocumentSummary`, `DocumentDetail` (`app/media/schemas.py`) |
| Lists | `ArchivedQuery` (`include_archived`) for unit, image, document, and owner lists |

- **Where rules live.** Pydantic checks shape plus field-local and cross-field rules that need no database: trimming, lengths, decimals, coordinate pairs, area units, date order, duplicate IDs or identifiers in one request, and units on a `whole` property. Services check active references, type/subtype compatibility, uniqueness, share totals, dependencies, archival, and permissions, and re-run the cross-field rules on the merged record after a `PATCH` (`property_rule_errors`, `contact_rule_errors`). PostgreSQL remains the final integrity boundary.
- **Shared field types** (`app/catalog/fields.py`) normalize text exactly as the ORM and database checks expect. Blank required text is reported as too short; blank optional text becomes `null`.
- **Writes** reject unknown fields (`extra="forbid"`) and never accept server-controlled fields (IDs, `reference`, timestamps, staff IDs, archive data, storage keys). Contact and property errors never echo input (`hide_input_in_errors`).
- **`PATCH`** distinguishes omitted fields (unchanged) from explicit `null` (cleared): `changes()` returns only supplied fields. Required columns refuse `null`, an empty body is refused, and `version` is required wherever records are versioned. `status: archived` is refused: archive with `DELETE`.
- **Directory query.** Multi-select filters use repeated parameters (`?status=active&status=draft`). `amenity_id` requires every listed amenity. `sort` is an allow-listed enum (`created_at`, `updated_at`, `reference`, `name`, `locality`, each optionally prefixed with `-`; default `-updated_at`). Unknown parameters or values are `422`, never ignored. Filtering on `archived` needs `include_archived=true`.
- **Outputs.** `PropertySummary` is a compact directory row with no address lines, notes, owners, or files. `PropertyDetail` omits (not nulls) `internal_notes` without `properties:read_internal` and `owners` without `property_ownership:read`. Inside owners, contact details need `contacts:read` and link notes need `properties:read_internal`. Decimals serialize as exact strings. No output schema has a storage key or path. `PublicProperty` is defined but not published yet: physical facts, classification names, locality/region/country, amenity names, and coordinates rounded to three decimals (about 100 m), with no reference, address lines, postal code, internal description, notes, owners, documents, or staff data.
- **OpenAPI.** `app/catalog/openapi.error_responses(...)` documents `401`/`403` on every catalog route plus the statuses it adds, listing the exact codes from `CATALOG_ERRORS`, so the documentation cannot drift. `from_attributes` is enabled only on output schemas.

### Services and repositories

Repositories (`*/repository.py`) hold parameterized SQLAlchemy queries and never commit. Services hold transactions, rules, and permission checks (`run_in_transaction` in `app/catalog/transactions.py`), and add each audit event in the same transaction as its change. Only expected integrity errors are translated: duplicate names, identifiers, or links. Anything else propagates as a `500`.

- **`ReferenceDataService`** (`app/catalog/service.py`). Any `properties:read` holder lists active types (with their active subtypes) and active amenities, which is what property forms offer, and may open any single record. Administrators (`reference_data:manage`) also list disabled records (`include_inactive`) and create, update, disable, reactivate, and reorder types, subtypes (addressed through their own type), and amenities. Duplicate names, ignoring case, are `duplicate_reference`: a pre-check gives the friendly error and the unique constraint catches races. Reordering takes the complete list, locks it, and stores positions as 0, 10, 20, …. Disable and reactivate are idempotent.
- **`PropertyService`** (`app/properties/service.py`):
  - **Create** (`properties:create`, plus `property_ownership:manage` / `property_units:manage` when initial owners or units are sent) validates classification, amenities, owners (active contacts, share total), and units (subtype of the property's type, amenities), then writes everything in one transaction. Any failure leaves no property, link, unit, or audit event. Error fields point into the request, such as `units.1.amenity_ids`.
  - **References** come from a database sequence, so concurrent creates never collide.
  - **Update** (`properties:update`) locks the row, refuses archived properties and stale `version`s, re-checks the merged record, and refuses newly assigning disabled references. A type change needs a compatible subtype and is refused while active units have subtypes. Switching to `whole` is refused while active units exist. Any change, including amenities only, increments `version`. Unchanged updates write nothing.
  - **Archive and restore** (`properties:archive`) are idempotent and change no child record. A restored property becomes `inactive`, since the previous status is not stored. Restore needs no reference re-check because reference rows are never deleted.
  - **Reads.** Any `properties:read` holder may open a property directly, archived or not, so history always resolves. Directory results exclude archived properties unless `include_archived=true`, which needs `properties:archive`.
- **Directory query** (`PropertyRepository.list_page`). The count and the page use identical filters. Sorting uses the allow-listed column (case-insensitive for name and locality) with the property ID as tie-breaker, so pages never skip or repeat rows. Search is literal (`%` and `_` are escaped) and case-insensitive over reference, name, locality, and region, plus current owners' names only for callers with `property_ownership:read`, so search cannot reveal ownership. Unit counts and cover IDs are fetched for the whole page in one query each.

### HTTP behaviour

Reference data, contacts, properties, and property owners are served by `app/api/v1/routes/reference_data.py`, `contacts.py`, `properties.py`, `owners.py`, `units.py`, and `files.py`, registered in the v1 router.

- **Guards.** Each route declares its exact permission (`require_permissions`), and the service checks again. Cookie-authenticated `POST`, `PUT`, `PATCH`, and `DELETE` requests need `X-CSRF-Token` (`403 csrf_failed`); bearer-token requests do not. A permission that only widens a read (`include_inactive`, `include_archived` on properties) is checked by the service and is also `403 permission_denied`.
- **Statuses.** Creation is `201` with a `Location` header pointing at the new record's `GET` route. Other mutations, including `DELETE` (archive or end) and actions such as `disable` or `restore`, return `200` with the record. Path IDs are validated as UUIDs (`422`).
- **Errors.** Service errors become the standard error body via `app/catalog/http.translated()`: `404 not_found` (including a record under the wrong parent), `409 duplicate_reference` / `conflict` / `dependency_conflict` / `stale_version` / `archived_record`, and `422 validation_error` / `invalid_relationship`. Unexpected errors are logged and returned as `500 internal_error`.
- **Reference reads.** `GET /property-types` and `GET /amenities` return active records in display order. `include_inactive=true` adds disabled ones and needs `reference_data:manage`. `GET /property-types/{id}` returns the type with every subtype, so forms can label values that existing records still use. All readers see the same shape (`is_active` included).
- **Contacts.** Lists return `Page[ContactSummary]` (no address or notes). Detail, create, and update return `ContactDetail`. `internal_notes` appears only with `properties:read_internal`.
- **Owners.** `GET /properties/{id}/owners` returns a page of current links, plus ended ones with `include_archived=true`, together with today's `shares` summary, which always covers every current link whatever the page. Contact details inside a link need `contacts:read`, and link notes need `properties:read_internal`.
- **Properties.**
  - `GET /properties` returns `Page[PropertySummary]`. Multi-select filters repeat the parameter (`?status=active&status=draft&amenity_id=…&amenity_id=…`). Invalid values, sort keys, or unknown parameters are `422`, never ignored. `include_archived=true` needs `properties:archive`.
  - `POST /properties` returns `201` with `Location`. The OpenAPI document carries a standalone and a multi-unit request example.
  - `GET` returns the permission-filtered `PropertyDetail`; archived properties stay readable.
  - `PATCH` needs the current `version`.
  - `DELETE` archives and `POST …/restore` restores (as `inactive`). Both return the detail.
- **Units.** These are full CRUD under `/properties/{id}/units`. A unit requested under another property is `404`; `property_id` is not accepted in a `PATCH`. Creating or restoring a unit on a `whole` property is `409 conflict`, and reusing an active identifier is `409 duplicate_reference`. Archived units appear only with `include_archived=true`. `internal_notes` needs `properties:read_internal`.
- **Images and documents** are served at `/properties/{id}/…` and `/properties/{id}/units/{unit_id}/…` by the same handlers. A file of another parent is `404`.
  - **Uploads** are `multipart/form-data` with a `file` part. Images may add `alt_text`; documents add `category`, `title`, and optional `expiry_date`.
  - **Early refusal.** `app/media/http.UploadLimitMiddleware` refuses a multipart request without `Content-Length`, or declaring more than the largest upload limit plus 64 KiB, before its body is read (`422 invalid_upload`, `Connection: close`). Every chunk is then checked against the per-type limit, and the file is validated by content as described under media and private documents.
  - **`Location`** is the download URL for images and the metadata URL for documents.
- **Downloads** stream through the API. Every download sends `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'; sandbox`, `Cross-Origin-Resource-Policy: same-origin`, and a `Content-Disposition` with a sanitized ASCII name plus the exact name in `filename*` (RFC 6266), so a stored name cannot inject headers. Images are `inline` with `Cache-Control: private, max-age=300`; documents are `attachment` with `private, no-store`, and every document download is audited. A missing stored object is `404` and is logged.
- **Ordering and covers.** `PUT …/media/order` takes the complete set of active image IDs. `POST …/media/{id}/cover` replaces the previous cover atomically. Concurrent cover and order changes always leave exactly one cover and a gap-free order.
- **Server errors.** With `ESTATEHUB_DEBUG=false` (the default, and required wherever the API is exposed) an unexpected failure is `500 internal_error` with no detail. The development `.env.example` sets `true`, which makes Starlette return tracebacks; never deploy with it.
- **Anti-enumeration.** The route permission is checked before any lookup, so without it a missing and an existing ID both give `403`. With it, a missing ID is `404`.
- **Query shape.** A detail request and a directory page each run a fixed number of queries regardless of how many units, owners, or rows they return; `tests/test_properties_api.py` guards this.
- **Route list changes.** Stage 9 added `GET` routes for a single subtype, amenity, and ownership, so every `201` has a readable `Location`.

### Collections, limits, storage, and examples

**Every collection is bounded** (`tests/test_catalog_milestone.py` checks each route):

| Collection | Shape | Bound |
| --- | --- | --- |
| Properties, contacts, units, owners, images, documents | `items`, `total`, `limit`, `offset` | `limit` 1–100 (default 25), deterministic order with ID tie-breaker |
| Property types (with subtypes), amenities | whole list | at most 100 types, 100 subtypes per type, 200 amenities |
| Reorder requests (`PUT …/order`) | whole list | the same caps; image galleries at most 100 active images |
| Units and current owners inside a property detail | embedded | at most 500 active units and 50 current owners per property |

Creating a record beyond a cap is `409 conflict` (`"This list has reached its limit of N."`). Caps live in `app/catalog/limits.py`. Archived units, ended owners, and archived files do not count toward them and are read through the paginated lists with `include_archived=true`.

**Archive behaviour** is the same everywhere: `DELETE` archives and returns the record with `archived_at`, and repeating it changes nothing. Archived records leave normal lists and stay readable with `include_archived=true`. Properties, units, and contacts come back through `POST …/restore`. Ending an ownership and archiving an image or document is final. Nothing in the catalog is ever physically deleted.

**Local upload configuration (Docker).** Files are written to `ESTATEHUB_MEDIA_STORAGE_ROOT` (`storage`, which is `/app/storage` in the `api` container). That is the named volume `media_data`, which survives container restarts and image rebuilds; `docker compose down -v` deletes it. Staging uses `<root>/.incoming` on the same volume. Back up the volume together with PostgreSQL, because metadata without its object downloads as `404`. Limits and accepted formats are listed under [Media and private documents](#media-and-private-documents).

**Example requests.** The examples use a bearer token, so they need no CSRF header; browsers using cookies must send `X-CSRF-Token`. Interactive documentation, including standalone and multi-unit create examples, is at `http://localhost:8000/docs`.

```bash
API=http://localhost:8000/api/v1
TOKEN=$(curl -s -X POST "$API/auth/token" -d "username=$EMAIL" -d "password=$PASSWORD" | jq -r .access_token)
AUTH="Authorization: Bearer $TOKEN"

# Active property types and subtypes, as offered by property forms.
curl -s -H "$AUTH" "$API/property-types"

# Search the directory: repeated parameters select several values.
curl -s -H "$AUTH" "$API/properties?q=rose&status=active&status=draft&sort=-updated_at&limit=25"

# Create a property, then update it with its current version.
curl -s -H "$AUTH" -H "Content-Type: application/json" -X POST "$API/properties" \
  -d '{"name":"Rose Cottage","property_type_id":"<type id>","address_line_1":"1 High Street","locality":"Bath","region":"Somerset","country_code":"GB"}'
curl -s -H "$AUTH" -H "Content-Type: application/json" -X PATCH "$API/properties/<id>" \
  -d '{"version":1,"bedrooms":3}'

# Upload an image and a private document (multipart), then download the document.
curl -s -H "$AUTH" -F "file=@front.jpg" -F "alt_text=Front of the house" "$API/properties/<id>/media"
curl -s -H "$AUTH" -F "file=@deed.pdf" -F "category=title_deed" -F "title=Title deed" "$API/properties/<id>/documents"
curl -s -H "$AUTH" -OJ "$API/properties/<id>/documents/<document id>/content"

# Archive and restore.
curl -s -H "$AUTH" -X DELETE "$API/properties/<id>"
curl -s -H "$AUTH" -X POST "$API/properties/<id>/restore"
```

### Routes

| Method | Path | Permission | Success | Summary |
| --- | --- | --- | :---: | --- |
| `GET` | `/property-types` | `properties:read` | `200` | List property types with subtypes |
| `GET` | `/property-types/{property_type_id}` | `properties:read` | `200` | Get a property type |
| `POST` | `/property-types` | `reference_data:manage` | `201` | Create a property type |
| `PATCH` | `/property-types/{property_type_id}` | `reference_data:manage` | `200` | Update a property type |
| `POST` | `/property-types/{property_type_id}/disable` | `reference_data:manage` | `200` | Disable a property type |
| `POST` | `/property-types/{property_type_id}/reactivate` | `reference_data:manage` | `200` | Reactivate a property type |
| `PUT` | `/property-types/order` | `reference_data:manage` | `200` | Reorder property types |
| `GET` | `/property-types/{property_type_id}/subtypes/{property_subtype_id}` | `properties:read` | `200` | Get a property subtype |
| `POST` | `/property-types/{property_type_id}/subtypes` | `reference_data:manage` | `201` | Create a property subtype |
| `PATCH` | `/property-types/{property_type_id}/subtypes/{property_subtype_id}` | `reference_data:manage` | `200` | Update a property subtype |
| `POST` | `/property-types/{property_type_id}/subtypes/{property_subtype_id}/disable` | `reference_data:manage` | `200` | Disable a property subtype |
| `POST` | `/property-types/{property_type_id}/subtypes/{property_subtype_id}/reactivate` | `reference_data:manage` | `200` | Reactivate a property subtype |
| `PUT` | `/property-types/{property_type_id}/subtypes/order` | `reference_data:manage` | `200` | Reorder property subtypes |
| `GET` | `/amenities` | `properties:read` | `200` | List amenities |
| `GET` | `/amenities/{amenity_id}` | `properties:read` | `200` | Get an amenity |
| `POST` | `/amenities` | `reference_data:manage` | `201` | Create an amenity |
| `PATCH` | `/amenities/{amenity_id}` | `reference_data:manage` | `200` | Update an amenity |
| `POST` | `/amenities/{amenity_id}/disable` | `reference_data:manage` | `200` | Disable an amenity |
| `POST` | `/amenities/{amenity_id}/reactivate` | `reference_data:manage` | `200` | Reactivate an amenity |
| `PUT` | `/amenities/order` | `reference_data:manage` | `200` | Reorder amenities |
| `GET` | `/contacts` | `contacts:read` | `200` | List contacts |
| `POST` | `/contacts` | `contacts:manage` | `201` | Create a contact |
| `GET` | `/contacts/{contact_id}` | `contacts:read` | `200` | Get a contact |
| `PATCH` | `/contacts/{contact_id}` | `contacts:manage` | `200` | Update a contact |
| `DELETE` | `/contacts/{contact_id}` | `contacts:manage` | `200` | Archive a contact |
| `POST` | `/contacts/{contact_id}/restore` | `contacts:manage` | `200` | Restore a contact |
| `GET` | `/properties` | `properties:read` | `200` | List properties |
| `POST` | `/properties` | `properties:create` | `201` | Create a property |
| `GET` | `/properties/{property_id}` | `properties:read` | `200` | Get a property |
| `PATCH` | `/properties/{property_id}` | `properties:update` | `200` | Update a property |
| `DELETE` | `/properties/{property_id}` | `properties:archive` | `200` | Archive a property |
| `POST` | `/properties/{property_id}/restore` | `properties:archive` | `200` | Restore a property |
| `GET` | `/properties/{property_id}/owners` | `property_ownership:read` | `200` | List property owners |
| `POST` | `/properties/{property_id}/owners` | `property_ownership:manage` | `201` | Add a property owner |
| `GET` | `/properties/{property_id}/owners/{ownership_id}` | `property_ownership:read` | `200` | Get a property ownership |
| `PATCH` | `/properties/{property_id}/owners/{ownership_id}` | `property_ownership:manage` | `200` | Update a property ownership |
| `DELETE` | `/properties/{property_id}/owners/{ownership_id}` | `property_ownership:manage` | `200` | End a property ownership |
| `GET` | `/properties/{property_id}/units` | `properties:read` | `200` | List units |
| `POST` | `/properties/{property_id}/units` | `property_units:manage` | `201` | Create a unit |
| `GET` | `/properties/{property_id}/units/{unit_id}` | `properties:read` | `200` | Get a unit |
| `PATCH` | `/properties/{property_id}/units/{unit_id}` | `property_units:manage` | `200` | Update a unit |
| `DELETE` | `/properties/{property_id}/units/{unit_id}` | `property_units:manage` | `200` | Archive a unit |
| `POST` | `/properties/{property_id}/units/{unit_id}/restore` | `property_units:manage` | `200` | Restore a unit |
| `GET` | `/properties/{property_id}/media` | `properties:read` | `200` | List property images |
| `POST` | `/properties/{property_id}/media` | `property_media:manage` | `201` | Upload a property image |
| `GET` | `/properties/{property_id}/media/{media_id}/content` | `properties:read` | `200` | Download a property image |
| `PATCH` | `/properties/{property_id}/media/{media_id}` | `property_media:manage` | `200` | Update property image alt text |
| `PUT` | `/properties/{property_id}/media/order` | `property_media:manage` | `200` | Reorder property images |
| `POST` | `/properties/{property_id}/media/{media_id}/cover` | `property_media:manage` | `200` | Set the property cover |
| `DELETE` | `/properties/{property_id}/media/{media_id}` | `property_media:manage` | `200` | Archive a property image |
| `GET` | `/properties/{property_id}/documents` | `property_documents:read` | `200` | List property documents |
| `POST` | `/properties/{property_id}/documents` | `property_documents:manage` | `201` | Upload a property document |
| `GET` | `/properties/{property_id}/documents/{document_id}` | `property_documents:read` | `200` | Get property document metadata |
| `GET` | `/properties/{property_id}/documents/{document_id}/content` | `property_documents:read` | `200` | Download a property document |
| `PATCH` | `/properties/{property_id}/documents/{document_id}` | `property_documents:manage` | `200` | Update property document metadata |
| `PUT` | `/properties/{property_id}/documents/{document_id}/content` | `property_documents:manage` | `200` | Replace a property document file |
| `DELETE` | `/properties/{property_id}/documents/{document_id}` | `property_documents:manage` | `200` | Archive a property document |
| `GET` | `/properties/{property_id}/units/{unit_id}/media` | `properties:read` | `200` | List unit images |
| `POST` | `/properties/{property_id}/units/{unit_id}/media` | `property_media:manage` | `201` | Upload a unit image |
| `GET` | `/properties/{property_id}/units/{unit_id}/media/{media_id}/content` | `properties:read` | `200` | Download a unit image |
| `PATCH` | `/properties/{property_id}/units/{unit_id}/media/{media_id}` | `property_media:manage` | `200` | Update unit image alt text |
| `PUT` | `/properties/{property_id}/units/{unit_id}/media/order` | `property_media:manage` | `200` | Reorder unit images |
| `POST` | `/properties/{property_id}/units/{unit_id}/media/{media_id}/cover` | `property_media:manage` | `200` | Set the unit cover |
| `DELETE` | `/properties/{property_id}/units/{unit_id}/media/{media_id}` | `property_media:manage` | `200` | Archive a unit image |
| `GET` | `/properties/{property_id}/units/{unit_id}/documents` | `property_documents:read` | `200` | List unit documents |
| `POST` | `/properties/{property_id}/units/{unit_id}/documents` | `property_documents:manage` | `201` | Upload a unit document |
| `GET` | `/properties/{property_id}/units/{unit_id}/documents/{document_id}` | `property_documents:read` | `200` | Get unit document metadata |
| `GET` | `/properties/{property_id}/units/{unit_id}/documents/{document_id}/content` | `property_documents:read` | `200` | Download a unit document |
| `PATCH` | `/properties/{property_id}/units/{unit_id}/documents/{document_id}` | `property_documents:manage` | `200` | Update unit document metadata |
| `PUT` | `/properties/{property_id}/units/{unit_id}/documents/{document_id}/content` | `property_documents:manage` | `200` | Replace a unit document file |
| `DELETE` | `/properties/{property_id}/units/{unit_id}/documents/{document_id}` | `property_documents:manage` | `200` | Archive a unit document |

<!-- Generated by app.catalog.contracts.render_routes_markdown(); tests/test_catalog_contracts.py fails if this table and the code differ. -->

### Error codes

Every catalog error uses the standard error body. Messages are generic; details go in `fields` and never quote private values.

| Code | Status | Message |
| --- | :---: | --- |
| `validation_error` | `422` | The request contains invalid data. |
| `not_found` | `404` | The requested record was not found. |
| `duplicate_reference` | `409` | A record with this value already exists. |
| `invalid_relationship` | `422` | A referenced record cannot be used here. |
| `archived_record` | `409` | The record is archived. Restore it before changing it. |
| `conflict` | `409` | The change conflicts with the current state of the record. |
| `dependency_conflict` | `409` | Other records depend on this one, so it cannot be changed. |
| `stale_version` | `409` | The record was changed by someone else. Reload it and review the changes. |
| `invalid_upload` | `422` | The file cannot be accepted. |
| `permission_denied` | `403` | You do not have permission to perform this action. |

Request-shape validation keeps the existing `422 validation_error`; services raise the same code when a rule needs stored state, such as a `PATCH` that would leave a contact unreachable. A missing or wrong-parent record is `not_found`; an unknown, inactive, or incompatible referenced record (such as a subtype of another type) is `invalid_relationship`; a `PATCH` with an out-of-date `version` is `stale_version`.

### Audit events

Catalog events (`property.*`, `unit.*`, `media.*`, `document.*`, `contact.*`, `reference_data.*`) are written in the same transaction as the change. Their metadata is allow-listed per event code: IDs, ID lists, counts, changed field names, short codes, and detected media types only. Keys such as `email`, `notes`, `filename`, or `storage_key` are refused, and free-text values do not fit any allowed shape, so contact details, notes, file contents, and storage paths cannot be recorded.

## Bootstrap administrator

```bash
docker compose run --rm api python -m app.cli create-admin --email admin@example.com --name "Admin Name"
```

- The password comes from a hidden `getpass` prompt entered twice, or from the first line of standard input with `--password-stdin` (only the line ending is stripped). There is no `--password` option, and no environment variable is read.
- The command refuses (exit code `2`) while any active administrator exists, unless `--allow-additional-admin` is given. The check runs under the same advisory lock as administrator demotion, so concurrent runs cannot both pass.
- It uses `StaffService.bootstrap_administrator`, which shares the API's validation (12–128 character password, email normalization), Argon2id hashing, and audit path. It records `staff.bootstrap_admin_created` with no actor.
- Exit codes: `0` created, `1` invalid input or mismatched passwords, `2` refused. Errors name the field but never print the value.

## Rate limiting

Authentication endpoints are rate-limited with fixed-window counters in Redis, shared by every API process. Each request is counted before it is processed. Keys are `{RATE_LIMIT_KEY_PREFIX}:{rule}:{fingerprint}`, where the fingerprint is an HMAC of the email, IP address, or user ID under a key derived from `REFRESH_TOKEN_HASH_SECRET`. Raw emails and addresses never reach Redis.

| Endpoint | Limited by | Settings (default) | Redis down |
| --- | --- | --- | --- |
| `POST /auth/token` | client IP **and** normalized email | `AUTH_LOGIN_MAX_ATTEMPTS_PER_IP` (20), `AUTH_LOGIN_MAX_ATTEMPTS_PER_EMAIL` (5), `AUTH_LOGIN_WINDOW_SECONDS` (900) | **fails closed**: `503 auth_service_unavailable` |
| `POST /auth/change-password` | client IP **and** user ID | `AUTH_PASSWORD_CHANGE_MAX_ATTEMPTS` (5), `AUTH_PASSWORD_CHANGE_WINDOW_SECONDS` (900) | **fails closed** |
| `POST /auth/refresh` | client IP (the user is unknown until the token is checked) | `AUTH_REFRESH_MAX_ATTEMPTS_PER_IP` (60), `AUTH_REFRESH_WINDOW_SECONDS` (60) | fails open, logs a warning |
| `POST /auth/logout`, `GET /auth/me`, `GET /auth/me/permissions` | client IP | `AUTH_SESSION_MAX_REQUESTS_PER_IP` (300), `AUTH_SESSION_WINDOW_SECONDS` (60) | fails open, logs a warning |

- **Exceeding a limit** returns `429 auth_rate_limited` with `Retry-After` (seconds until the window resets). Successful logins count too. A correct password does not bypass an active limit.
- **No email enumeration.** Limits are checked before the email is looked up, so known and unknown emails give identical responses.
- **Redis outages.** Login and password change are the credential-guessing surfaces, so they refuse service rather than run unprotected. Refresh, logout, and the read endpoints already need a valid session or access token, so they keep working. `GET /health/ready` returns `503` whenever Redis is unreachable.

### Client IP and proxies

The client address is the TCP peer address unless the peer is listed in `ESTATEHUB_TRUSTED_PROXIES` (JSON list of IPs or CIDRs, empty by default). Only then is `X-Forwarded-For` read, from the right, skipping trusted proxies; the first untrusted address is the client. Addresses a client adds to the header itself are never reached, so forged headers cannot dodge per-IP limits. When deploying behind a proxy, set this to the proxy's addresses. Keep Uvicorn's own `--forwarded-allow-ips` at its default, or set it to the same addresses, so the two do not disagree. The resolved address is stored only as a /24 (IPv4) or /48 (IPv6) prefix.

**Behind the web app.** Browser traffic reaches the API through the Next.js `/api/v1` rewrite. Next.js forwards the client's own `X-Forwarded-For` unchanged and does not append the real peer address. Trusting the web container on its own would therefore let any browser choose its rate-limit IP. Instead:

- **Development** trusts no proxies, so every browser request counts as the web container's address. Per-IP limits are shared, but they cannot be spoofed, and per-email and per-user limits are unaffected.
- **Production** must put a reverse proxy or load balancer in front of the web app that appends the real client address to `X-Forwarded-For`. Set `ESTATEHUB_TRUSTED_PROXIES` to that proxy's addresses **and** the web servers' addresses. The API then reads the rightmost untrusted entry, which is the address the load balancer appended.

## Audit log

Audit events are inserted by the application and never updated or deleted through it (the ORM refuses both). Metadata is validated and cannot contain credentials, tokens, or request bodies.

| Code | Actor | Recorded when | Metadata |
| --- | --- | --- | --- |
| `auth.login_succeeded` | the user | a login succeeds | `session_family_id`, `client_ip_prefix`, `hash_upgraded` if the password hash was upgraded |
| `auth.login_failed` | none | a login fails | `reason` (`unknown_email`, `wrong_password`, `user_disabled`), `email_fingerprint` (HMAC, never the email), `client_ip_prefix` |
| `auth.rate_limited` | the user, when known | the first rejected request per key and window | `rule`, `client_ip_prefix`, `email_fingerprint` for the per-email rule |
| `auth.refresh_token_reused` | none | a rotated refresh token is replayed | `session_family_id`, `revoked_sessions` |
| `auth.logout` | the user | a session is actually revoked | `session_family_id` |
| `auth.password_changed` | the user | a password change commits | `revoked_sessions` |
| `auth.permission_denied` | the user | a permission guard returns `403` | `required_permissions`, `permission_mode`, `method`, `path` |
| `staff.bootstrap_admin_created` | none | the CLI creates an administrator | `roles` |
| `staff.*` | the administrator | see [Staff management](#staff-management) | |

Every event carries the request ID when there is one. Successful-change events share the change's transaction. Failure events (`auth.login_failed`, `auth.rate_limited`, `auth.permission_denied`) are written in their own transaction, because the failed work is rolled back.

`GET /api/v1/audit-events` (`audit:read`) lists events newest first, with the ID as tie-breaker. It returns `Page[AuditEventPublic]`. Filters: `event_code`, `actor_id`, `entity_type`, `entity_id`, `occurred_from` (inclusive) and `occurred_to` (exclusive), both timezone-aware. Pagination: `limit` (1–100) and `offset`.

