from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.auth.constants import USER_AGENT_MAX_LENGTH
from app.auth.schemas import ClientMetadata
from app.models import RefreshSession, User
from app.users.constants import UserStatus

ISSUED_AT = datetime(2026, 11, 3, 12, tzinfo=UTC)


def make_session(status: UserStatus = UserStatus.ACTIVE) -> RefreshSession:
    user = User(email="agent@estatehub.example", full_name="Ada", password_hash="h", status=status)
    return RefreshSession(
        user=user,
        family_id=uuid4(),
        token_hash="a" * 64,
        issued_at=ISSUED_AT,
        expires_at=ISSUED_AT + timedelta(days=7),
    )


def test_session_is_active_until_expiry() -> None:
    session = make_session()

    assert session.is_active(ISSUED_AT)
    assert session.is_active(session.expires_at - timedelta(seconds=1))
    assert not session.is_active(session.expires_at)


def test_revoked_session_is_not_active() -> None:
    session = make_session()
    session.revoked_at = ISSUED_AT + timedelta(minutes=1)

    assert not session.is_active(ISSUED_AT + timedelta(minutes=2))


def test_session_of_disabled_user_is_not_active() -> None:
    assert not make_session(UserStatus.DISABLED).is_active(ISSUED_AT)


@pytest.mark.parametrize("expires_at", [ISSUED_AT, ISSUED_AT - timedelta(seconds=1)])
def test_session_must_expire_after_it_is_issued(expires_at: datetime) -> None:
    with pytest.raises(ValueError, match="expire after"):
        RefreshSession(issued_at=ISSUED_AT, expires_at=expires_at)


def test_session_issue_time_cannot_move_past_expiry() -> None:
    session = make_session()

    with pytest.raises(ValueError, match="expire after"):
        session.issued_at = session.expires_at


def test_session_model_has_no_raw_token_column() -> None:
    columns = set(RefreshSession.__table__.columns.keys())

    assert "token_hash" in columns
    assert not {"token", "refresh_token", "raw_token"} & columns


@pytest.mark.parametrize(
    ("client_ip", "expected"),
    [
        ("203.0.113.77", "203.0.113.0/24"),
        ("2001:db8:1234:5678::1", "2001:db8:1234::/48"),
        ("::ffff:198.51.100.9", "198.51.100.0/24"),
        ("not-an-ip", None),
        (None, None),
    ],
)
def test_client_ip_is_reduced_to_a_network_prefix(
    client_ip: str | None, expected: str | None
) -> None:
    assert ClientMetadata.from_request_values(None, client_ip).client_ip_prefix == expected


def test_user_agent_is_cleaned_and_truncated() -> None:
    metadata = ClientMetadata.from_request_values("Mozilla/5.0\r\n\x00 Evil" + "x" * 500, None)

    assert metadata.user_agent is not None
    assert metadata.user_agent.startswith("Mozilla/5.0 Evil")
    assert len(metadata.user_agent) == USER_AGENT_MAX_LENGTH
    assert ClientMetadata.from_request_values(" \t ", None).user_agent is None
