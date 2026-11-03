"""Authentication service tests against PostgreSQL with an injected clock and tokens."""

import asyncio
import itertools
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import service as auth_service
from app.auth.constants import AuthErrorCode, RevocationReason
from app.auth.errors import (
    AuthServiceError,
    DisabledUserError,
    ExpiredSessionError,
    InvalidCredentialsError,
    InvalidSessionError,
    ReusedRefreshTokenError,
    SessionConflictError,
)
from app.auth.models import RefreshSession
from app.auth.policy import Actor
from app.auth.schemas import ClientMetadata
from app.auth.service import AuthConfig, AuthService, IssuedSession
from app.core.security.access_tokens import AccessTokenConfig, decode_access_token
from app.core.security.opaque_tokens import hash_refresh_token
from app.core.security.passwords import hash_password
from app.users.constants import RoleCode, UserStatus
from app.users.models import Role, User
from app.users.schemas import UserPublic

FAST = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8_192, parallelism=1),))
PASSWORD = "correct horse battery staple"
EMAIL = "ada.agent@estatehub.example"
START = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
CONFIG = AuthConfig(
    access=AccessTokenConfig(
        secret_key="test-only-access-token-key-0123456789abcdef",
        algorithm="HS256",
        issuer="estatehub-api",
        audience="estatehub-staff",
        lifetime=timedelta(minutes=15),
    ),
    refresh_hash_key=b"test-only-refresh-hash-key-0123456789abcdef",
    refresh_lifetime=timedelta(days=7),
)
CLIENT = ClientMetadata.from_request_values("Mozilla/5.0 Test", "203.0.113.42")

Sessions = async_sessionmaker[AsyncSession]


@dataclass
class Clock:
    now: datetime = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@dataclass
class Tokens:
    """Deterministic, valid-shaped refresh tokens."""

    counter: itertools.count[int] = field(default_factory=itertools.count)
    issued: list[str] = field(default_factory=list)

    def __call__(self) -> str:
        token = f"test-token-{next(self.counter):032d}"
        self.issued.append(token)
        return token


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def tokens() -> Tokens:
    return Tokens()


@pytest.fixture
async def db(session_factory: Sessions) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest.fixture
def make_service(
    session_factory: Sessions, clock: Clock, tokens: Tokens
) -> Callable[[AsyncSession], AuthService]:
    def build(session: AsyncSession, hasher: PasswordHash = FAST) -> AuthService:
        return AuthService(
            session, CONFIG, clock=clock, token_factory=tokens, password_hasher=hasher
        )

    return build


@pytest.fixture
async def user(db: AsyncSession) -> User:
    return await create_user(db, EMAIL)


async def create_user(
    db: AsyncSession,
    email: str,
    status: UserStatus = UserStatus.ACTIVE,
    password_hash: str | None = None,
) -> User:
    agent = (await db.scalars(select(Role).where(Role.code == RoleCode.AGENT))).one()
    created = User(
        email=email,
        full_name="Ada Agent",
        password_hash=password_hash or hash_password(PASSWORD, FAST),
        status=status,
    )
    created.roles = [agent]
    db.add(created)
    await db.commit()
    return created


def id_of(user: User) -> uuid.UUID:
    """Primary key without I/O: a rolled-back session expires every loaded attribute."""
    identity = inspect(user).identity
    assert identity is not None
    user_id: uuid.UUID = identity[0]
    return user_id


async def sessions_of(db: AsyncSession, user: User) -> list[RefreshSession]:
    user_id = id_of(user)
    db.expire_all()
    result = await db.scalars(
        select(RefreshSession)
        .where(RefreshSession.user_id == user_id)
        .order_by(RefreshSession.issued_at, RefreshSession.parent_id.nulls_first())
    )
    return list(result)


async def login(service: AuthService) -> IssuedSession:
    return await service.authenticate(EMAIL, PASSWORD, CLIENT)


# --- Credential authentication ---------------------------------------------------------


async def test_login_issues_tokens_and_persists_only_a_hash(
    db: AsyncSession, make_service: Callable[[AsyncSession], AuthService], user: User
) -> None:
    issued = await make_service(db).authenticate("  Ada.Agent@EstateHub.Example ", PASSWORD, CLIENT)

    claims = decode_access_token(issued.access_token.token, CONFIG.access, now=START)
    assert claims.user_id == user.id
    assert claims.token_version == 0
    assert issued.refresh_expires_at == START + timedelta(days=7)

    (stored,) = await sessions_of(db, user)
    assert stored.id == issued.session_id
    assert stored.family_id == issued.family_id
    assert stored.parent_id is None
    assert stored.token_hash == hash_refresh_token(issued.refresh_token, CONFIG.refresh_hash_key)
    assert issued.refresh_token not in {
        stored.token_hash,
        stored.user_agent,
        stored.client_ip_prefix,
    }
    assert (stored.user_agent, stored.client_ip_prefix) == ("Mozilla/5.0 Test", "203.0.113.0/24")
    assert stored.revoked_at is None

    await db.refresh(user)
    assert user.last_login_at == START


async def test_login_result_serializes_without_lazy_loading(
    db: AsyncSession, make_service: Callable[[AsyncSession], AuthService], user: User
) -> None:
    issued = await login(make_service(db))

    public = UserPublic.model_validate(issued.user)

    assert public.roles == ["agent"]
    assert public.last_login_at == START
    assert issued.refresh_token not in repr(issued)


@pytest.mark.parametrize(
    ("email", "password", "reason"),
    [
        (EMAIL, "wrong password entirely", "wrong_password"),
        ("nobody@estatehub.example", PASSWORD, "unknown_email"),
        ("", PASSWORD, "unknown_email"),
        ("x" * 300 + "@estatehub.example", PASSWORD, "unknown_email"),
        (EMAIL, "", "wrong_password"),
    ],
)
async def test_invalid_credentials_share_one_public_contract(
    db: AsyncSession,
    make_service: Callable[[AsyncSession], AuthService],
    user: User,
    email: str,
    password: str,
    reason: str,
) -> None:
    with pytest.raises(InvalidCredentialsError) as error:
        await make_service(db).authenticate(email, password)

    assert type(error.value) is InvalidCredentialsError
    assert error.value.reason == reason
    assert error.value.public_code == AuthErrorCode.INVALID_CREDENTIALS
    assert await sessions_of(db, user) == []


async def test_unknown_email_spends_password_work(
    db: AsyncSession,
    make_service: Callable[[AsyncSession], AuthService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(auth_service, "verify_dummy_password", lambda pw, _: calls.append(pw))

    with pytest.raises(InvalidCredentialsError):
        await make_service(db).authenticate("nobody@estatehub.example", PASSWORD)

    assert calls == [PASSWORD]


async def test_disabled_user_is_publicly_indistinguishable(
    db: AsyncSession, make_service: Callable[[AsyncSession], AuthService]
) -> None:
    disabled = await create_user(db, EMAIL, UserStatus.DISABLED)

    with pytest.raises(DisabledUserError) as error:
        await login(make_service(db))
    assert error.value.public_code == AuthErrorCode.INVALID_CREDENTIALS

    with pytest.raises(InvalidCredentialsError) as wrong:
        await make_service(db).authenticate(EMAIL, "wrong password entirely")
    assert wrong.value.reason == "wrong_password"
    assert await sessions_of(db, disabled) == []


async def test_unrecognized_stored_hash_fails_as_invalid_credentials(
    db: AsyncSession, make_service: Callable[[AsyncSession], AuthService]
) -> None:
    await create_user(db, EMAIL, password_hash="not-a-real-hash")

    with pytest.raises(InvalidCredentialsError):
        await login(make_service(db))


async def test_outdated_password_hash_is_upgraded_on_login(
    db: AsyncSession, make_service: Callable[[AsyncSession], AuthService]
) -> None:
    weaker = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=4_096, parallelism=1),))
    created = await create_user(db, EMAIL, password_hash=hash_password(PASSWORD, weaker))
    old_hash = created.password_hash

    issued = await login(make_service(db))

    assert issued.password_rehashed
    await db.refresh(created)
    assert created.password_hash != old_hash
    assert "m=8192,t=1,p=1" in created.password_hash


# --- Refresh rotation -----------------------------------------------------------------


async def test_rotation_creates_one_child_and_revokes_the_parent(
    db: AsyncSession,
    make_service: Callable[[AsyncSession], AuthService],
    clock: Clock,
    user: User,
) -> None:
    first = await login(make_service(db))
    clock.advance(minutes=20)

    second = await make_service(db).refresh(first.refresh_token, CLIENT)

    assert second.refresh_token != first.refresh_token
    assert second.family_id == first.family_id
    assert second.refresh_expires_at == first.refresh_expires_at
    assert decode_access_token(second.access_token.token, CONFIG.access, now=clock.now)

    parent, child = await sessions_of(db, user)
    assert parent.revoked_reason == RevocationReason.ROTATED
    assert parent.revoked_at == parent.last_used_at == clock.now
    assert child.parent_id == parent.id
    assert child.family_id == parent.family_id
    assert child.revoked_at is None


async def test_refresh_uses_the_current_token_version(
    db: AsyncSession, make_service: Callable[[AsyncSession], AuthService], user: User
) -> None:
    first = await login(make_service(db))
    await db.execute(text("UPDATE users SET token_version = 7 WHERE id = :id"), {"id": user.id})
    await db.commit()

    second = await make_service(db).refresh(first.refresh_token)

    assert second.access_token.claims.token_version == 7


@pytest.mark.parametrize("value", ["", "abc", "x" * 44, "é" * 43, "test-token-" + "9" * 32])
async def test_malformed_and_unknown_tokens_are_invalid_sessions(
    db: AsyncSession, make_service: Callable[[AsyncSession], AuthService], value: str
) -> None:
    with pytest.raises(InvalidSessionError) as error:
        await make_service(db).refresh(value)

    assert type(error.value) is InvalidSessionError
    assert error.value.reason in {"malformed_token", "unknown_session"}
    assert error.value.public_code == AuthErrorCode.INVALID_SESSION


async def test_expired_session_is_rejected(
    db: AsyncSession,
    make_service: Callable[[AsyncSession], AuthService],
    clock: Clock,
    user: User,
) -> None:
    issued = await login(make_service(db))
    clock.now = issued.refresh_expires_at

    with pytest.raises(ExpiredSessionError):
        await make_service(db).refresh(issued.refresh_token)

    (stored,) = await sessions_of(db, user)
    assert stored.revoked_at is None


async def test_logged_out_session_cannot_refresh(
    db: AsyncSession, make_service: Callable[[AsyncSession], AuthService], user: User
) -> None:
    issued = await login(make_service(db))
    await make_service(db).logout(issued.refresh_token)

    with pytest.raises(InvalidSessionError) as error:
        await make_service(db).refresh(issued.refresh_token)

    assert error.value.reason == "session_revoked"


async def test_disabled_user_cannot_refresh(
    db: AsyncSession, make_service: Callable[[AsyncSession], AuthService], user: User
) -> None:
    issued = await login(make_service(db))
    await db.execute(text("UPDATE users SET status = 'disabled' WHERE id = :id"), {"id": user.id})
    await db.commit()

    with pytest.raises(InvalidSessionError) as error:
        await make_service(db).refresh(issued.refresh_token)

    assert error.value.reason == "user_disabled"


async def test_reuse_revokes_the_whole_family(
    db: AsyncSession,
    make_service: Callable[[AsyncSession], AuthService],
    clock: Clock,
    user: User,
) -> None:
    first = await login(make_service(db))
    other_family = await login(make_service(db))
    clock.advance(minutes=1)
    second = await make_service(db).refresh(first.refresh_token)
    clock.advance(minutes=1)

    with pytest.raises(ReusedRefreshTokenError) as error:
        await make_service(db).refresh(first.refresh_token)

    assert (error.value.user_id, error.value.family_id) == (id_of(user), first.family_id)
    assert error.value.revoked_sessions == 1
    assert error.value.public_code == AuthErrorCode.INVALID_SESSION
    with pytest.raises(InvalidSessionError):
        await make_service(db).refresh(second.refresh_token)

    stored = {s.id: s for s in await sessions_of(db, user)}
    assert stored[second.session_id].revoked_reason == RevocationReason.REUSE_DETECTED
    # Other devices' sessions are untouched.
    assert stored[other_family.session_id].revoked_at is None


async def test_replay_within_the_grace_window_is_a_conflict(
    db: AsyncSession,
    make_service: Callable[[AsyncSession], AuthService],
    clock: Clock,
    user: User,
) -> None:
    first = await login(make_service(db))
    second = await make_service(db).refresh(first.refresh_token)
    clock.advance(seconds=5)

    with pytest.raises(SessionConflictError):
        await make_service(db).refresh(first.refresh_token)

    assert (await make_service(db).refresh(second.refresh_token)).family_id == first.family_id


async def test_concurrent_rotations_allow_exactly_one_success(
    session_factory: Sessions,
    make_service: Callable[[AsyncSession], AuthService],
    db: AsyncSession,
    user: User,
) -> None:
    issued = await login(make_service(db))

    async def attempt() -> IssuedSession | AuthServiceError:
        async with session_factory() as own_session:
            try:
                return await make_service(own_session).refresh(issued.refresh_token)
            except AuthServiceError as exc:
                return exc

    results = await asyncio.gather(*(attempt() for _ in range(5)))

    successes = [r for r in results if isinstance(r, IssuedSession)]
    conflicts = [r for r in results if isinstance(r, SessionConflictError)]
    assert (len(successes), len(conflicts)) == (1, 4)
    stored = await sessions_of(db, user)
    assert len(stored) == 2
    assert sum(s.revoked_at is None for s in stored) == 1


# --- Revocation -----------------------------------------------------------------------


async def test_logout_is_idempotent(
    db: AsyncSession, make_service: Callable[[AsyncSession], AuthService], user: User
) -> None:
    issued = await login(make_service(db))

    first = await make_service(db).logout(issued.refresh_token)
    second = await make_service(db).logout(issued.refresh_token)

    assert (first.revoked, first.user_id, first.session_id) == (
        True,
        id_of(user),
        issued.session_id,
    )
    assert not second.revoked
    (stored,) = await sessions_of(db, user)
    assert stored.revoked_reason == RevocationReason.LOGOUT


@pytest.mark.parametrize("value", [None, "", "garbage", "test-token-" + "9" * 32])
async def test_logout_without_a_valid_session_is_a_no_op(
    db: AsyncSession, make_service: Callable[[AsyncSession], AuthService], value: str | None
) -> None:
    assert not (await make_service(db).logout(value)).revoked


async def test_revoke_all_invalidates_sessions_and_access_tokens(
    db: AsyncSession, make_service: Callable[[AsyncSession], AuthService], user: User
) -> None:
    first = await login(make_service(db))
    second = await login(make_service(db))
    await make_service(db).logout(second.refresh_token)

    revoked = await make_service(db).revoke_all_sessions(
        Actor.from_user(user), user.id, RevocationReason.PASSWORD_CHANGED
    )

    assert revoked == 1
    await db.refresh(user)
    assert user.token_version == first.access_token.claims.token_version + 1
    reasons = {s.id: s.revoked_reason for s in await sessions_of(db, user)}
    assert reasons == {
        first.session_id: RevocationReason.PASSWORD_CHANGED,
        second.session_id: RevocationReason.LOGOUT,
    }
    with pytest.raises(InvalidSessionError):
        await make_service(db).refresh(first.refresh_token)


async def test_failed_unit_of_work_rolls_back(
    db: AsyncSession,
    make_service: Callable[[AsyncSession], AuthService],
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*_: object, **__: object) -> None:
        raise RuntimeError("token signing failed")

    monkeypatch.setattr(auth_service, "create_access_token", explode)

    with pytest.raises(RuntimeError):
        await login(make_service(db))

    assert await sessions_of(db, user) == []
    await db.refresh(user)
    assert user.last_login_at is None


async def test_raw_tokens_and_passwords_are_never_logged(
    db: AsyncSession,
    make_service: Callable[[AsyncSession], AuthService],
    tokens: Tokens,
    clock: Clock,
    user: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        issued = await login(make_service(db))
        await make_service(db).refresh(issued.refresh_token)
        clock.advance(minutes=5)
        with pytest.raises(ReusedRefreshTokenError):
            await make_service(db).refresh(issued.refresh_token)

    for secret in [PASSWORD, *tokens.issued]:
        assert secret not in caplog.text
