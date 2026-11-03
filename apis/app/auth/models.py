import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.auth.constants import (
    CLIENT_IP_PREFIX_MAX_LENGTH,
    REFRESH_TOKEN_HASH_LENGTH,
    USER_AGENT_MAX_LENGTH,
    RevocationReason,
)
from app.core.database import Base, str_enum
from app.users.models import User


class RefreshSession(Base):
    """One refresh token in a rotation family. Only a keyed hash of the token is stored."""

    __tablename__ = "refresh_sessions"
    __table_args__ = (
        CheckConstraint("expires_at > issued_at", name="expires_after_issued"),
        CheckConstraint(
            f"char_length(token_hash) = {REFRESH_TOKEN_HASH_LENGTH}", name="token_hash_length"
        ),
        CheckConstraint(
            "(revoked_at IS NULL) = (revoked_reason IS NULL)", name="revocation_complete"
        ),
        Index("ix_refresh_sessions_family_id", "family_id"),
        # Active sessions per user, for revoke-all and session listings.
        Index(
            "ix_refresh_sessions_active_user_expiry",
            "user_id",
            "expires_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        # Cleanup of expired and revoked sessions.
        Index("ix_refresh_sessions_expires_at", "expires_at"),
        Index(
            "ix_refresh_sessions_revoked_at",
            "revoked_at",
            postgresql_where=text("revoked_at IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    family_id: Mapped[uuid.UUID]
    # Unique so concurrent rotations of the same parent cannot both create a child.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_sessions.id", ondelete="SET NULL"), unique=True
    )
    token_hash: Mapped[str] = mapped_column(String(REFRESH_TOKEN_HASH_LENGTH), unique=True)
    issued_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    last_used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    revoked_reason: Mapped[RevocationReason | None] = mapped_column(
        str_enum(RevocationReason, "refresh_session_revoked_reason")
    )
    user_agent: Mapped[str | None] = mapped_column(String(USER_AGENT_MAX_LENGTH))
    client_ip_prefix: Mapped[str | None] = mapped_column(String(CLIENT_IP_PREFIX_MAX_LENGTH))

    user: Mapped[User] = relationship(lazy="raise")

    @validates("issued_at", "expires_at")
    def _expires_after_issued(self, key: str, value: datetime) -> datetime:
        issued_at = value if key == "issued_at" else self.issued_at
        expires_at = value if key == "expires_at" else self.expires_at
        if issued_at is not None and expires_at is not None and expires_at <= issued_at:
            raise ValueError("A refresh session must expire after it is issued.")
        return value

    def is_active(self, now: datetime) -> bool:
        """Whether the session may be used at ``now``. Requires ``user`` to be loaded."""
        return self.revoked_at is None and now < self.expires_at and self.user.is_active
