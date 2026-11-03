FROM python:3.14-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv

# The virtual environment lives outside /app so the development bind mount cannot hide it.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN addgroup --system estatehub && adduser --system --ingroup estatehub estatehub

COPY pyproject.toml uv.lock README.md ./

FROM base AS development
RUN uv sync --locked --extra dev --no-install-project
COPY . .
RUN uv sync --locked --extra dev \
    && mkdir -p /app/storage \
    && chown -R estatehub:estatehub /app
USER estatehub

FROM base AS production
RUN uv sync --locked --no-dev --no-install-project
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
RUN uv sync --locked --no-dev --no-editable \
    && mkdir -p /app/storage \
    && chown -R estatehub:estatehub /app/storage
USER estatehub
EXPOSE 8000
CMD ["fastapi", "run", "app/main.py", "--host", "0.0.0.0", "--port", "8000"]
