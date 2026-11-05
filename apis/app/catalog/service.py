"""Administrator management of property types, subtypes, and amenities.

Rows are never deleted: disable and reactivate replace deletion, so records already using
a row stay valid. Names are unique ignoring case (a pre-check gives a friendly error; the
unique constraint on ``name_key`` is the final guard). Reordering locks the rows being
ordered, so two concurrent reorders cannot interleave.

Audit events identify the record through ``entity_type``/``entity_id`` and add only the
parent type ID, changed field names, and ordered IDs, never names or descriptions.
"""

import uuid
from typing import Any, Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.events import AuditEventCode
from app.audit.service import record_audit_event
from app.auth.permissions import Permission
from app.auth.policy import Actor, require_permissions
from app.catalog.errors import (
    CatalogNotFoundError,
    DuplicateReferenceError,
    InvalidRelationshipError,
)
from app.catalog.limits import (
    MAX_AMENITIES,
    MAX_PROPERTY_TYPES,
    MAX_SUBTYPES_PER_TYPE,
    ensure_below,
)
from app.catalog.models import Amenity, PropertySubtype, PropertyType
from app.catalog.repository import ReferenceRepository
from app.catalog.schemas import (
    AmenityCreate,
    AmenityUpdate,
    ReferenceCreate,
    ReferenceOrder,
    ReferenceUpdate,
)
from app.catalog.transactions import run_in_transaction

RecordType = Literal["property_type", "property_subtype", "amenity"]
Record = PropertyType | PropertySubtype | Amenity
DUPLICATE_NAME = "Another record in this list already uses this name."
ORDER_MISMATCH = "Provide every record of this list exactly once."
ORDER_STEP = 10
_UNIQUE_NAME_CONSTRAINTS = (
    "uq_property_types_name_key",
    "uq_property_subtypes_property_type_id_name_key",
    "uq_amenities_name_key",
)


def _record_type(record: Record) -> RecordType:
    if isinstance(record, PropertyType):
        return "property_type"
    if isinstance(record, PropertySubtype):
        return "property_subtype"
    return "amenity"


def _parent_metadata(record: Record) -> dict[str, Any]:
    if isinstance(record, PropertySubtype):
        return {"property_type_id": str(record.property_type_id)}
    return {}


class ReferenceDataService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._reference = ReferenceRepository(db)

    # --- Reads ---------------------------------------------------------------------------

    async def list_property_types(
        self, actor: Actor, *, include_inactive: bool = False
    ) -> list[PropertyType]:
        """Active types with their active subtypes, in display order: what property
        forms offer. ``include_inactive`` adds disabled records for administrators."""
        require_permissions(actor, Permission.PROPERTIES_READ)
        if include_inactive:
            require_permissions(actor, Permission.REFERENCE_DATA_MANAGE)
        return await self._reference.property_types(active_only=not include_inactive)

    async def get_property_type(self, actor: Actor, property_type_id: uuid.UUID) -> PropertyType:
        """Any reader may open a type, disabled or not, with every subtype: existing
        properties may still use them. ``is_active`` marks what can be newly chosen."""
        require_permissions(actor, Permission.PROPERTIES_READ)
        row = await self._reference.property_type_detail(property_type_id)
        if row is None:
            raise CatalogNotFoundError()
        return row

    async def get_subtype(
        self, actor: Actor, property_type_id: uuid.UUID, subtype_id: uuid.UUID
    ) -> PropertySubtype:
        require_permissions(actor, Permission.PROPERTIES_READ)
        return await self._subtype(property_type_id, subtype_id, for_update=False)

    async def list_amenities(
        self, actor: Actor, *, include_inactive: bool = False
    ) -> list[Amenity]:
        require_permissions(actor, Permission.PROPERTIES_READ)
        if include_inactive:
            require_permissions(actor, Permission.REFERENCE_DATA_MANAGE)
        return await self._reference.all_amenities(active_only=not include_inactive)

    async def get_amenity(self, actor: Actor, amenity_id: uuid.UUID) -> Amenity:
        require_permissions(actor, Permission.PROPERTIES_READ)
        return await self._amenity(amenity_id, for_update=False)

    # --- Creation ------------------------------------------------------------------------

    async def create_property_type(
        self, actor: Actor, data: ReferenceCreate, *, request_id: str | None = None
    ) -> PropertyType:
        require_permissions(actor, Permission.REFERENCE_DATA_MANAGE)

        async def work() -> PropertyType:
            await self._reference.lock_creation("property_types")
            ensure_below(await self._reference.count(PropertyType), MAX_PROPERTY_TYPES, "name")
            await self._ensure_name_free(PropertyType, data.name)
            row = PropertyType(id=uuid.uuid4(), **data.model_dump())
            return await self._insert(actor, row, request_id)

        return await run_in_transaction(self._db, work)

    async def create_subtype(
        self,
        actor: Actor,
        property_type_id: uuid.UUID,
        data: ReferenceCreate,
        *,
        request_id: str | None = None,
    ) -> PropertySubtype:
        """A disabled type may receive subtypes; they stay unselectable until the type is
        reactivated."""
        require_permissions(actor, Permission.REFERENCE_DATA_MANAGE)

        async def work() -> PropertySubtype:
            if await self._reference.property_type(property_type_id, for_update=True) is None:
                raise CatalogNotFoundError()
            ensure_below(
                await self._reference.count(PropertySubtype, property_type_id=property_type_id),
                MAX_SUBTYPES_PER_TYPE,
                "name",
            )
            await self._ensure_name_free(
                PropertySubtype, data.name, property_type_id=property_type_id
            )
            row = PropertySubtype(
                id=uuid.uuid4(), property_type_id=property_type_id, **data.model_dump()
            )
            return await self._insert(actor, row, request_id)

        return await run_in_transaction(self._db, work)

    async def create_amenity(
        self, actor: Actor, data: AmenityCreate, *, request_id: str | None = None
    ) -> Amenity:
        require_permissions(actor, Permission.REFERENCE_DATA_MANAGE)

        async def work() -> Amenity:
            await self._reference.lock_creation("amenities")
            ensure_below(await self._reference.count(Amenity), MAX_AMENITIES, "name")
            await self._ensure_name_free(Amenity, data.name)
            row = Amenity(id=uuid.uuid4(), **data.model_dump())
            return await self._insert(actor, row, request_id)

        return await run_in_transaction(self._db, work)

    # --- Updates -------------------------------------------------------------------------

    async def update_property_type(
        self,
        actor: Actor,
        property_type_id: uuid.UUID,
        data: ReferenceUpdate,
        *,
        request_id: str | None = None,
    ) -> PropertyType:
        require_permissions(actor, Permission.REFERENCE_DATA_MANAGE)

        async def work() -> PropertyType:
            row = await self._type(property_type_id, for_update=True)
            return await self._update(actor, row, data, request_id)

        return await run_in_transaction(self._db, work)

    async def update_subtype(
        self,
        actor: Actor,
        property_type_id: uuid.UUID,
        subtype_id: uuid.UUID,
        data: ReferenceUpdate,
        *,
        request_id: str | None = None,
    ) -> PropertySubtype:
        require_permissions(actor, Permission.REFERENCE_DATA_MANAGE)

        async def work() -> PropertySubtype:
            row = await self._subtype(property_type_id, subtype_id, for_update=True)
            return await self._update(actor, row, data, request_id)

        return await run_in_transaction(self._db, work)

    async def update_amenity(
        self,
        actor: Actor,
        amenity_id: uuid.UUID,
        data: AmenityUpdate,
        *,
        request_id: str | None = None,
    ) -> Amenity:
        require_permissions(actor, Permission.REFERENCE_DATA_MANAGE)

        async def work() -> Amenity:
            row = await self._amenity(amenity_id, for_update=True)
            return await self._update(actor, row, data, request_id)

        return await run_in_transaction(self._db, work)

    # --- Activity ------------------------------------------------------------------------

    async def set_property_type_active(
        self,
        actor: Actor,
        property_type_id: uuid.UUID,
        active: bool,
        *,
        request_id: str | None = None,
    ) -> PropertyType:
        """Disabling a type leaves its subtypes' own flags alone; while the type is
        disabled none of them can be newly assigned."""
        require_permissions(actor, Permission.REFERENCE_DATA_MANAGE)

        async def work() -> PropertyType:
            row = await self._type(property_type_id, for_update=True)
            return await self._set_active(actor, row, active, request_id)

        return await run_in_transaction(self._db, work)

    async def set_subtype_active(
        self,
        actor: Actor,
        property_type_id: uuid.UUID,
        subtype_id: uuid.UUID,
        active: bool,
        *,
        request_id: str | None = None,
    ) -> PropertySubtype:
        require_permissions(actor, Permission.REFERENCE_DATA_MANAGE)

        async def work() -> PropertySubtype:
            row = await self._subtype(property_type_id, subtype_id, for_update=True)
            return await self._set_active(actor, row, active, request_id)

        return await run_in_transaction(self._db, work)

    async def set_amenity_active(
        self, actor: Actor, amenity_id: uuid.UUID, active: bool, *, request_id: str | None = None
    ) -> Amenity:
        require_permissions(actor, Permission.REFERENCE_DATA_MANAGE)

        async def work() -> Amenity:
            row = await self._amenity(amenity_id, for_update=True)
            return await self._set_active(actor, row, active, request_id)

        return await run_in_transaction(self._db, work)

    # --- Ordering ------------------------------------------------------------------------

    async def reorder_property_types(
        self, actor: Actor, data: ReferenceOrder, *, request_id: str | None = None
    ) -> list[PropertyType]:
        require_permissions(actor, Permission.REFERENCE_DATA_MANAGE)

        async def work() -> list[PropertyType]:
            rows = await self._reference.all_types(for_update=True)
            await self._reorder(actor, "property_type", rows, data, None, request_id)
            return await self._reference.all_types()

        return await run_in_transaction(self._db, work)

    async def reorder_subtypes(
        self,
        actor: Actor,
        property_type_id: uuid.UUID,
        data: ReferenceOrder,
        *,
        request_id: str | None = None,
    ) -> list[PropertySubtype]:
        require_permissions(actor, Permission.REFERENCE_DATA_MANAGE)

        async def work() -> list[PropertySubtype]:
            await self._type(property_type_id, for_update=True)
            rows = await self._reference.subtypes_of(property_type_id, for_update=True)
            await self._reorder(actor, "property_subtype", rows, data, property_type_id, request_id)
            return await self._reference.subtypes_of(property_type_id)

        return await run_in_transaction(self._db, work)

    async def reorder_amenities(
        self, actor: Actor, data: ReferenceOrder, *, request_id: str | None = None
    ) -> list[Amenity]:
        require_permissions(actor, Permission.REFERENCE_DATA_MANAGE)

        async def work() -> list[Amenity]:
            rows = await self._reference.all_amenities(for_update=True)
            await self._reorder(actor, "amenity", rows, data, None, request_id)
            return await self._reference.all_amenities()

        return await run_in_transaction(self._db, work)

    # --- Helpers -------------------------------------------------------------------------

    async def _type(self, property_type_id: uuid.UUID, *, for_update: bool) -> PropertyType:
        row = await self._reference.property_type(property_type_id, for_update=for_update)
        if row is None:
            raise CatalogNotFoundError()
        return row

    async def _subtype(
        self, property_type_id: uuid.UUID, subtype_id: uuid.UUID, *, for_update: bool
    ) -> PropertySubtype:
        """A subtype requested under another type is treated as missing."""
        row = await self._reference.subtype(
            subtype_id, property_type_id=property_type_id, for_update=for_update
        )
        if row is None:
            raise CatalogNotFoundError()
        return row

    async def _amenity(self, amenity_id: uuid.UUID, *, for_update: bool) -> Amenity:
        row = await self._reference.amenity(amenity_id, for_update=for_update)
        if row is None:
            raise CatalogNotFoundError()
        return row

    async def _ensure_name_free(
        self,
        model: type[Record],
        name: str,
        *,
        property_type_id: uuid.UUID | None = None,
        excluding: uuid.UUID | None = None,
    ) -> None:
        if await self._reference.name_taken(
            model, name, property_type_id=property_type_id, excluding=excluding
        ):
            raise DuplicateReferenceError({"name": [DUPLICATE_NAME]})

    async def _insert[R: (PropertyType, PropertySubtype, Amenity)](
        self, actor: Actor, row: R, request_id: str | None
    ) -> R:
        row.created_by_id = actor.user_id
        row.updated_by_id = actor.user_id
        self._db.add(row)
        await self._flush()
        self._audit(AuditEventCode.REFERENCE_DATA_CREATED, actor, row, request_id, {})
        return row

    async def _update[R: (PropertyType, PropertySubtype, Amenity)](
        self,
        actor: Actor,
        row: R,
        data: ReferenceUpdate,
        request_id: str | None,
    ) -> R:
        changes = {
            name: value for name, value in data.changes().items() if getattr(row, name) != value
        }
        if not changes:
            return row
        if "name" in changes:
            await self._ensure_name_free(
                type(row),
                str(changes["name"]),
                property_type_id=getattr(row, "property_type_id", None),
                excluding=row.id,
            )
        for name, value in changes.items():
            setattr(row, name, value)
        row.updated_by_id = actor.user_id
        await self._flush()
        self._audit(
            AuditEventCode.REFERENCE_DATA_UPDATED,
            actor,
            row,
            request_id,
            {"changed_fields": sorted(changes)},
        )
        return row

    async def _set_active[R: (PropertyType, PropertySubtype, Amenity)](
        self, actor: Actor, row: R, active: bool, request_id: str | None
    ) -> R:
        if row.is_active == active:
            return row
        row.is_active = active
        row.updated_by_id = actor.user_id
        await self._flush()
        code = (
            AuditEventCode.REFERENCE_DATA_REACTIVATED
            if active
            else AuditEventCode.REFERENCE_DATA_DISABLED
        )
        self._audit(code, actor, row, request_id, {})
        return row

    async def _reorder(
        self,
        actor: Actor,
        record_type: RecordType,
        rows: list[PropertyType] | list[PropertySubtype] | list[Amenity],
        data: ReferenceOrder,
        property_type_id: uuid.UUID | None,
        request_id: str | None,
    ) -> None:
        """Positions become 0, 10, 20, … so one record can later be slotted between two."""
        by_id: dict[uuid.UUID, Record] = {row.id: row for row in rows}
        if set(data.ids) != set(by_id):
            raise InvalidRelationshipError({"ids": [ORDER_MISMATCH]})
        for position, record_id in enumerate(data.ids):
            by_id[record_id].display_order = position * ORDER_STEP
            by_id[record_id].updated_by_id = actor.user_id
        await self._flush()
        metadata: dict[str, Any] = {
            "record_type": record_type,
            "ids": [str(record_id) for record_id in data.ids],
        }
        if property_type_id is not None:
            metadata["property_type_id"] = str(property_type_id)
        record_audit_event(
            self._db,
            AuditEventCode.REFERENCE_DATA_REORDERED,
            actor_id=actor.user_id,
            request_id=request_id,
            entity_type=record_type,
            entity_id=property_type_id or data.ids[0],
            metadata=metadata,
        )

    async def _flush(self) -> None:
        try:
            await self._db.flush()
        except IntegrityError as exc:
            # A concurrent request took the name between the pre-check and the write.
            if any(name in str(exc.orig) for name in _UNIQUE_NAME_CONSTRAINTS):
                raise DuplicateReferenceError({"name": [DUPLICATE_NAME]}) from None
            raise

    def _audit(
        self,
        code: AuditEventCode,
        actor: Actor,
        row: Record,
        request_id: str | None,
        metadata: dict[str, Any],
    ) -> None:
        record_audit_event(
            self._db,
            code,
            actor_id=actor.user_id,
            request_id=request_id,
            entity_type=_record_type(row),
            entity_id=row.id,
            metadata=_parent_metadata(row) | metadata,
        )
