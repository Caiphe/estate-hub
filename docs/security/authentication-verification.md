# Authentication milestone: security verification

Recorded 2026-11-03 for milestone 01 (authentication, staff users, and RBAC). Run against the Docker Compose development stack, a throwaway PostgreSQL database (`estatehub_verify`, dropped afterwards), and a second API instance on port 8010 started with production configuration.

The production-configured instance used `ESTATEHUB_ENVIRONMENT=production`, freshly generated random secrets, `AUTH_COOKIE_SECURE=true`, `AUTH_COOKIE_SAME_SITE=strict`, `AUTH_COOKIE_DOMAIN=estatehub.example`, `CORS_ORIGINS=["https://estatehub.example"]`, and a separate Redis key prefix.

## Verification commands

| Command | Result |
| --- | --- |
| `docker compose run --rm api ruff check .` | exit 0: All checks passed |
| `docker compose run --rm api ruff format --check .` | exit 0: 77 files already formatted |
| `docker compose run --rm api mypy app tests` | exit 0: no issues in 74 source files |
| `docker compose run --rm api pytest` | exit 0: 612 passed |
| `docker compose run --rm api alembic upgrade head` | exit 0 |
| `docker compose run --rm api alembic check` | exit 0: No new upgrade operations detected |
| `docker compose run --rm web npm run lint` | exit 0 |
| `docker compose run --rm web npm run typecheck` | exit 0 |
| `docker compose run --rm web npm test` | exit 0: 81 passed (6 files) |
| `docker compose run --rm web npm run build` | exit 0 |
| `PLAYWRIGHT_BASE_URL=http://127.0.0.1:3001 npm run test:e2e` | exit 0: 16 passed (5 consecutive green runs) |
| `docker compose config -q`, `GET /api/v1/health/ready` | exit 0, `{"status":"ok"}` |

## Integration and security checks

### 1. Clean database upgrade

A new empty database upgraded to `20261103_0001 (head)`; `alembic check` reported no differences from the models.

### 2. First administrator through the CLI

`printf '%s\n' "$PW" | ... python -m app.cli create-admin --email admin@estatehub.example --name 'Verify Admin' --password-stdin` printed `Created administrator admin@estatehub.example (<id>)`. A second run exited with code `2` (an active administrator exists). The password never appeared on the command line, in an environment variable, or in output.

### 3. Production cookie attributes

```text
set-cookie: estatehub_access=<value>; Domain=estatehub.example; HttpOnly; Max-Age=900; Path=/; SameSite=strict; Secure
set-cookie: estatehub_refresh=<value>; Domain=estatehub.example; HttpOnly; Max-Age=604800; Path=/api/v1/auth; SameSite=strict; Secure
set-cookie: estatehub_csrf=<value>; Domain=estatehub.example; Max-Age=604800; Path=/; SameSite=strict; Secure
```

Logout deletes each cookie with the same `Domain`, `Path`, `Secure`, and `SameSite` (`Max-Age=0`).

### 4. CSRF

| Request (cookie-authenticated unless noted) | Result |
| --- | --- |
| `POST /staff`, no `X-CSRF-Token` | `403 csrf_failed` |
| `POST /staff`, random `X-CSRF-Token` | `403 csrf_failed` |
| `POST /auth/refresh`, no header | `403 csrf_failed` |
| `GET /auth/me`, no header (safe method) | `200` |
| `POST /staff`, bearer token, no header | `422` (passed authentication and CSRF, then failed validation) |

### 5. CORS with credentials

| Preflight `Origin` | Result |
| --- | --- |
| `https://estatehub.example` (allowed) | `200`, `Access-Control-Allow-Origin: https://estatehub.example` |
| `https://evil.example` | `400`, no `Access-Control-Allow-Origin` |
| `http://estatehub.example` (wrong scheme) | `400`, no `Access-Control-Allow-Origin` |

### 6. Refresh-token reuse

After one rotation and an 11-second wait (past the 10-second concurrency grace window), replaying the rotated token returned `401 invalid_session`. The newest token in the family was then also refused (`401`). The family's rows were `rotated` and `reuse_detected`, and one `auth.refresh_token_reused` audit event recorded `revoked_sessions: 1` and the family ID.

### 7. Disabling a signed-in user

An agent's bearer token returned `200` from `/auth/me`. After an administrator disabled the account, the same token returned `401 invalid_token`, and signing in returned `401 invalid_credentials`. The browser equivalent is covered by Playwright: a disabled member's reload lands on `/login`.

### 8. Rate limit in the composed stack

Six sign-ins for one email through the web origin (`localhost:3001/api/v1/auth/token`): attempts 1–5 returned `401 invalid_credentials`; attempt 6 returned `429 auth_rate_limited` with `Retry-After: 900`.

### 9. Database inspection

All password hashes are Argon2id (`2 total, 2 argon2id`). All refresh-token hashes are 64-character hex HMACs (`5 total, 5 are 64-char hex`). A full data dump of the verification database contained none of the raw refresh tokens, the CSRF token, the access JWT, or either password (0 matches each).

### 10. Logs during the full Playwright run

The API and web logs captured during a complete e2e run (2,366 lines, 167 requests) contained zero matches for the e2e passwords, JWTs (`eyJ…`), `estatehub_access=`, `estatehub_refresh=`, `estatehub_csrf=`, `X-CSRF-Token:`, `password=`, or `$argon2`.

## Milestone checklist

- [x] All 12 sub-prompts are complete.
- [x] A clean database upgrades through every authentication migration (check 1).
- [x] The first administrator can be created without exposing a password in shell history (check 2).
- [x] Login, refresh rotation, reuse detection, logout, password change, and account disabling work (API and Playwright suites; checks 6 and 7).
- [x] Administrator, manager, agent, and accountant permissions are tested (`tests/test_authorization.py`, `tests/test_staff_api.py`, `e2e/staff.spec.ts`).
- [x] Redis protects authentication endpoints from abusive attempts (check 8; `tests/test_rate_limits_and_audit.py`).
- [x] Security events and staff changes create audit events (check 6; audit tests; Playwright audit view).
- [x] Browser cookies and CSRF behavior are verified under production configuration (checks 3–5).
- [x] Playwright covers login, route protection, logout, and administrator staff management (16 tests).
- [x] Every Prompt 00 check still passes.

## Known limitations

- **Per-IP limits in development.** Browser traffic reaches the API through the Next.js rewrite, which does not append the client address to `X-Forwarded-For`. In development every browser therefore shares one rate-limit IP (the web container), and `compose.yaml` raises the per-IP login limit to 200. Per-email and per-user limits are unaffected. Production needs a reverse proxy that appends the real client address, with `ESTATEHUB_TRUSTED_PROXIES` listing that proxy and the web servers.
- **Lost refresh responses.** If a refresh response never reaches the browser (navigation mid-refresh, network drop), the next refresh presents an already-rotated token. Within 10 seconds that is a conflict and the user signs in again. After 10 seconds it counts as reuse and the family is revoked and audited. This is the accepted cost of strict rotation with theft detection.
- **Breached-password screening** is deferred; it needs an offline list or a privacy-preserving lookup.
- **The audit view shows IDs, not names**, for actors and staff members.
- **Managers see a read-only staff directory** (`staff:read` in the approved matrix). Agents and accountants see neither staff nor audit pages.

## Recommended follow-ups

1. Before production, document the reverse-proxy setup and set `ESTATEHUB_TRUSTED_PROXIES`, then repeat check 8 per client IP.
2. Add a scheduled job that deletes expired and long-revoked refresh sessions.
3. Consider multi-factor authentication for administrators (out of scope for version 1).
4. Show names alongside IDs in the audit view, and add CSV export when reporting is built.
5. Run Playwright in CI against the composed stack.
