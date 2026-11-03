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
| `properties:manage` | ✓ | ✓ |  |  |
| `listings:read` | ✓ | ✓ | ✓ |  |
| `listings:manage` | ✓ | ✓ | ✓ |  |
| `listings:publish` | ✓ | ✓ |  |  |
| `contacts:read` | ✓ | ✓ | ✓ |  |
| `contacts:manage` | ✓ | ✓ | ✓ |  |
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

