import re
from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_SECRET_LENGTH = 32
_MIN_DISTINCT_SECRET_CHARACTERS = 10
# Placeholder fragments from .env.example and common defaults; refused outside development/test.
_PLACEHOLDER_SECRET_FRAGMENTS = ("change-me", "changeme", "dev-only", "dev_only", "placeholder")
# RFC 6265 cookie-name token characters.
_COOKIE_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]{1,64}$")
_COOKIE_DOMAIN = re.compile(r"^\.?[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})*$")
_DEPLOYED_ENVIRONMENTS = ("staging", "production")


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

    # Access tokens (JWT). Only symmetric HMAC algorithms are supported in version 1.
    jwt_issuer: str = Field(default="estatehub-api", min_length=1, max_length=255)
    jwt_audience: str = Field(default="estatehub-staff", min_length=1, max_length=255)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_secret_key: SecretStr | None = None
    access_token_ttl_minutes: int = Field(default=15, ge=1, le=60)

    # Refresh sessions. Refresh tokens are opaque; only a keyed hash is stored.
    refresh_token_hash_secret: SecretStr | None = None
    refresh_session_ttl_days: int = Field(default=7, ge=1, le=30)

    # Authentication cookies.
    auth_access_cookie_name: str = "estatehub_access"
    auth_refresh_cookie_name: str = "estatehub_refresh"
    auth_csrf_cookie_name: str = "estatehub_csrf"
    auth_cookie_secure: bool = True
    auth_cookie_same_site: Literal["lax", "strict", "none"] = "lax"
    auth_cookie_domain: str | None = None
    auth_access_cookie_path: str = "/"
    auth_refresh_cookie_path: str = "/api/v1/auth"

    # Authentication rate limits: maximum attempts within a fixed window.
    auth_login_max_attempts_per_ip: int = Field(default=20, ge=1, le=10_000)
    auth_login_max_attempts_per_email: int = Field(default=5, ge=1, le=1_000)
    auth_login_window_seconds: int = Field(default=900, ge=1, le=86_400)
    auth_refresh_max_attempts_per_ip: int = Field(default=60, ge=1, le=10_000)
    auth_refresh_window_seconds: int = Field(default=60, ge=1, le=86_400)
    auth_password_change_max_attempts: int = Field(default=5, ge=1, le=1_000)
    auth_password_change_window_seconds: int = Field(default=900, ge=1, le=86_400)

    @field_validator(
        "jwt_secret_key", "refresh_token_hash_secret", "auth_cookie_domain", mode="before"
    )
    @classmethod
    def blank_as_unset(cls, value: object) -> object:
        # An empty `NAME=` line in .env means "not configured", not an empty string.
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def is_deployed(self) -> bool:
        return self.environment in _DEPLOYED_ENVIRONMENTS

    @model_validator(mode="after")
    def validate_cors_origins(self) -> Self:
        for origin in self.cors_origins:
            if "*" in origin:
                raise ValueError("CORS origins must be explicit; wildcards are not allowed.")
            if self.is_deployed and not origin.startswith("https://"):
                raise ValueError(f"CORS origin {origin!r} must use HTTPS in {self.environment}.")
        return self

    @model_validator(mode="after")
    def validate_auth_secrets(self) -> Self:
        secrets = {
            "ESTATEHUB_JWT_SECRET_KEY": self.jwt_secret_key,
            "ESTATEHUB_REFRESH_TOKEN_HASH_SECRET": self.refresh_token_hash_secret,
        }
        for name, secret in secrets.items():
            if secret is None:
                if self.is_deployed:
                    raise ValueError(f"{name} is required in {self.environment}.")
                continue
            value = secret.get_secret_value()
            if len(value) < MIN_SECRET_LENGTH:
                raise ValueError(f"{name} must be at least {MIN_SECRET_LENGTH} characters.")
            if self.is_deployed and _looks_like_placeholder(value):
                raise ValueError(f"{name} must be a unique random value in {self.environment}.")
        jwt_secret, hash_secret = secrets.values()
        if jwt_secret is not None and hash_secret is not None and jwt_secret == hash_secret:
            raise ValueError(
                "ESTATEHUB_JWT_SECRET_KEY and ESTATEHUB_REFRESH_TOKEN_HASH_SECRET must differ."
            )
        return self

    @model_validator(mode="after")
    def validate_auth_lifetimes(self) -> Self:
        if self.refresh_session_ttl_days * 24 * 60 <= self.access_token_ttl_minutes:
            raise ValueError("Refresh sessions must outlive access tokens.")
        return self

    @model_validator(mode="after")
    def validate_auth_cookies(self) -> Self:
        names = (
            self.auth_access_cookie_name,
            self.auth_refresh_cookie_name,
            self.auth_csrf_cookie_name,
        )
        for name in names:
            if not _COOKIE_NAME.fullmatch(name):
                raise ValueError(f"Cookie name {name!r} contains invalid characters.")
        if len({name.lower() for name in names}) != len(names):
            raise ValueError("Access, refresh, and CSRF cookie names must be distinct.")

        if self.is_deployed and not self.auth_cookie_secure:
            raise ValueError(f"ESTATEHUB_AUTH_COOKIE_SECURE must be true in {self.environment}.")
        if self.auth_cookie_same_site == "none" and not self.auth_cookie_secure:
            raise ValueError("SameSite=None cookies must also be Secure.")
        if self.auth_cookie_domain is not None and not _COOKIE_DOMAIN.fullmatch(
            self.auth_cookie_domain
        ):
            raise ValueError("ESTATEHUB_AUTH_COOKIE_DOMAIN must be a bare host name.")

        for path in (self.auth_access_cookie_path, self.auth_refresh_cookie_path):
            if not path.startswith("/") or any(char in path for char in ";, \t"):
                raise ValueError(f"Cookie path {path!r} must be an absolute URL path.")
        if not self.auth_refresh_cookie_path.startswith(self.api_v1_prefix):
            raise ValueError("The refresh cookie path must be within the API prefix.")

        for name in names:
            if name.startswith(("__Secure-", "__Host-")) and not self.auth_cookie_secure:
                raise ValueError(f"Cookie {name!r} uses a secure prefix but is not Secure.")
        host_prefixed_paths = {
            self.auth_access_cookie_name: self.auth_access_cookie_path,
            self.auth_refresh_cookie_name: self.auth_refresh_cookie_path,
            self.auth_csrf_cookie_name: "/",
        }
        for name, path in host_prefixed_paths.items():
            if name.startswith("__Host-") and (path != "/" or self.auth_cookie_domain):
                raise ValueError(f"Cookie {name!r} uses __Host- and requires path / and no domain.")
        return self


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.lower()
    return (
        any(fragment in lowered for fragment in _PLACEHOLDER_SECRET_FRAGMENTS)
        or len(set(value)) < _MIN_DISTINCT_SECRET_CHARACTERS
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
