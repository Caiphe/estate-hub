from collections.abc import AsyncIterator
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Enum, MetaData, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import settings

# Deterministic constraint names keep Alembic migrations and downgrades predictable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {datetime: DateTime(timezone=True)}


class TimestampMixin:
    # Fetch server-generated values with RETURNING. Otherwise they are expired after a
    # flush and a later read would need implicit I/O, which async sessions refuse.
    __mapper_args__ = {"eager_defaults": True}

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


def str_enum(enum_class: type[StrEnum], name: str) -> Enum:
    """Store a StrEnum as its values in a VARCHAR guarded by a named check constraint.

    A check constraint is simpler to evolve in migrations than a native PostgreSQL enum.
    """

    def values(members: Any) -> list[str]:
        return [member.value for member in members]

    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=values,
        validate_strings=True,
    )


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    # Bound values include password hashes and token hashes; keep them out of SQL logs
    # and exception messages.
    hide_parameters=True,
    pool_pre_ping=True,
)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
