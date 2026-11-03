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
