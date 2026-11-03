import logging
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings

# Test-only values: long, distinct, and free of placeholder fragments.
JWT_SECRET = "test-jwt-3f9a1c7e5b2d4086a1f3c5e7b9d0f2a4"
HASH_SECRET = "test-hash-8b2e4d6f0a1c3e5g7i9k1m3o5q7s9u1w"


@pytest.fixture(autouse=True)
def _isolate_auth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep host or container environment variables out of configuration tests."""
    for name in (
        "ESTATEHUB_ENVIRONMENT",
        "ESTATEHUB_CORS_ORIGINS",
        "ESTATEHUB_JWT_SECRET_KEY",
        "ESTATEHUB_REFRESH_TOKEN_HASH_SECRET",
        "ESTATEHUB_AUTH_COOKIE_SECURE",
        "ESTATEHUB_AUTH_COOKIE_SAME_SITE",
        "ESTATEHUB_AUTH_COOKIE_DOMAIN",
    ):
        monkeypatch.delenv(name, raising=False)


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "development",
        "jwt_secret_key": JWT_SECRET,
        "refresh_token_hash_secret": HASH_SECRET,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def production_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "production",
        "cors_origins": ["https://estatehub.example"],
        "auth_cookie_secure": True,
    }
    values.update(overrides)
    return make_settings(**values)


def test_development_defaults_load_with_explicit_local_secrets() -> None:
    settings = make_settings()

    assert settings.jwt_issuer == "estatehub-api"
    assert settings.jwt_audience == "estatehub-staff"
    assert settings.jwt_algorithm == "HS256"
    assert settings.access_token_ttl_minutes == 15
    assert settings.refresh_session_ttl_days == 7
    assert settings.auth_access_cookie_name == "estatehub_access"
    assert settings.auth_refresh_cookie_name == "estatehub_refresh"
    assert settings.auth_csrf_cookie_name == "estatehub_csrf"
    assert settings.auth_cookie_same_site == "lax"
    assert settings.auth_refresh_cookie_path == "/api/v1/auth"
    assert settings.jwt_secret_key is not None
    assert settings.jwt_secret_key.get_secret_value() == JWT_SECRET


def test_development_allows_missing_secrets() -> None:
    settings = make_settings(jwt_secret_key=None, refresh_token_hash_secret=None)

    assert settings.jwt_secret_key is None
    assert settings.refresh_token_hash_secret is None


@pytest.mark.parametrize("field", ["jwt_secret_key", "auth_cookie_domain"])
def test_blank_values_are_treated_as_unset(field: str) -> None:
    settings = make_settings(**{field: "  "})

    assert getattr(settings, field) is None


def test_blank_secret_is_still_required_in_production() -> None:
    with pytest.raises(ValidationError, match="is required in production"):
        production_settings(jwt_secret_key="")


def test_production_accepts_strong_distinct_secrets() -> None:
    settings = production_settings()

    assert settings.is_deployed


@pytest.mark.parametrize("environment", ["staging", "production"])
@pytest.mark.parametrize(
    ("field", "env_name"),
    [
        ("jwt_secret_key", "ESTATEHUB_JWT_SECRET_KEY"),
        ("refresh_token_hash_secret", "ESTATEHUB_REFRESH_TOKEN_HASH_SECRET"),
    ],
)
def test_deployed_environments_require_secrets(environment: str, field: str, env_name: str) -> None:
    with pytest.raises(ValidationError, match=f"{env_name} is required in {environment}"):
        production_settings(environment=environment, **{field: None})


@pytest.mark.parametrize("environment", ["development", "production"])
def test_short_secrets_are_rejected(environment: str) -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        production_settings(environment=environment, jwt_secret_key="too-short")


@pytest.mark.parametrize(
    "placeholder",
    [
        "dev-only-change-me-jwt-secret-0123456789abcdef",
        "PLACEHOLDER-placeholder-placeholder-1234",
        "a" * 64,
        "abababababababababababababababababab",
    ],
)
def test_production_rejects_default_or_low_entropy_secrets(placeholder: str) -> None:
    with pytest.raises(ValidationError, match="unique random value"):
        production_settings(refresh_token_hash_secret=placeholder)


def test_development_allows_example_placeholders() -> None:
    settings = make_settings(jwt_secret_key="dev-only-change-me-jwt-secret-0123456789abcdef")

    assert settings.jwt_secret_key is not None


@pytest.mark.parametrize("environment", ["development", "production"])
def test_equal_secrets_are_rejected(environment: str) -> None:
    with pytest.raises(ValidationError, match="must differ"):
        production_settings(environment=environment, refresh_token_hash_secret=JWT_SECRET)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_environments_require_secure_cookies(environment: str) -> None:
    with pytest.raises(ValidationError, match="AUTH_COOKIE_SECURE must be true"):
        production_settings(environment=environment, auth_cookie_secure=False)


def test_same_site_none_requires_secure() -> None:
    with pytest.raises(ValidationError, match="SameSite=None"):
        make_settings(auth_cookie_same_site="none", auth_cookie_secure=False)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("access_token_ttl_minutes", 0),
        ("access_token_ttl_minutes", -5),
        ("access_token_ttl_minutes", 61),
        ("refresh_session_ttl_days", 0),
        ("refresh_session_ttl_days", 31),
        ("auth_login_max_attempts_per_email", 0),
        ("auth_login_window_seconds", 0),
        ("auth_login_window_seconds", 86_401),
        ("auth_refresh_max_attempts_per_ip", 0),
        ("auth_password_change_window_seconds", 0),
    ],
)
def test_lifetime_and_rate_limit_bounds(field: str, value: int) -> None:
    with pytest.raises(ValidationError, match=field):
        make_settings(**{field: value})


@pytest.mark.parametrize(
    "overrides",
    [
        {"auth_refresh_cookie_name": "estatehub_access"},
        {"auth_csrf_cookie_name": "ESTATEHUB_ACCESS"},
    ],
)
def test_cookie_names_must_be_distinct(overrides: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="must be distinct"):
        production_settings(**overrides)


@pytest.mark.parametrize("name", ["", "bad name", "semi;colon", 'quote"d', "x" * 65])
def test_cookie_names_must_be_valid_tokens(name: str) -> None:
    with pytest.raises(ValidationError, match="invalid characters"):
        make_settings(auth_access_cookie_name=name)


def test_secure_cookie_prefixes_require_secure() -> None:
    with pytest.raises(ValidationError, match="secure prefix"):
        make_settings(auth_refresh_cookie_name="__Secure-refresh", auth_cookie_secure=False)


def test_host_prefix_requires_root_path_and_no_domain() -> None:
    with pytest.raises(ValidationError, match="__Host-"):
        production_settings(auth_refresh_cookie_name="__Host-refresh")
    with pytest.raises(ValidationError, match="__Host-"):
        production_settings(
            auth_access_cookie_name="__Host-access", auth_cookie_domain="estatehub.example"
        )

    settings = production_settings(auth_access_cookie_name="__Host-access")
    assert settings.auth_access_cookie_name == "__Host-access"


@pytest.mark.parametrize("path", ["api/v1/auth", "/api/v1/auth;x", "/other/auth"])
def test_refresh_cookie_path_must_be_absolute_and_inside_api(path: str) -> None:
    with pytest.raises(ValidationError, match="path"):
        make_settings(auth_refresh_cookie_path=path)


@pytest.mark.parametrize("domain", ["https://estatehub.example", "estatehub.example/x", "a b"])
def test_cookie_domain_must_be_a_bare_host(domain: str) -> None:
    with pytest.raises(ValidationError, match="bare host name"):
        make_settings(auth_cookie_domain=domain)


def test_secrets_are_hidden_from_representations(caplog: pytest.LogCaptureFixture) -> None:
    settings = make_settings()

    with caplog.at_level(logging.INFO):
        logging.getLogger(__name__).info("settings: %s", settings)

    for rendered in (repr(settings), str(settings), settings.model_dump_json(), caplog.text):
        assert JWT_SECRET not in rendered
        assert HASH_SECRET not in rendered


def test_validation_errors_do_not_echo_secret_values() -> None:
    with pytest.raises(ValidationError) as exc_info:
        production_settings(refresh_token_hash_secret=JWT_SECRET)

    assert JWT_SECRET not in str(exc_info.value)
