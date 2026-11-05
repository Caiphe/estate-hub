import re
import uuid
from datetime import date
from typing import Literal

from sqlalchemy import ColumnElement, Select, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.text import escape_like
from app.contacts.constants import ContactStatus
from app.contacts.models import Contact
from app.contacts.schemas import ContactListQuery, ContactSort
from app.properties.models import PropertyOwnership

# Mutation decisions must see the current row, not attributes cached in the session.
_FRESH = {"populate_existing": True}
Lock = Literal["update", "share"] | None
_NON_DIGITS = re.compile(r"\D")


class ContactRepository:
    """Contact persistence. Never commits; the calling service owns the transaction."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(self, contact_id: uuid.UUID, *, lock: Lock = None) -> Contact | None:
        statement = select(Contact).where(Contact.id == contact_id).execution_options(**_FRESH)
        if lock == "update":
            statement = statement.with_for_update()
        elif lock == "share":
            # Blocks a concurrent archive (FOR UPDATE) without blocking other readers.
            statement = statement.with_for_update(read=True)
        return (await self._db.scalars(statement)).one_or_none()

    async def list(self, query: ContactListQuery) -> tuple[list[Contact], int]:
        conditions = _filters(query)
        total = await self._db.scalar(select(func.count()).select_from(Contact).where(*conditions))
        column, descending = _SORT_COLUMNS[query.sort]
        statement: Select[tuple[Contact]] = (
            select(Contact)
            .where(*conditions)
            # The primary key breaks ties so pages never overlap or skip rows.
            .order_by(column.desc() if descending else column.asc(), Contact.id.asc())
            .limit(query.limit)
            .offset(query.offset)
        )
        return list(await self._db.scalars(statement)), int(total or 0)

    async def has_current_ownership(self, contact_id: uuid.UUID, today: date) -> bool:
        """An unended link whose real-world end date, if any, has not passed."""
        statement = select(
            exists().where(
                PropertyOwnership.contact_id == contact_id,
                PropertyOwnership.archived_at.is_(None),
                or_(PropertyOwnership.end_date.is_(None), PropertyOwnership.end_date >= today),
            )
        )
        return bool(await self._db.scalar(statement))


_SORT_COLUMNS = {
    ContactSort.DISPLAY_NAME: (func.lower(Contact.display_name), False),
    ContactSort.DISPLAY_NAME_DESC: (func.lower(Contact.display_name), True),
    ContactSort.CREATED_AT: (Contact.created_at, False),
    ContactSort.CREATED_AT_DESC: (Contact.created_at, True),
    ContactSort.UPDATED_AT: (Contact.updated_at, False),
    ContactSort.UPDATED_AT_DESC: (Contact.updated_at, True),
}


def _filters(query: ContactListQuery) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if not query.include_archived:
        conditions.append(Contact.status == ContactStatus.ACTIVE)
    if query.kind is not None:
        conditions.append(Contact.kind == query.kind)
    if query.q is not None:
        pattern = f"%{escape_like(query.q.strip())}%"
        matches: list[ColumnElement[bool]] = [
            Contact.display_name.ilike(pattern, escape="\\"),
            Contact.organization_name.ilike(pattern, escape="\\"),
            Contact.email.ilike(pattern, escape="\\"),
        ]
        # Numbers are stored without separators, so search them the same way.
        digits = _NON_DIGITS.sub("", query.q)
        if len(digits) >= 3:
            matches.append(Contact.telephone.contains(digits, autoescape=True))
            matches.append(Contact.alternative_telephone.contains(digits, autoescape=True))
        conditions.append(or_(*matches))
    return conditions
