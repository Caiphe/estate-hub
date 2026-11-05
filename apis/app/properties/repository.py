import uuid

from sqlalchemy import ColumnElement, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, with_loader_criteria

from app.catalog.text import escape_like
from app.contacts.models import Contact
from app.core.pagination import MAX_PAGE_SIZE
from app.media.models import MediaAsset
from app.properties.constants import PropertyStatus
from app.properties.models import Property, PropertyOwnership, Unit, property_amenities
from app.properties.schemas import PropertyListQuery, PropertySort

# Mutation decisions must see the current row, not attributes cached in the session.
_FRESH = {"populate_existing": True}


class PropertyRepository:
    """Property persistence. Never commits; the calling service owns the transaction."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(
        self, property_id: uuid.UUID, *, for_update: bool = False, with_amenities: bool = False
    ) -> Property | None:
        statement = select(Property).where(Property.id == property_id).execution_options(**_FRESH)
        if with_amenities:
            statement = statement.options(selectinload(Property.amenities))
        if for_update:
            # Serializes ownership and unit changes on the property (share totals,
            # duplicate links and identifiers, management-mode checks).
            statement = statement.with_for_update()
        return (await self._db.scalars(statement)).one_or_none()

    async def get_detail(self, property_id: uuid.UUID) -> Property | None:
        """The property with its classification, amenities, and every unit (each with its
        subtype and amenities). A fixed number of queries however many units there are:
        one per relationship level, never one per row."""
        statement = (
            select(Property)
            .where(Property.id == property_id)
            .options(
                selectinload(Property.property_type),
                selectinload(Property.property_subtype),
                selectinload(Property.amenities),
                selectinload(Property.units).selectinload(Unit.property_subtype),
                selectinload(Property.units).selectinload(Unit.amenities),
                # Archived units are history (paged under /units); the active ones are
                # capped by MAX_ACTIVE_UNITS_PER_PROPERTY.
                with_loader_criteria(Unit, Unit.archived_at.is_(None)),
            )
            .execution_options(**_FRESH)
        )
        return (await self._db.scalars(statement)).one_or_none()

    async def list_page(
        self, query: PropertyListQuery, *, search_owners: bool
    ) -> tuple[list[Property], int]:
        """One page of the directory and the total under identical filters.

        ``search_owners`` adds current owners' names to ``q``; pass it only when the
        caller may read ownership, so search results cannot reveal who owns what.
        """
        conditions = _filters(query, search_owners=search_owners)
        total = await self._db.scalar(select(func.count()).select_from(Property).where(*conditions))
        column, descending = _SORT_COLUMNS[query.sort]
        statement = (
            select(Property)
            .where(*conditions)
            .options(selectinload(Property.property_type), selectinload(Property.property_subtype))
            # The primary key breaks ties, so pages never overlap or skip rows.
            .order_by(column.desc() if descending else column.asc(), Property.id.asc())
            .limit(query.limit)
            .offset(query.offset)
        )
        return list(await self._db.scalars(statement)), int(total or 0)

    async def active_unit_counts(self, property_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not property_ids:
            return {}
        statement = (
            select(Unit.property_id, func.count())
            .where(Unit.property_id.in_(property_ids), Unit.archived_at.is_(None))
            .group_by(Unit.property_id)
        )
        return {row[0]: int(row[1]) for row in await self._db.execute(statement)}

    async def cover_media_ids(self, property_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
        if not property_ids:
            return {}
        statement = select(MediaAsset.property_id, MediaAsset.id).where(
            MediaAsset.property_id.in_(property_ids), MediaAsset.is_cover.is_(True)
        )
        return {row[0]: row[1] for row in await self._db.execute(statement) if row[0]}

    async def count_typed_units(self, property_id: uuid.UUID) -> int:
        """Active units that have a subtype (which must match the property's type)."""
        statement = select(func.count()).where(
            Unit.property_id == property_id,
            Unit.archived_at.is_(None),
            Unit.property_subtype_id.is_not(None),
        )
        return int(await self._db.scalar(statement) or 0)

    async def count_active_units(self, property_id: uuid.UUID) -> int:
        statement = select(func.count()).where(
            Unit.property_id == property_id, Unit.archived_at.is_(None)
        )
        return int(await self._db.scalar(statement) or 0)


class UnitRepository:
    """Unit persistence. Never commits; the calling service owns the transaction."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(self, property_id: uuid.UUID, unit_id: uuid.UUID) -> Unit | None:
        """A unit under another property is treated as missing."""
        statement = (
            select(Unit)
            .where(Unit.id == unit_id, Unit.property_id == property_id)
            .options(selectinload(Unit.property_subtype), selectinload(Unit.amenities))
            .execution_options(**_FRESH)
        )
        return (await self._db.scalars(statement)).one_or_none()

    async def list_for_property(
        self,
        property_id: uuid.UUID,
        *,
        include_archived: bool = False,
        limit: int = MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> list[Unit]:
        """Active units of an unarchived property, or every unit with ``include_archived``.

        Archiving a property hides its units here without changing them.
        """
        statement = (
            select(Unit)
            .where(*_unit_filters(property_id, include_archived))
            .options(selectinload(Unit.property_subtype), selectinload(Unit.amenities))
            .order_by(Unit.identifier_key, Unit.id)
            .limit(limit)
            .offset(offset)
            .execution_options(**_FRESH)
        )
        return list(await self._db.scalars(statement))

    async def count_for_property(
        self, property_id: uuid.UUID, *, include_archived: bool = False
    ) -> int:
        statement = (
            select(func.count())
            .select_from(Unit)
            .where(*_unit_filters(property_id, include_archived))
        )
        return int(await self._db.scalar(statement) or 0)

    async def identifier_taken(
        self, property_id: uuid.UUID, identifier: str, *, excluding: uuid.UUID | None = None
    ) -> bool:
        statement = select(Unit.id).where(
            Unit.property_id == property_id,
            Unit.identifier_key == func.lower(identifier),
            Unit.archived_at.is_(None),
        )
        if excluding is not None:
            statement = statement.where(Unit.id != excluding)
        return bool(await self._db.scalar(statement.exists().select()))


class OwnershipRepository:
    """Ownership persistence. Never commits; the calling service owns the transaction."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(
        self, property_id: uuid.UUID, ownership_id: uuid.UUID
    ) -> PropertyOwnership | None:
        """A link under another property is treated as missing."""
        statement = (
            select(PropertyOwnership)
            .where(
                PropertyOwnership.id == ownership_id,
                PropertyOwnership.property_id == property_id,
            )
            .options(selectinload(PropertyOwnership.contact))
            .execution_options(**_FRESH)
        )
        return (await self._db.scalars(statement)).one_or_none()

    async def list_for_property(
        self,
        property_id: uuid.UUID,
        *,
        include_ended: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[PropertyOwnership]:
        """Current links first. Without ``limit`` only current links may be read (the
        share and duplicate checks need all of them, and MAX_CURRENT_OWNERS_PER_PROPERTY
        bounds them); ended history is always paged."""
        if include_ended and limit is None:
            raise ValueError("Ended ownership history must be read with a limit.")
        statement = (
            select(PropertyOwnership)
            .where(PropertyOwnership.property_id == property_id)
            .options(selectinload(PropertyOwnership.contact))
            .order_by(
                PropertyOwnership.archived_at.asc().nulls_first(),
                PropertyOwnership.start_date.asc().nulls_first(),
                PropertyOwnership.created_at.asc(),
                PropertyOwnership.id.asc(),
            )
            .limit(limit)
            .offset(offset)
            .execution_options(**_FRESH)
        )
        if not include_ended:
            statement = statement.where(PropertyOwnership.archived_at.is_(None))
        return list(await self._db.scalars(statement))

    async def count_for_property(
        self, property_id: uuid.UUID, *, include_ended: bool = False
    ) -> int:
        statement = select(func.count()).where(PropertyOwnership.property_id == property_id)
        if not include_ended:
            statement = statement.where(PropertyOwnership.archived_at.is_(None))
        return int(await self._db.scalar(statement) or 0)


def _unit_filters(property_id: uuid.UUID, include_archived: bool) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [Unit.property_id == property_id]
    if not include_archived:
        conditions += [
            Unit.archived_at.is_(None),
            select(Property.id)
            .where(Property.id == Unit.property_id, Property.status != PropertyStatus.ARCHIVED)
            .exists(),
        ]
    return conditions


_SORT_COLUMNS = {
    PropertySort.CREATED_AT: (Property.created_at, False),
    PropertySort.CREATED_AT_DESC: (Property.created_at, True),
    PropertySort.UPDATED_AT: (Property.updated_at, False),
    PropertySort.UPDATED_AT_DESC: (Property.updated_at, True),
    PropertySort.REFERENCE: (Property.reference, False),
    PropertySort.REFERENCE_DESC: (Property.reference, True),
    PropertySort.NAME: (func.lower(Property.name), False),
    PropertySort.NAME_DESC: (func.lower(Property.name), True),
    PropertySort.LOCALITY: (func.lower(Property.locality), False),
    PropertySort.LOCALITY_DESC: (func.lower(Property.locality), True),
}


def _filters(query: PropertyListQuery, *, search_owners: bool) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if query.status:
        conditions.append(Property.status.in_(query.status))
    elif not query.include_archived:
        conditions.append(Property.status != PropertyStatus.ARCHIVED)
    if query.property_type_id:
        conditions.append(Property.property_type_id.in_(query.property_type_id))
    if query.property_subtype_id:
        conditions.append(Property.property_subtype_id.in_(query.property_subtype_id))
    if query.management_mode:
        conditions.append(Property.management_mode.in_(query.management_mode))
    for amenity_id in query.amenity_id:
        conditions.append(
            exists().where(
                property_amenities.c.property_id == Property.id,
                property_amenities.c.amenity_id == amenity_id,
            )
        )
    if query.locality is not None:
        conditions.append(func.lower(Property.locality) == func.lower(query.locality))
    if query.region is not None:
        conditions.append(func.lower(Property.region) == func.lower(query.region))
    if query.country_code is not None:
        conditions.append(Property.country_code == query.country_code)
    if query.q is not None:
        pattern = f"%{escape_like(query.q.strip())}%"
        matches: list[ColumnElement[bool]] = [
            column.ilike(pattern, escape="\\")
            for column in (Property.reference, Property.name, Property.locality, Property.region)
        ]
        if search_owners:
            matches.append(
                exists().where(
                    PropertyOwnership.property_id == Property.id,
                    PropertyOwnership.archived_at.is_(None),
                    Contact.id == PropertyOwnership.contact_id,
                    or_(
                        Contact.display_name.ilike(pattern, escape="\\"),
                        Contact.organization_name.ilike(pattern, escape="\\"),
                    ),
                )
            )
        conditions.append(or_(*matches))
    return conditions
