import uuid
from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import MAX_PAGE_SIZE
from app.media.models import Document, MediaAsset

_FRESH = {"populate_existing": True}


@dataclass(frozen=True, slots=True)
class Parent:
    """A property, or a unit of that property. The unit must belong to the property."""

    property_id: uuid.UUID
    unit_id: uuid.UUID | None = None

    @property
    def audit_metadata(self) -> dict[str, str]:
        if self.unit_id is not None:
            return {"property_id": str(self.property_id), "unit_id": str(self.unit_id)}
        return {"property_id": str(self.property_id)}


def _for_parent[T: (MediaAsset, Document)](model: type[T], parent: Parent) -> Select[tuple[T]]:
    if parent.unit_id is not None:
        return select(model).where(model.unit_id == parent.unit_id)
    return select(model).where(model.property_id == parent.property_id)


class MediaRepository:
    """Media persistence. Never commits; the calling service owns the transaction."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(self, parent: Parent, media_id: uuid.UUID) -> MediaAsset | None:
        """Media of another parent is treated as missing."""
        statement = _for_parent(MediaAsset, parent).where(MediaAsset.id == media_id)
        return (await self._db.scalars(statement.execution_options(**_FRESH))).one_or_none()

    async def list(
        self,
        parent: Parent,
        *,
        include_archived: bool = False,
        limit: int = MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> list[MediaAsset]:
        statement = _for_parent(MediaAsset, parent).order_by(
            MediaAsset.display_order, MediaAsset.created_at, MediaAsset.id
        )
        if not include_archived:
            statement = statement.where(MediaAsset.archived_at.is_(None))
        statement = statement.limit(limit).offset(offset).execution_options(**_FRESH)
        return list(await self._db.scalars(statement))

    async def count(self, parent: Parent, *, include_archived: bool = False) -> int:
        statement = _for_parent(MediaAsset, parent)
        if not include_archived:
            statement = statement.where(MediaAsset.archived_at.is_(None))
        return int(
            await self._db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )

    async def next_display_order(self, parent: Parent) -> int:
        statement = _for_parent(MediaAsset, parent).where(MediaAsset.archived_at.is_(None))
        highest = await self._db.scalar(select(func.max(statement.subquery().c.display_order)))
        return 0 if highest is None else int(highest) + 1

    async def cover(self, parent: Parent) -> MediaAsset | None:
        statement = _for_parent(MediaAsset, parent).where(MediaAsset.is_cover.is_(True))
        return (await self._db.scalars(statement.execution_options(**_FRESH))).one_or_none()


class DocumentRepository:
    """Document persistence. Never commits; the calling service owns the transaction."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(self, parent: Parent, document_id: uuid.UUID) -> Document | None:
        """A document of another parent is treated as missing."""
        statement = _for_parent(Document, parent).where(Document.id == document_id)
        return (await self._db.scalars(statement.execution_options(**_FRESH))).one_or_none()

    async def list(
        self,
        parent: Parent,
        *,
        include_archived: bool = False,
        limit: int = MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> list[Document]:
        statement = _for_parent(Document, parent).order_by(
            Document.created_at.desc(), Document.id.desc()
        )
        if not include_archived:
            statement = statement.where(Document.archived_at.is_(None))
        statement = statement.limit(limit).offset(offset).execution_options(**_FRESH)
        return list(await self._db.scalars(statement))

    async def count(self, parent: Parent, *, include_archived: bool = False) -> int:
        statement = _for_parent(Document, parent)
        if not include_archived:
            statement = statement.where(Document.archived_at.is_(None))
        return int(
            await self._db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )
