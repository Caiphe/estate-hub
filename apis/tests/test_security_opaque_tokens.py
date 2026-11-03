import re
import subprocess
import sys

import pytest
from pydantic import SecretStr

from app.auth.constants import REFRESH_TOKEN_HASH_LENGTH
from app.core.config import Settings
from app.core.security.exceptions import MalformedRefreshTokenError, SecurityConfigurationError
from app.core.security.opaque_tokens import (
    TOKEN_BYTES,
    csrf_tokens_match,
    generate_csrf_token,
    generate_refresh_token,
    hash_refresh_token,
    refresh_token_hash_key,
    refresh_token_matches,
)

KEY = b"test-only-refresh-hash-key-0123456789abcdef"
OTHER_KEY = b"test-only-other-refresh-hash-key-0123456789"
URL_SAFE = re.compile(r"^[A-Za-z0-9_-]+$")


def alter(token: str) -> str:
    return token[:-1] + ("A" if token[-1] != "A" else "B")


def test_tokens_have_at_least_256_bits_of_entropy() -> None:
    assert TOKEN_BYTES * 8 >= 256


@pytest.mark.parametrize("generate", [generate_refresh_token, generate_csrf_token])
def test_tokens_are_unique_and_url_safe(generate: object) -> None:
    assert callable(generate)
    tokens = {generate() for _ in range(1_000)}

    assert len(tokens) == 1_000
    for token in tokens:
        assert URL_SAFE.fullmatch(token)
        assert len(token) == 43


def test_refresh_hash_is_keyed_and_never_the_token() -> None:
    token = generate_refresh_token()

    stored = hash_refresh_token(token, KEY)

    assert stored != token
    assert token not in stored
    assert len(stored) == REFRESH_TOKEN_HASH_LENGTH
    assert stored == hash_refresh_token(token, KEY)
    assert stored != hash_refresh_token(token, OTHER_KEY)


def test_refresh_token_matching() -> None:
    token = generate_refresh_token()
    stored = hash_refresh_token(token, KEY)

    assert refresh_token_matches(token, stored, KEY)
    assert not refresh_token_matches(alter(token), stored, KEY)
    assert not refresh_token_matches(token, stored, OTHER_KEY)
    assert not refresh_token_matches(token, alter(stored), KEY)
    assert not refresh_token_matches("not a token", stored, KEY)


@pytest.mark.parametrize(
    "token", ["", "short", "a" * 44, "a" * 42 + "=", "é" * 43, "a" * 42 + "\n"]
)
def test_malformed_refresh_tokens_cannot_be_hashed(token: str) -> None:
    with pytest.raises(MalformedRefreshTokenError) as error:
        hash_refresh_token(token, KEY)

    assert token not in str(error.value) or not token


def test_hash_key_comes_from_settings() -> None:
    settings = Settings(
        _env_file=None,
        refresh_token_hash_secret=SecretStr(KEY.decode()),
    )

    assert refresh_token_hash_key(settings) == KEY
    with pytest.raises(SecurityConfigurationError):
        refresh_token_hash_key(Settings(_env_file=None, refresh_token_hash_secret=None))


def test_csrf_tokens_match_only_when_identical() -> None:
    token = generate_csrf_token()

    assert csrf_tokens_match(token, token)
    assert not csrf_tokens_match(token, alter(token))
    assert not csrf_tokens_match(token, generate_csrf_token())


@pytest.mark.parametrize(
    ("cookie", "header"),
    [
        (None, None),
        ("", ""),
        (None, "x" * 43),
        ("x" * 43, None),
        ("x" * 43, "x" * 42),
        ("é" * 43, "é" * 43),
        ("x" * 43 + ",x", "x" * 43 + ",x"),
    ],
)
def test_missing_or_malformed_csrf_values_never_match(
    cookie: str | None, header: str | None
) -> None:
    assert not csrf_tokens_match(cookie, header)


def test_security_modules_have_no_framework_dependencies() -> None:
    code = (
        "import sys\n"
        "import app.core.security.access_tokens, app.core.security.opaque_tokens\n"
        "import app.core.security.passwords\n"
        "loaded = {name.split('.')[0] for name in sys.modules}\n"
        "print(sorted(loaded & {'fastapi', 'starlette', 'sqlalchemy', 'redis'}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "[]"
