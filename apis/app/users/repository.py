import uuid

from sqlalchemy import ColumnElement, Select, exists, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.users.constants import RoleCode, UserStatus
from app.users.models import Role, User, user_roles
from app.users.schemas import StaffListQuery, StaffSort

# Security decisions must see the current row, not attributes cached in the session.
_FRESH = {"populate_existing": True}


class UserRepository:
    """User persistence. Never commits; the calling service owns the transaction."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_email(self, email: str) -> User | None:
        """Look up by an already-normalized email, with roles loaded."""
        statement = (
            select(User)
            .where(User.email == email)
            .options(selectinload(User.roles))
            .execution_options(**_FRESH)
        )
        return (await self._db.scalars(statement)).one_or_none()

    async def get_by_id(self, user_id: uuid.UUID, *, for_update: bool = False) -> User | None:
        statement = (
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.roles))
            .execution_options(**_FRESH)
        )
        if for_update:
            statement = statement.with_for_update(of=User)
        return (await self._db.scalars(statement)).one_or_none()

    async def increment_token_version(self, user_id: uuid.UUID) -> int:
        """Invalidate every access token issued to the user so far."""
        statement = (
            update(User)
            .where(User.id == user_id)
            .values(token_version=User.token_version + 1)
            .returning(User.token_version)
        )
        return (await self._db.execute(statement)).scalar_one()

    async def email_taken(self, email: str, *, excluding: uuid.UUID | None = None) -> bool:
        condition = User.email == email
        if excluding is not None:
            condition = condition & (User.id != excluding)
        return bool(await self._db.scalar(select(exists().where(condition))))

    async def list_staff(self, query: StaffListQuery) -> tuple[list[User], int]:
        conditions = _filters(query)
        total = await self._db.scalar(select(func.count()).select_from(User).where(*conditions))
        column, descending = _SORT_COLUMNS[query.sort]
        statement: Select[tuple[User]] = (
            select(User)
            .where(*conditions)
            .options(selectinload(User.roles))
            # The primary key breaks ties so pages never overlap or skip rows.
            .order_by(column.desc() if descending else column.asc(), User.id.asc())
            .limit(query.limit)
            .offset(query.offset)
        )
        return list(await self._db.scalars(statement)), int(total or 0)

    async def roles_by_code(self, codes: list[str]) -> list[Role]:
        return list(await self._db.scalars(select(Role).where(Role.code.in_(codes))))

    async def lock_administrator_set(self) -> None:
        """Serialize every change that could reduce the number of active administrators.

        A transaction-scoped advisory lock is held until commit or rollback, so two
        concurrent requests cannot each see "another administrator remains".
        """
        await self._db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ADMIN_LOCK})

    async def count_active_administrators(self, *, excluding: uuid.UUID) -> int:
        statement = (
            select(func.count(func.distinct(User.id)))
            .join(user_roles, user_roles.c.user_id == User.id)
            .join(Role, Role.id == user_roles.c.role_id)
            .where(
                Role.code == RoleCode.ADMINISTRATOR.value,
                User.status == UserStatus.ACTIVE,
                User.id != excluding,
            )
        )
        return int(await self._db.scalar(statement) or 0)


# Arbitrary constant identifying the "administrator set" advisory lock.
_ADMIN_LOCK = 7_301_202_611

_SORT_COLUMNS = {
    StaffSort.FULL_NAME: (User.full_name, False),
    StaffSort.FULL_NAME_DESC: (User.full_name, True),
    StaffSort.EMAIL: (User.email, False),
    StaffSort.EMAIL_DESC: (User.email, True),
    StaffSort.CREATED_AT: (User.created_at, False),
    StaffSort.CREATED_AT_DESC: (User.created_at, True),
}


def _filters(query: StaffListQuery) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if query.status is not None:
        conditions.append(User.status == query.status)
    if query.role is not None:
        conditions.append(
            exists()
            .where(user_roles.c.user_id == User.id)
            .where(user_roles.c.role_id == Role.id)
            .where(Role.code == query.role.value)
        )
    if query.q is not None:
        # Escape LIKE wildcards so the search is literal.
        term = query.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{term}%"
        conditions.append(
            User.email.ilike(pattern, escape="\\") | User.full_name.ilike(pattern, escape="\\")
        )
    return conditions
