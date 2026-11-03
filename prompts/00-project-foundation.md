# Prompt 00: Project Foundation

## Objective

Create and verify EstateHub's reproducible development foundation without implementing business-domain features.

## Read first

- `docs/superpowers/specs/2026-11-03-estatehub-design.md`
- `docs/implementation-roadmap.md`
- Root `README.md`

## Required outcome

Docker Compose must start PostgreSQL, Redis, FastAPI, Celery worker, Celery Beat, and Next.js. Both applications must expose health endpoints, and the repository must have working lint, type-check, test, migration, and production-build commands.

## Work

1. Validate the root environment template, ignore rules, and repository documentation.
2. Validate Compose health checks, service dependencies, persistent volumes, and development mounts.
3. Configure FastAPI with Pydantic v2 settings, SQLAlchemy 2.x async sessions, PostgreSQL through `asyncpg`, Alembic, Redis, and Celery.
4. Provide API liveness and dependency-aware readiness endpoints.
5. Add request IDs and strict environment-specific CORS configuration.
6. Configure Pytest, HTTPX, Ruff, and mypy.
7. Configure Next.js App Router, TypeScript strict mode, ESLint, Playwright, and a minimal application shell.
8. Ensure production Docker stages use non-root users.
9. Generate and commit dependency lock files.
10. Initialize Alembic with a valid empty baseline only if a baseline is needed before domain tables.

Do not add authentication, users, properties, or other domain models in this milestone.

## Acceptance criteria

- `docker compose config` succeeds.
- `docker compose up --build -d` reaches a healthy state for required services.
- API liveness returns HTTP 200 without checking dependencies.
- API readiness returns HTTP 200 only when PostgreSQL and Redis are reachable.
- The Next.js health route and home page return HTTP 200.
- API tests, linting, and type checking pass.
- Frontend linting, type checking, build, and foundation Playwright test pass.
- A worker can connect to Redis without task-discovery errors.
- No credentials or generated runtime data are tracked.

## Verification

```bash
docker compose config
docker compose up --build -d
docker compose ps
curl --fail http://localhost:8000/api/v1/health/live
curl --fail http://localhost:8000/api/v1/health/ready
curl --fail http://localhost:3001/api/health
docker compose run --rm api ruff check .
docker compose run --rm api mypy app
docker compose run --rm api pytest
docker compose run --rm web npm run lint
docker compose run --rm web npm run typecheck
docker compose run --rm web npm run build
cd web
npx playwright install chromium
PLAYWRIGHT_BASE_URL=http://127.0.0.1:3001 npm run test:e2e
```

## Completion report

Report created files, architecture decisions, command results, remaining warnings, and the exact next prompt. Do not proceed to Prompt 01.
