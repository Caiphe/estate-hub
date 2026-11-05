import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.events import AuditEventCode
from app.audit.service import record_audit_event
from app.auth.permissions import Permission
from app.auth.policy import Actor, require_permissions
from app.catalog.errors import (
    ArchivedRecordError,
    CatalogNotFoundError,
    CatalogValidationError,
    DuplicateReferenceError,
    InvalidRelationshipError,
    StaleVersionError,
)
from app.catalog.limits import MAX_ACTIVE_UNITS_PER_PROPERTY, ensure_below
from app.catalog.models import Amenity
from app.catalog.repository import ReferenceRepository
from app.core.pagination import MAX_PAGE_SIZE
from app.core.security.access_tokens import utc_now
from app.properties.models import Property, Unit
from app.properties.repository import PropertyRepository, UnitRepository
from app.properties.rules import (
    ensure_amenities_assignable,
    ensure_mode_allows_units,
    ensure_unit_subtype_assignable,
)
from app.properties.schemas import AREA_UNIT_REQUIRED, UnitCreate, UnitUpdate

ENTITY_TYPE = "unit"
DUPLICATE_IDENTIFIER = "Another active unit of this property uses this identifier."
UNKNOWN_SUBTYPE = "The subtype does not exist."
UNKNOWN_AMENITY = "One or more amenities do not exist."


class UnitService:
    """Units of a property.

    Every change locks the parent property row first, so identifier uniqueness and the
    management-mode rule cannot be raced (the partial unique index is the final guard).
    Units never move between properties. Audit events hold the property ID, changed
    field names, and version: never notes or descriptions.
    """

    def __init__(self, db: AsyncSession, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._db = db
        self._properties = PropertyRepository(db)
        self._units = UnitRepository(db)
        self._reference = ReferenceRepository(db)
        self._clock = clock

    # --- Reads ---------------------------------------------------------------------------

    async def list_units(
        self,
        actor: Actor,
        property_id: uuid.UUID,
        *,
        include_archived: bool = False,
        limit: int = MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> list[Unit]:
        require_permissions(actor, Permission.PROPERTIES_READ)
        await self._property(property_id)
        return await self._units.list_for_property(
            property_id, include_archived=include_archived, limit=limit, offset=offset
        )

    async def count_units(
        self, actor: Actor, property_id: uuid.UUID, *, include_archived: bool = False
    ) -> int:
        require_permissions(actor, Permission.PROPERTIES_READ)
        await self._property(property_id)
        return await self._units.count_for_property(property_id, include_archived=include_archived)

    async def get_unit(self, actor: Actor, property_id: uuid.UUID, unit_id: uuid.UUID) -> Unit:
        require_permissions(actor, Permission.PROPERTIES_READ)
        return await self._unit(property_id, unit_id)

    # --- Mutations -----------------------------------------------------------------------

    async def create_unit(
        self,
        actor: Actor,
        property_id: uuid.UUID,
        data: UnitCreate,
        *,
        request_id: str | None = None,
    ) -> Unit:
        require_permissions(actor, Permission.PROPERTY_UNITS_MANAGE)

        async def work() -> Unit:
            parent = await self._changeable_property(property_id)
            ensure_mode_allows_units(parent.management_mode)
            await self._ensure_room(property_id)
            if await self._units.identifier_taken(property_id, data.identifier):
                raise DuplicateReferenceError({"identifier": [DUPLICATE_IDENTIFIER]})
            if data.property_subtype_id is not None:
                await self._check_subtype(parent, data.property_subtype_id)
            amenities = await self._amenities(data.amenity_ids)
            unit = Unit(
                id=uuid.uuid4(),
                property_id=property_id,
                **data.model_dump(exclude={"amenity_ids"}, exclude_none=True),
                created_by_id=actor.user_id,
                updated_by_id=actor.user_id,
            )
            unit.amenities = amenities
            self._db.add(unit)
            await self._flush()
            self._audit(
                AuditEventCode.UNIT_CREATED,
                actor,
                unit,
                request_id,
                {"property_id": str(property_id)},
            )
            return await self._unit(property_id, unit.id)

        return await self._unit_of_work(work)

    async def update_unit(
        self,
        actor: Actor,
        property_id: uuid.UUID,
        unit_id: uuid.UUID,
        data: UnitUpdate,
        *,
        request_id: str | None = None,
    ) -> Unit:
        require_permissions(actor, Permission.PROPERTY_UNITS_MANAGE)

        async def work() -> Unit:
            parent = await self._changeable_property(property_id)
            unit = await self._unit(property_id, unit_id)
            if unit.is_archived:
                raise ArchivedRecordError()
            if unit.version != data.version:
                raise StaleVersionError()
            requested = data.changes()
            requested.pop("amenity_ids", None)
            amenity_ids = data.amenity_ids
            changes = {
                name: value for name, value in requested.items() if getattr(unit, name) != value
            }
            if "identifier" in changes and await self._units.identifier_taken(
                property_id, str(changes["identifier"]), excluding=unit.id
            ):
                raise DuplicateReferenceError({"identifier": [DUPLICATE_IDENTIFIER]})
            if "property_subtype_id" in changes and data.property_subtype_id is not None:
                await self._check_subtype(parent, data.property_subtype_id)
            new_amenities: list[Amenity] | None = None
            if amenity_ids is not None and set(amenity_ids) != {a.id for a in unit.amenities}:
                current = {a.id for a in unit.amenities}
                new_amenities = await self._amenities(amenity_ids, current_ids=current)
                changes["amenity_ids"] = amenity_ids
            if not changes:
                return unit
            for name, value in changes.items():
                if name != "amenity_ids":
                    setattr(unit, name, value)
            if new_amenities is not None:
                unit.amenities = new_amenities
            if (unit.floor_area is None) != (unit.area_unit is None):
                raise CatalogValidationError({"area_unit": [AREA_UNIT_REQUIRED]})
            unit.updated_by_id = actor.user_id
            # Always write the row, so the version also moves when only the amenity links
            # changed (updated_by_id may already hold this actor).
            unit.updated_at = func.now()
            await self._flush()
            self._audit(
                AuditEventCode.UNIT_UPDATED,
                actor,
                unit,
                request_id,
                {
                    "property_id": str(property_id),
                    "changed_fields": sorted(changes),
                    "version": unit.version,
                },
            )
            return await self._unit(property_id, unit.id)

        return await self._unit_of_work(work)

    async def archive_unit(
        self,
        actor: Actor,
        property_id: uuid.UUID,
        unit_id: uuid.UUID,
        *,
        request_id: str | None = None,
    ) -> Unit:
        """Archive a unit, keeping it as history. Idempotent.

        Listings, leases, and bookings (later prompts) add their dependency checks here
        before the unit is archived.
        """
        require_permissions(actor, Permission.PROPERTY_UNITS_MANAGE)

        async def work() -> Unit:
            await self._changeable_property(property_id)
            unit = await self._unit(property_id, unit_id)
            if unit.is_archived:
                return unit
            unit.archived_at = self._clock()
            unit.archived_by_id = actor.user_id
            unit.updated_by_id = actor.user_id
            await self._flush()
            self._audit(
                AuditEventCode.UNIT_ARCHIVED,
                actor,
                unit,
                request_id,
                {"property_id": str(property_id), "version": unit.version},
            )
            return await self._unit(property_id, unit.id)

        return await self._unit_of_work(work)

    async def restore_unit(
        self,
        actor: Actor,
        property_id: uuid.UUID,
        unit_id: uuid.UUID,
        *,
        request_id: str | None = None,
    ) -> Unit:
        """Restore an archived unit if its property still accepts units and no active
        unit has taken its identifier meanwhile. Idempotent."""
        require_permissions(actor, Permission.PROPERTY_UNITS_MANAGE)

        async def work() -> Unit:
            parent = await self._changeable_property(property_id)
            unit = await self._unit(property_id, unit_id)
            if not unit.is_archived:
                return unit
            ensure_mode_allows_units(parent.management_mode)
            await self._ensure_room(property_id)
            if await self._units.identifier_taken(property_id, unit.identifier):
                raise DuplicateReferenceError({"identifier": [DUPLICATE_IDENTIFIER]})
            unit.archived_at = None
            unit.archived_by_id = None
            unit.updated_by_id = actor.user_id
            await self._flush()
            self._audit(
                AuditEventCode.UNIT_RESTORED,
                actor,
                unit,
                request_id,
                {"property_id": str(property_id), "version": unit.version},
            )
            return await self._unit(property_id, unit.id)

        return await self._unit_of_work(work)

    # --- Helpers -------------------------------------------------------------------------

    async def _unit_of_work[T](self, work: Callable[[], Awaitable[T]]) -> T:
        try:
            result = await work()
            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            raise
        return result

    async def _property(self, property_id: uuid.UUID, *, for_update: bool = False) -> Property:
        found = await self._properties.get(property_id, for_update=for_update)
        if found is None:
            raise CatalogNotFoundError()
        return found

    async def _changeable_property(self, property_id: uuid.UUID) -> Property:
        found = await self._property(property_id, for_update=True)
        if found.is_archived:
            raise ArchivedRecordError()
        return found

    async def _ensure_room(self, property_id: uuid.UUID) -> None:
        """Runs under the property lock, so concurrent creates cannot pass the cap."""
        ensure_below(
            await self._properties.count_active_units(property_id),
            MAX_ACTIVE_UNITS_PER_PROPERTY,
            "units",
        )

    async def _unit(self, property_id: uuid.UUID, unit_id: uuid.UUID) -> Unit:
        unit = await self._units.get(property_id, unit_id)
        if unit is None:
            raise CatalogNotFoundError()
        return unit

    async def _check_subtype(self, parent: Property, subtype_id: uuid.UUID) -> None:
        subtype = await self._reference.subtype(subtype_id)
        property_type = await self._reference.property_type(parent.property_type_id)
        if subtype is None or property_type is None:
            raise InvalidRelationshipError({"property_subtype_id": [UNKNOWN_SUBTYPE]})
        ensure_unit_subtype_assignable(property_type, subtype)

    async def _amenities(
        self, amenity_ids: list[uuid.UUID], *, current_ids: set[uuid.UUID] | None = None
    ) -> list[Amenity]:
        amenities = await self._reference.amenities(amenity_ids)
        if len(amenities) != len(set(amenity_ids)):
            raise InvalidRelationshipError({"amenity_ids": [UNKNOWN_AMENITY]})
        ensure_amenities_assignable(amenities, current_ids=current_ids or set())
        return amenities

    async def _flush(self) -> None:
        try:
            await self._db.flush()
        except IntegrityError as exc:
            # The property lock prevents this; the unique index is the final guard.
            if "uq_units_current_identifier" in str(exc.orig):
                raise DuplicateReferenceError({"identifier": [DUPLICATE_IDENTIFIER]}) from None
            raise

    def _audit(
        self,
        code: AuditEventCode,
        actor: Actor,
        unit: Unit,
        request_id: str | None,
        metadata: dict[str, Any],
    ) -> None:
        record_audit_event(
            self._db,
            code,
            actor_id=actor.user_id,
            request_id=request_id,
            entity_type=ENTITY_TYPE,
            entity_id=unit.id,
            metadata=metadata,
        )
