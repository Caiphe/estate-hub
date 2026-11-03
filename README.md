# EstateHub

EstateHub is a property sales, lettings, and management platform for one property-management company. It consists of a FastAPI backend, a Next.js public site and staff workspace, PostgreSQL, Redis, and Celery workers.

## Current milestone

Milestone 00 establishes the development environment and health-checked application shells. Business modules are added in the numbered order documented in [`prompts/`](./prompts/README.md).

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

# Run browser tests against the Dockerized web application
cd web
npx playwright install chromium
PLAYWRIGHT_BASE_URL=http://127.0.0.1:3001 npm run test:e2e

# Apply database migrations and confirm models match them
docker compose run --rm api alembic upgrade head
docker compose run --rm api alembic check
```

Backend dependency locking and API conventions are documented in [`apis/README.md`](./apis/README.md).

The approved product design is in [`docs/superpowers/specs/2026-11-03-estatehub-design.md`](./docs/superpowers/specs/2026-11-03-estatehub-design.md).
