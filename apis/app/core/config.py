from functools import lru_cache
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ESTATEHUB_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000"]
    database_url: str = "postgresql+asyncpg://estatehub:estatehub_dev_only@localhost:5432/estatehub"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    @model_validator(mode="after")
    def validate_cors_origins(self) -> Self:
        for origin in self.cors_origins:
            if "*" in origin:
                raise ValueError("CORS origins must be explicit; wildcards are not allowed.")
            if self.environment in ("staging", "production") and not origin.startswith("https://"):
                raise ValueError(f"CORS origin {origin!r} must use HTTPS in {self.environment}.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
