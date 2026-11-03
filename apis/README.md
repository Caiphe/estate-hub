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
- `ESTATEHUB_CORS_ORIGINS` must list explicit origins. Wildcards are rejected, and staging/production require HTTPS origins.
