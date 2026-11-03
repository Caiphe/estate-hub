from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.auth.constants import AUTH_ERRORS, AuthErrorCode
from app.auth.schemas import TokenResponse, UserIdentity
from app.core.errors import ErrorResponse
from app.main import app


def test_token_response_is_oauth2_compatible() -> None:
    token = TokenResponse(access_token="opaque-access-token", expires_in=900)

    assert token.model_dump() == {
        "access_token": "opaque-access-token",
        "token_type": "bearer",
        "expires_in": 900,
    }


def test_token_response_never_carries_a_refresh_token() -> None:
    token = TokenResponse.model_validate(
        {"access_token": "a", "expires_in": 900, "refresh_token": "must-not-leak"}
    )

    assert "refresh_token" not in token.model_dump()


@pytest.mark.parametrize("expires_in", [0, -1])
def test_token_response_requires_positive_lifetime(expires_in: int) -> None:
    with pytest.raises(ValidationError):
        TokenResponse(access_token="a", expires_in=expires_in)


def test_user_identity_serializes_only_documented_fields() -> None:
    user_id = uuid4()
    identity = UserIdentity.model_validate(
        {
            "id": user_id,
            "email": "agent@estatehub.example",
            "full_name": "Ada Agent",
            "roles": ["agent"],
            "password_hash": "$argon2id$secret",
            "token_version": 3,
        }
    )

    assert identity.model_dump() == {
        "id": user_id,
        "email": "agent@estatehub.example",
        "full_name": "Ada Agent",
        "roles": ["agent"],
    }


def test_error_response_serializes_the_standard_body() -> None:
    body = ErrorResponse.model_validate(
        {"error": {"code": "invalid_credentials", "message": "m", "request_id": "r"}}
    )

    assert body.model_dump() == {
        "error": {"code": "invalid_credentials", "message": "m", "fields": {}, "request_id": "r"}
    }


def test_every_error_code_has_a_public_contract() -> None:
    assert set(AUTH_ERRORS) == set(AuthErrorCode)
    assert len({code.value for code in AuthErrorCode}) == len(AuthErrorCode)


@pytest.mark.parametrize("code", list(AuthErrorCode))
def test_error_messages_do_not_disclose_account_state(code: AuthErrorCode) -> None:
    message = AUTH_ERRORS[code].message.lower()

    for word in ("exist", "disabled", "not found", "unknown", "reuse", "revoked", "locked"):
        assert word not in message


def test_openapi_contains_no_secrets() -> None:
    schema = str(app.openapi())

    for secret_field in ("jwt_secret_key", "refresh_token_hash_secret", "password_hash"):
        assert secret_field not in schema
