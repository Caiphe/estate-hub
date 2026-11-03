import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.security.access_tokens import (
    MAX_ACCESS_TOKEN_LENGTH,
    AccessTokenConfig,
    create_access_token,
    decode_access_token,
)
from app.core.security.exceptions import (
    ExpiredAccessTokenError,
    InvalidAccessTokenError,
    SecurityConfigurationError,
)

TEST_KEY = "test-only-access-token-key-0123456789abcdef"
NOW = datetime(2026, 11, 3, 12, 0, 0, tzinfo=UTC)
USER_ID = uuid.UUID("7d9f1f6c-3a1b-4c55-9a51-0f4b6f5f6a10")
CONFIG = AccessTokenConfig(
    secret_key=TEST_KEY,
    algorithm="HS256",
    issuer="estatehub-api",
    audience="estatehub-staff",
    lifetime=timedelta(minutes=15),
)


def valid_payload(**overrides: Any) -> dict[str, Any]:
    timestamp = int(NOW.timestamp())
    payload: dict[str, Any] = {
        "iss": "estatehub-api",
        "aud": "estatehub-staff",
        "sub": str(USER_ID),
        "iat": timestamp,
        "nbf": timestamp,
        "exp": timestamp + 900,
        "jti": uuid.uuid4().hex,
        "typ": "access",
        "ver": 2,
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None}


def sign(payload: dict[str, Any], key: str = TEST_KEY, algorithm: str = "HS256") -> str:
    return jwt.encode(payload, key, algorithm=algorithm)


def assert_rejected(token: str, reason: str, now: datetime = NOW) -> None:
    with pytest.raises(InvalidAccessTokenError) as error:
        decode_access_token(token, CONFIG, now=now)

    assert error.value.reason == reason
    # Library exceptions are never chained into ours.
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ or error.value.__context__ is None


def test_valid_token_round_trips() -> None:
    issued = create_access_token(USER_ID, 2, CONFIG, now=NOW.replace(microsecond=123))

    claims = decode_access_token(issued.token, CONFIG, now=NOW + timedelta(minutes=5))

    assert claims == issued.claims
    assert claims.user_id == USER_ID
    assert claims.token_version == 2
    assert claims.issued_at == claims.not_before == NOW
    assert claims.expires_at == NOW + timedelta(minutes=15)
    assert issued.expires_in == 900


def test_token_contains_only_the_required_claims() -> None:
    token = create_access_token(USER_ID, 0, CONFIG, now=NOW).token

    payload = jwt.decode(token, options={"verify_signature": False})
    header = jwt.get_unverified_header(token)

    assert set(payload) == {"iss", "aud", "sub", "iat", "nbf", "exp", "jti", "typ", "ver"}
    assert header == {"alg": "HS256", "typ": "JWT"}


def test_token_ids_are_unique() -> None:
    ids = {create_access_token(USER_ID, 0, CONFIG, now=NOW).claims.token_id for _ in range(50)}

    assert len(ids) == 50


def test_expiry_is_exclusive() -> None:
    token = create_access_token(USER_ID, 0, CONFIG, now=NOW).token
    expires_at = NOW + CONFIG.lifetime

    decode_access_token(token, CONFIG, now=expires_at - timedelta(seconds=1))
    with pytest.raises(ExpiredAccessTokenError) as error:
        decode_access_token(token, CONFIG, now=expires_at)
    assert error.value.reason == "token_expired"


def test_token_used_before_issue_is_rejected() -> None:
    token = create_access_token(USER_ID, 0, CONFIG, now=NOW).token

    assert_rejected(token, "not_yet_valid", now=NOW - timedelta(seconds=1))
    decode_access_token(token, CONFIG, now=NOW - timedelta(seconds=1), leeway=timedelta(seconds=5))


def test_tampered_payload_is_rejected() -> None:
    header, _, signature = create_access_token(USER_ID, 0, CONFIG, now=NOW).token.split(".")
    forged = base64.urlsafe_b64encode(
        json.dumps(valid_payload(sub=str(uuid.uuid4()))).encode()
    ).rstrip(b"=")

    assert_rejected(f"{header}.{forged.decode()}.{signature}", "bad_signature")


def test_wrong_key_is_rejected() -> None:
    assert_rejected(sign(valid_payload(), key="another-test-key-0123456789abcdef"), "bad_signature")


@pytest.mark.parametrize("algorithm", ["HS512", "none"])
def test_algorithm_outside_the_allowlist_is_rejected(algorithm: str) -> None:
    key = "" if algorithm == "none" else TEST_KEY * 2
    token = jwt.encode(valid_payload(), key, algorithm=algorithm)

    assert_rejected(token, "algorithm_not_allowed")


def test_wrong_issuer_and_audience_are_rejected() -> None:
    assert_rejected(sign(valid_payload(iss="someone-else")), "wrong_issuer")
    assert_rejected(sign(valid_payload(aud="public-site")), "wrong_audience")


@pytest.mark.parametrize("claim", ["iss", "aud", "sub", "iat", "nbf", "exp", "jti", "typ", "ver"])
def test_missing_claims_are_rejected(claim: str) -> None:
    payload = valid_payload()
    del payload[claim]

    assert_rejected(sign(payload), "missing_claim")


def test_wrong_purpose_is_rejected() -> None:
    assert_rejected(sign(valid_payload(typ="refresh")), "wrong_purpose")


@pytest.mark.parametrize(
    "subject",
    ["not-a-uuid", str(USER_ID).upper(), USER_ID.hex, "", "00000000-0000-0000-0000", 123],
)
def test_malformed_subject_is_rejected(subject: object) -> None:
    assert_rejected(sign(valid_payload(sub=subject)), "malformed_subject")


@pytest.mark.parametrize("version", ["2", True, -1, 1.5, [], {}])
def test_malformed_token_version_is_rejected(version: object) -> None:
    assert_rejected(sign(valid_payload(ver=version)), "malformed_token_version")


@pytest.mark.parametrize("token_id", ["", "short", "Z" * 32, 12345])
def test_malformed_token_id_is_rejected(token_id: object) -> None:
    assert_rejected(sign(valid_payload(jti=token_id)), "malformed_token_id")


def test_inconsistent_time_claims_are_rejected() -> None:
    timestamp = int(NOW.timestamp())

    assert_rejected(sign(valid_payload(exp=timestamp)), "inconsistent_time_claims")
    assert_rejected(sign(valid_payload(nbf=timestamp - 1)), "inconsistent_time_claims")


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "x" * (MAX_ACCESS_TOKEN_LENGTH + 1)])
def test_garbage_is_rejected(token: str) -> None:
    assert_rejected(token, "malformed")


def test_naive_clock_values_are_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        create_access_token(USER_ID, 0, CONFIG, now=datetime(2026, 11, 3))


def test_negative_token_version_cannot_be_issued() -> None:
    with pytest.raises(ValueError):
        create_access_token(USER_ID, -1, CONFIG, now=NOW)


def test_representations_hide_secrets_and_tokens() -> None:
    issued = create_access_token(USER_ID, 0, CONFIG, now=NOW)

    assert TEST_KEY not in repr(CONFIG)
    assert issued.token not in repr(issued)


def test_config_from_settings() -> None:
    settings = Settings(
        _env_file=None,
        jwt_secret_key=SecretStr(TEST_KEY),
        jwt_algorithm="HS384",
        access_token_ttl_minutes=10,
    )

    config = AccessTokenConfig.from_settings(settings)

    assert (config.algorithm, config.lifetime) == ("HS384", timedelta(minutes=10))
    with pytest.raises(SecurityConfigurationError):
        AccessTokenConfig.from_settings(Settings(_env_file=None, jwt_secret_key=None))
