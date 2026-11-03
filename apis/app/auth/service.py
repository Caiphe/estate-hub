import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Self

from pwdlib import PasswordHash
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.constants import RevocationReason
from app.auth.errors import (
    DisabledUserError,
    ExpiredSessionError,
    IncorrectCurrentPasswordError,
    InvalidCredentialsError,
    InvalidSessionError,
    ReusedRefreshTokenError,
    SessionConflictError,
)
from app.auth.models import RefreshSession
from app.auth.permissions import Permission
from app.auth.policy import Actor, require_permissions
from app.auth.repository import RefreshSessionRepository
from app.auth.schemas import ClientMetadata
from app.core.config import Settings
from app.core.security.access_tokens import (
    AccessTokenConfig,
    IssuedAccessToken,
    create_access_token,
    utc_now,
)
from app.core.security.exceptions import MalformedRefreshTokenError, PasswordHashError
from app.core.security.opaque_tokens import (
    generate_refresh_token,
    hash_refresh_token,
    refresh_token_hash_key,
)
from app.core.security.passwords import (
    DEFAULT_PASSWORD_HASHER,
    PasswordCheck,
    hash_password,
    verify_dummy_password,
    verify_password,
)
from app.users.constants import EMAIL_MAX_LENGTH
from app.users.models import User
from app.users.repository import UserRepository

# A rotated token presented again within this window is treated as a concurrent request
# from the same client (for example two browser tabs), not as theft. It still gets no
# tokens; it just does not revoke the family.
DEFAULT_ROTATION_GRACE = timedelta(seconds=10)


@dataclass(frozen=True, slots=True)
class AuthConfig:
    access: AccessTokenConfig
    refresh_hash_key: bytes
    refresh_lifetime: timedelta
    rotation_grace: timedelta = DEFAULT_ROTATION_GRACE

    def __repr__(self) -> str:
        return (
            f"AuthConfig(access={self.access!r}, refresh_lifetime={self.refresh_lifetime!r}, "
            f"rotation_grace={self.rotation_grace!r})"
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(
            access=AccessTokenConfig.from_settings(settings),
            refresh_hash_key=refresh_token_hash_key(settings),
            refresh_lifetime=timedelta(days=settings.refresh_session_ttl_days),
        )


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """Result of a login or refresh. ``refresh_token`` is the only copy of the raw token."""

    user: User
    access_token: IssuedAccessToken
    refresh_token: str
    refresh_expires_at: datetime
    session_id: uuid.UUID
    family_id: uuid.UUID
    password_rehashed: bool = False

    def __repr__(self) -> str:
        return (
            f"IssuedSession(user_id={self.user.id}, session_id={self.session_id}, "
            f"family_id={self.family_id}, refresh_expires_at={self.refresh_expires_at!r})"
        )


@dataclass(frozen=True, slots=True)
class LogoutResult:
    revoked: bool
    user_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None


async def invalidate_user_sessions(
    db: AsyncSession, user_id: uuid.UUID, reason: RevocationReason, now: datetime
) -> int:
    """Revoke every active refresh session and invalidate every access token for a user.

    Does not commit: password change, account disabling, and administrator actions call
    this inside their own transaction. Returns the number of sessions revoked.
    """
    await UserRepository(db).increment_token_version(user_id)
    return await RefreshSessionRepository(db).revoke_all_for_user(user_id, reason, now)


class AuthService:
    """Credential authentication and refresh-session lifecycle.

    Every public method is one unit of work: it commits on success and rolls back on
    failure. The only exception is refresh-token reuse, which commits the family
    revocation before raising so the protection survives the error.
    """

    def __init__(
        self,
        db: AsyncSession,
        config: AuthConfig,
        *,
        clock: Callable[[], datetime] = utc_now,
        token_factory: Callable[[], str] = generate_refresh_token,
        password_hasher: PasswordHash = DEFAULT_PASSWORD_HASHER,
    ) -> None:
        self._db = db
        self._config = config
        self._clock = clock
        self._token_factory = token_factory
        self._hasher = password_hasher
        self._users = UserRepository(db)
        self._sessions = RefreshSessionRepository(db)

    async def authenticate(
        self, email: str, password: str, client: ClientMetadata | None = None
    ) -> IssuedSession:
        return await self._unit_of_work(lambda: self._authenticate(email, password, client))

    async def refresh(
        self, refresh_token: str, client: ClientMetadata | None = None
    ) -> IssuedSession:
        return await self._unit_of_work(lambda: self._refresh(refresh_token, client))

    async def logout(self, refresh_token: str | None) -> LogoutResult:
        return await self._unit_of_work(lambda: self._logout(refresh_token))

    async def change_password(
        self, user_id: uuid.UUID, current_password: str, new_password: str
    ) -> int:
        """Replace the password and sign the user out everywhere, atomically.

        Returns the number of refresh sessions revoked. Every access token issued before
        the change stops working because the token version is incremented.
        """
        return await self._unit_of_work(
            lambda: self._change_password(user_id, current_password, new_password)
        )

    async def revoke_all_sessions(
        self, actor: Actor, user_id: uuid.UUID, reason: RevocationReason
    ) -> int:
        """Sign a user out everywhere.

        Anyone may do this to their own account. Doing it to someone else requires
        ``staff:revoke_sessions``, checked here so non-HTTP callers cannot skip it.
        """
        if actor.user_id != user_id or not actor.active:
            require_permissions(actor, Permission.STAFF_REVOKE_SESSIONS)
        return await self._unit_of_work(
            lambda: invalidate_user_sessions(self._db, user_id, reason, self._now())
        )

    async def _unit_of_work[T](self, work: Callable[[], Awaitable[T]]) -> T:
        try:
            result = await work()
            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            raise
        return result

    async def _authenticate(
        self, email: str, password: str, client: ClientMetadata | None
    ) -> IssuedSession:
        normalized = email.strip().lower()
        user = (
            await self._users.get_by_email(normalized)
            if 0 < len(normalized) <= EMAIL_MAX_LENGTH
            else None
        )
        if user is None:
            # Same Argon2 work as a real check so timing does not reveal unknown emails.
            await asyncio.to_thread(verify_dummy_password, password, self._hasher)
            raise InvalidCredentialsError("unknown_email")

        check = await self._check_password(password, user.password_hash)
        if not check.valid:
            raise InvalidCredentialsError("wrong_password")
        # Checked only after the password so a disabled account is indistinguishable
        # from a wrong password to anyone without the password.
        if not user.is_active:
            raise DisabledUserError()

        now = self._now()
        if check.replacement_hash is not None:
            user.password_hash = check.replacement_hash
        user.last_login_at = now
        session, refresh_token = await self._start_session(
            user,
            family_id=uuid.uuid4(),
            parent_id=None,
            expires_at=now + self._config.refresh_lifetime,
            now=now,
            client=client,
        )
        return self._issued(
            user, session, refresh_token, now, password_rehashed=check.replacement_hash is not None
        )

    async def _change_password(
        self, user_id: uuid.UUID, current_password: str, new_password: str
    ) -> int:
        # Locking the row serializes concurrent changes for the same user.
        user = await self._users.get_by_id(user_id, for_update=True)
        if user is None or not user.is_active:
            raise InvalidSessionError("user_unavailable")
        if not (await self._check_password(current_password, user.password_hash)).valid:
            raise IncorrectCurrentPasswordError()
        user.password_hash = await asyncio.to_thread(hash_password, new_password, self._hasher)
        user.updated_by_id = user.id
        return await invalidate_user_sessions(
            self._db, user.id, RevocationReason.PASSWORD_CHANGED, self._now()
        )

    async def _check_password(self, password: str, password_hash: str) -> PasswordCheck:
        try:
            return await asyncio.to_thread(verify_password, password, password_hash, self._hasher)
        except PasswordHashError:
            return PasswordCheck(valid=False)

    async def _refresh(self, refresh_token: str, client: ClientMetadata | None) -> IssuedSession:
        token_hash = self._hash_or_reject(refresh_token)
        session = await self._sessions.get_by_token_hash(token_hash, for_update=True)
        if session is None:
            raise InvalidSessionError("unknown_session")

        now = self._now()
        if session.revoked_at is not None:
            await self._reject_revoked(session, now)
        if now >= session.expires_at:
            raise ExpiredSessionError()
        user = session.user
        if not user.is_active:
            raise InvalidSessionError("user_disabled")

        self._sessions.mark_revoked(session, RevocationReason.ROTATED, now)
        session.last_used_at = now
        try:
            # The child keeps the family's absolute expiry: refreshing never extends it.
            child, new_token = await self._start_session(
                user,
                family_id=session.family_id,
                parent_id=session.id,
                expires_at=session.expires_at,
                now=now,
                client=client,
            )
        except IntegrityError:
            # Backstop for the unique parent_id constraint; the row lock normally wins.
            raise SessionConflictError() from None
        return self._issued(user, child, new_token, now)

    async def _reject_revoked(self, session: RefreshSession, now: datetime) -> None:
        revoked_at = session.revoked_at
        assert revoked_at is not None
        if session.revoked_reason != RevocationReason.ROTATED:
            raise InvalidSessionError("session_revoked")
        if now - revoked_at <= self._config.rotation_grace:
            raise SessionConflictError()
        # A rotated token used again outside the grace window means a copy of it exists
        # elsewhere. Revoke the whole family and keep that revocation even though we raise.
        revoked = await self._sessions.revoke_family(
            session.family_id, RevocationReason.REUSE_DETECTED, now
        )
        await self._db.commit()
        raise ReusedRefreshTokenError(session.user_id, session.family_id, revoked)

    async def _logout(self, refresh_token: str | None) -> LogoutResult:
        if not refresh_token:
            return LogoutResult(revoked=False)
        try:
            token_hash = hash_refresh_token(refresh_token, self._config.refresh_hash_key)
        except MalformedRefreshTokenError:
            return LogoutResult(revoked=False)
        session = await self._sessions.get_by_token_hash(token_hash, for_update=True)
        if session is None or session.revoked_at is not None:
            return LogoutResult(revoked=False)
        self._sessions.mark_revoked(session, RevocationReason.LOGOUT, self._now())
        return LogoutResult(revoked=True, user_id=session.user_id, session_id=session.id)

    async def _start_session(
        self,
        user: User,
        *,
        family_id: uuid.UUID,
        parent_id: uuid.UUID | None,
        expires_at: datetime,
        now: datetime,
        client: ClientMetadata | None,
    ) -> tuple[RefreshSession, str]:
        refresh_token = self._token_factory()
        client = client or ClientMetadata()
        session = RefreshSession(
            id=uuid.uuid4(),
            user_id=user.id,
            family_id=family_id,
            parent_id=parent_id,
            token_hash=hash_refresh_token(refresh_token, self._config.refresh_hash_key),
            issued_at=now,
            expires_at=expires_at,
            user_agent=client.user_agent,
            client_ip_prefix=client.client_ip_prefix,
        )
        await self._sessions.add(session)
        return session, refresh_token

    def _issued(
        self,
        user: User,
        session: RefreshSession,
        refresh_token: str,
        now: datetime,
        *,
        password_rehashed: bool = False,
    ) -> IssuedSession:
        access_token = create_access_token(
            user.id, user.token_version, self._config.access, now=now
        )
        return IssuedSession(
            user=user,
            access_token=access_token,
            refresh_token=refresh_token,
            refresh_expires_at=session.expires_at,
            session_id=session.id,
            family_id=session.family_id,
            password_rehashed=password_rehashed,
        )

    def _hash_or_reject(self, refresh_token: str) -> str:
        try:
            return hash_refresh_token(refresh_token, self._config.refresh_hash_key)
        except MalformedRefreshTokenError:
            raise InvalidSessionError("malformed_token") from None

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("The service clock must return timezone-aware datetimes.")
        return now
