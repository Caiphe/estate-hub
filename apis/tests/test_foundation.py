import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.core.config import Settings


async def test_valid_request_id_is_echoed(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/live", headers={"X-Request-ID": "abc-123"})

    assert response.headers["x-request-id"] == "abc-123"


@pytest.mark.parametrize("unsafe_id", ["a" * 129, "bad id", "x\ty"])
async def test_unsafe_request_id_is_replaced(client: AsyncClient, unsafe_id: str) -> None:
    response = await client.get("/api/v1/health/live", headers={"X-Request-ID": unsafe_id})

    assert response.headers["x-request-id"] != unsafe_id
    assert len(response.headers["x-request-id"]) == 36


async def test_unknown_route_uses_standard_error_body(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Not Found",
            "fields": {},
            "request_id": response.headers["x-request-id"],
        }
    }


def test_wildcard_cors_origin_is_rejected() -> None:
    with pytest.raises(ValidationError, match="wildcards"):
        Settings(cors_origins=["*"])


def test_production_requires_https_cors_origins() -> None:
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(environment="production", cors_origins=["http://estatehub.example"])

    settings = Settings(
        environment="production",
        cors_origins=["https://estatehub.example"],
        auth_cookie_secure=True,
        jwt_secret_key="test-jwt-3f9a1c7e5b2d4086a1f3c5e7b9d0f2a4",
        refresh_token_hash_secret="test-hash-8b2e4d6f0a1c3e5g7i9k1m3o5q7s9u1w",
    )
    assert settings.cors_origins == ["https://estatehub.example"]
