import uuid
from collections.abc import Collection

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, with_loader_criteria

from app.catalog.models import Amenity, PropertySubtype, PropertyType

_FRESH = {"populate_existing": True}
ReferenceModel = type[PropertyType] | type[PropertySubtype] | type[Amenity]


def _ordered[T: (PropertyType, PropertySubtype, Amenity)](
    statement: Select[tuple[T]], model: type[T]
) -> Select[tuple[T]]:
    return statement.order_by(model.display_order, model.name_key, model.id)


# Arbitrary constants for the transaction-scoped advisory locks that serialize creation
# of top-level reference records, so concurrent creates cannot pass their caps.
_CREATE_LOCKS: dict[str, int] = {"property_types": 7_301_202_621, "amenities": 7_301_202_622}


class ReferenceRepository:
    """Reference-data persistence. Never commits; the calling service owns the transaction."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def lock_creation(self, table: str) -> None:
        await self._db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": _CREATE_LOCKS[table]}
        )

    async def count(
        self, model: ReferenceModel, *, property_type_id: uuid.UUID | None = None
    ) -> int:
        statement = select(func.count()).select_from(model)
        if model is PropertySubtype:
            statement = statement.where(PropertySubtype.property_type_id == property_type_id)
        return int(await self._db.scalar(statement) or 0)

    async def property_type(
        self, property_type_id: uuid.UUID, *, for_update: bool = False
    ) -> PropertyType | None:
        statement = select(PropertyType).where(PropertyType.id == property_type_id)
        if for_update:
            statement = statement.with_for_update()
        return (await self._db.scalars(statement.execution_options(**_FRESH))).one_or_none()

    async def subtype(
        self,
        subtype_id: uuid.UUID,
        *,
        property_type_id: uuid.UUID | None = None,
        for_update: bool = False,
    ) -> PropertySubtype | None:
        """With ``property_type_id``, a subtype of another type is treated as missing."""
        statement = select(PropertySubtype).where(PropertySubtype.id == subtype_id)
        if property_type_id is not None:
            statement = statement.where(PropertySubtype.property_type_id == property_type_id)
        if for_update:
            statement = statement.with_for_update()
        return (await self._db.scalars(statement.execution_options(**_FRESH))).one_or_none()

    async def amenity(self, amenity_id: uuid.UUID, *, for_update: bool = False) -> Amenity | None:
        statement = select(Amenity).where(Amenity.id == amenity_id)
        if for_update:
            statement = statement.with_for_update()
        return (await self._db.scalars(statement.execution_options(**_FRESH))).one_or_none()

    async def amenities(self, amenity_ids: Collection[uuid.UUID]) -> list[Amenity]:
        if not amenity_ids:
            return []
        statement = _ordered(select(Amenity).where(Amenity.id.in_(amenity_ids)), Amenity)
        return list(await self._db.scalars(statement))

    async def property_types(self, *, active_only: bool) -> list[PropertyType]:
        """Types with their subtypes in display order. ``active_only`` keeps active types
        and their active subtypes, for property forms."""
        statement = _ordered(select(PropertyType), PropertyType).options(
            selectinload(PropertyType.subtypes)
        )
        if active_only:
            statement = statement.where(PropertyType.is_active.is_(True)).options(
                with_loader_criteria(PropertySubtype, PropertySubtype.is_active.is_(True))
            )
        return list(await self._db.scalars(statement.execution_options(**_FRESH)))

    async def property_type_detail(self, property_type_id: uuid.UUID) -> PropertyType | None:
        statement = (
            select(PropertyType)
            .where(PropertyType.id == property_type_id)
            .options(selectinload(PropertyType.subtypes))
            .execution_options(**_FRESH)
        )
        return (await self._db.scalars(statement)).one_or_none()

    async def subtypes_of(
        self, property_type_id: uuid.UUID, *, for_update: bool = False
    ) -> list[PropertySubtype]:
        statement = _ordered(
            select(PropertySubtype).where(PropertySubtype.property_type_id == property_type_id),
            PropertySubtype,
        )
        if for_update:
            statement = statement.with_for_update()
        return list(await self._db.scalars(statement.execution_options(**_FRESH)))

    async def all_amenities(
        self, *, active_only: bool = False, for_update: bool = False
    ) -> list[Amenity]:
        statement = _ordered(select(Amenity), Amenity)
        if active_only:
            statement = statement.where(Amenity.is_active.is_(True))
        if for_update:
            statement = statement.with_for_update()
        return list(await self._db.scalars(statement.execution_options(**_FRESH)))

    async def all_types(self, *, for_update: bool = False) -> list[PropertyType]:
        statement = _ordered(select(PropertyType), PropertyType)
        if for_update:
            statement = statement.with_for_update()
        return list(await self._db.scalars(statement.execution_options(**_FRESH)))

    async def name_taken(
        self,
        model: ReferenceModel,
        name: str,
        *,
        property_type_id: uuid.UUID | None = None,
        excluding: uuid.UUID | None = None,
    ) -> bool:
        statement = select(model.id).where(model.name_key == func.lower(name))
        if model is PropertySubtype:
            statement = statement.where(PropertySubtype.property_type_id == property_type_id)
        if excluding is not None:
            statement = statement.where(model.id != excluding)
        return bool(await self._db.scalar(statement.exists().select()))
