# EstateHub

EstateHub is a property sales, lettings, and management platform for one property-management company. It consists of a FastAPI backend, a Next.js public site and staff workspace, PostgreSQL, Redis, and Celery workers.

## Current milestone

Milestones 00 (development environment) and 01 (staff authentication, RBAC, and staff management) are complete. Business modules are added in the numbered order documented in [`prompts/`](./prompts/README.md).

## Prerequisites

- Docker with Docker Compose
- Git
- Optional for running outside Docker: Python 3.14 and Node.js 22

## Start locally

```bash
cp .env.example .env
docker compose up --build
```

Then open:

- Public web application: <http://localhost:3001>
- FastAPI documentation: <http://localhost:8000/docs>
- API liveness: <http://localhost:8000/api/v1/health/live>
- API readiness: <http://localhost:8000/api/v1/health/ready>

### Connect with TablePlus

- Host: `127.0.0.1`
- Port: `5433`
- Database: `estatehub`
- User: `estatehub`
- Password: `estatehub_dev_only`

Port `5433` avoids conflicts with PostgreSQL installations using the default host port. Services inside Docker continue to connect to `db:5432`.

## Create the first administrator

After migrations, create the first staff administrator from the API container. The password is read from a hidden prompt (typed twice), never from the command line or an environment variable, so it stays out of shell history, process lists, and logs:

```bash
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.cli create-admin --email admin@example.com --name "Admin Name"
```

For automation, pipe the password on standard input with `--password-stdin`, for example from a secret manager (`... | docker compose run --rm -T api python -m app.cli create-admin ... --password-stdin`). The command refuses to run while an active administrator exists; add `--allow-additional-admin` to override. Further staff accounts are managed through the API. See [`apis/README.md`](./apis/README.md#bootstrap-administrator).

## Staff workspace

Sign in at <http://localhost:3001/login>. The workspace has `/dashboard`, `/account/password`, `/staff` (staff management, for administrators; managers get a read-only directory), and `/audit` (the audit log, for administrators).

- **Single origin.** The browser calls the API only at `/api/v1` on the web origin, and Next.js forwards those requests to `INTERNAL_API_BASE_URL` (`next.config.ts`). Auth cookies therefore belong to the web origin, no CORS is involved, and `web/proxy.ts` can see them. Set `INTERNAL_API_BASE_URL` before starting the dev server; for the production image, pass it as a build argument because rewrites are fixed at build time.
- **Tokens are never readable by scripts.** Access and refresh tokens stay in HTTP-only cookies. The client reads only the CSRF cookie and sends it as `X-CSRF-Token` on unsafe requests. Nothing is stored in `localStorage` or `sessionStorage`.
- **Route protection** (`web/proxy.ts`) is an optimistic check only; the API authorizes every request. Workspace routes need the access cookie, or the CSRF cookie so an expired access token can be refreshed. `/login` sends visitors with an access cookie to the workspace. The `next` parameter must be a same-origin workspace path (`web/lib/auth/redirect.ts`); anything else falls back to `/dashboard`.
- **Refresh.** On a `401` that a new access token can fix, the client makes one `POST /auth/refresh`, shared by every request waiting at that moment, and retries each request once. A refresh rejected by the API (`401`/`403`) returns to `/login`. A refresh that is merely unavailable (network error, `429`, `5xx`) shows a retry message and signs nobody out.
- **Navigation** is filtered by `GET /auth/me/permissions`. This only hides links; the API enforces every permission itself.
- **Development rate limits.** Browser requests reach the API through the web container, so in development every browser shares one IP, and `compose.yaml` raises the per-IP login limit to 200. Per-email limits (5 per 15 minutes) still apply.

The security verification for this milestone is recorded in [`docs/security/authentication-verification.md`](./docs/security/authentication-verification.md).

## Common commands

```bash
# Run backend checks
docker compose run --rm api pytest
docker compose run --rm api ruff check .
docker compose run --rm api ruff format --check .
docker compose run --rm api mypy app tests

# Run frontend checks
docker compose run --rm web npm run lint
docker compose run --rm web npm run typecheck
docker compose run --rm web npm run build

# Run frontend unit tests
docker compose run --rm web npm test

# Run browser tests against the Dockerized web application (the stack must be running).
# Global setup creates e2e.*@estatehub.example administrators in the development
# database through the bootstrap CLI and resets development rate-limit counters.
cd web
npx playwright install chromium
PLAYWRIGHT_BASE_URL=http://127.0.0.1:3001 npm run test:e2e

# Apply database migrations and confirm models match them
docker compose run --rm api alembic upgrade head
docker compose run --rm api alembic check
```

Backend dependency locking and API conventions are documented in [`apis/README.md`](./apis/README.md).

The approved product design is in [`docs/superpowers/specs/2026-11-03-estatehub-design.md`](./docs/superpowers/specs/2026-11-03-estatehub-design.md).
