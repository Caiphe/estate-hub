from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError

from app.api.v1.routes import health


class _FakeConnection:
    async def execute(self, _: Any) -> None:
        return None


class _FakeEngine:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[_FakeConnection]:
        if self.error:
            raise self.error
        yield _FakeConnection()


class _FakeRedis:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def ping(self) -> bool:
        if self.error:
            raise self.error
        return True


async def test_liveness(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


async def test_readiness_when_dependencies_are_reachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health, "engine", _FakeEngine())
    monkeypatch.setattr(health, "redis_client", _FakeRedis())

    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("engine_error", "redis_error"),
    [
        (OperationalError("SELECT 1", {}, Exception("db down")), None),
        (None, RedisConnectionError("redis down")),
    ],
)
async def test_readiness_fails_when_a_dependency_is_unreachable(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    engine_error: Exception | None,
    redis_error: Exception | None,
) -> None:
    monkeypatch.setattr(health, "engine", _FakeEngine(engine_error))
    monkeypatch.setattr(health, "redis_client", _FakeRedis(redis_error))

    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "service_unavailable"
    assert "down" not in error["message"]
    assert error["request_id"] == response.headers["x-request-id"]
