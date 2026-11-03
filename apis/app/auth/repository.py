import uuid
from datetime import datetime

from sqlalchemy import ColumnElement, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.constants import RevocationReason
from app.auth.models import RefreshSession
from app.users.models import User


class RefreshSessionRepository:
    """Refresh-session persistence. Never commits; the calling service owns the transaction."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def add(self, session: RefreshSession) -> None:
        self._db.add(session)
        await self._db.flush()

    async def get_by_token_hash(
        self, token_hash: str, *, for_update: bool = False
    ) -> RefreshSession | None:
        """Load a session with its user and the user's roles.

        With ``for_update`` only the session row is locked, so concurrent rotations of the
        same token run one after another.
        """
        statement = (
            select(RefreshSession)
            .where(RefreshSession.token_hash == token_hash)
            .options(joinedload(RefreshSession.user).selectinload(User.roles))
            # Security decisions must see the current rows, not session-cached attributes.
            .execution_options(populate_existing=True)
        )
        if for_update:
            statement = statement.with_for_update(of=RefreshSession)
        return (await self._db.scalars(statement)).unique().one_or_none()

    @staticmethod
    def mark_revoked(session: RefreshSession, reason: RevocationReason, now: datetime) -> None:
        session.revoked_at = now
        session.revoked_reason = reason

    async def revoke_family(
        self, family_id: uuid.UUID, reason: RevocationReason, now: datetime
    ) -> int:
        return await self._revoke_where(RefreshSession.family_id == family_id, reason, now)

    async def revoke_all_for_user(
        self, user_id: uuid.UUID, reason: RevocationReason, now: datetime
    ) -> int:
        return await self._revoke_where(RefreshSession.user_id == user_id, reason, now)

    async def _revoke_where(
        self, condition: ColumnElement[bool], reason: RevocationReason, now: datetime
    ) -> int:
        statement = (
            update(RefreshSession)
            .where(condition, RefreshSession.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason=reason)
            .returning(RefreshSession.id)
            .execution_options(synchronize_session="fetch")
        )
        return len((await self._db.execute(statement)).all())
