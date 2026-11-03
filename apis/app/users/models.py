import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.core.database import Base, TimestampMixin, str_enum
from app.users.constants import (
    EMAIL_MAX_LENGTH,
    FULL_NAME_MAX_LENGTH,
    ROLE_CODE_MAX_LENGTH,
    ROLE_DESCRIPTION_MAX_LENGTH,
    ROLE_NAME_MAX_LENGTH,
    UserStatus,
)

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    # The composite primary key already serves user lookups; this serves role lookups.
    Index("ix_user_roles_role_id", "role_id"),
)


class Role(TimestampMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (CheckConstraint("code ~ '^[a-z][a-z_]*$'", name="code_format"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(ROLE_CODE_MAX_LENGTH), unique=True)
    name: Mapped[str] = mapped_column(String(ROLE_NAME_MAX_LENGTH))
    description: Mapped[str] = mapped_column(
        String(ROLE_DESCRIPTION_MAX_LENGTH), default="", server_default=""
    )

    @validates("code")
    def _code_is_immutable(self, _: str, code: str) -> str:
        if self.code is not None and self.code != code:
            raise ValueError("A role code cannot be changed once set.")
        return code


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("email = lower(btrim(email))", name="email_normalized"),
        CheckConstraint("char_length(btrim(full_name)) > 0", name="full_name_not_blank"),
        CheckConstraint("token_version >= 0", name="token_version_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH), unique=True)
    full_name: Mapped[str] = mapped_column(String(FULL_NAME_MAX_LENGTH))
    # Argon2id hash only. Never add this field to a response schema.
    password_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[UserStatus] = mapped_column(
        str_enum(UserStatus, "user_status"),
        default=UserStatus.ACTIVE,
        server_default=UserStatus.ACTIVE.value,
    )
    # Incremented to invalidate every access token issued before the change.
    token_version: Mapped[int] = mapped_column(default=0, server_default="0")
    last_login_at: Mapped[datetime | None]
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    # lazy="raise" makes an unloaded relationship fail loudly instead of issuing implicit
    # I/O, which async sessions cannot do. Load roles explicitly with selectinload().
    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="raise", order_by=Role.code)

    @validates("email")
    def _normalize_email(self, _: str, email: str) -> str:
        return email.strip().lower()

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE

    @property
    def role_codes(self) -> list[str]:
        return [role.code for role in self.roles]
