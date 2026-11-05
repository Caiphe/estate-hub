"""Property records: create, read, search, update, archive, and restore.

Transactions live here; repositories never commit. Every mutation locks the property row,
so it serializes with owner, unit, and file changes on the same property. Each successful
change writes its audit event in the same transaction; a failed change rolls back both.

Archive and restore keep every child record unchanged. While a property is archived its
units leave normal unit lists, and its owners, units, and files cannot be changed.
Listing, lease, and booking prompts will add their dependency checks to ``archive``.
"""

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.events import AuditEventCode
from app.audit.service import record_audit_event
from app.auth.permissions import Permission
from app.auth.policy import Actor, has_permissions, require_permissions
from app.catalog.errors import (
    ArchivedRecordError,
    CatalogConflictError,
    CatalogNotFoundError,
    CatalogValidationError,
    DependencyConflictError,
    InvalidRelationshipError,
    StaleVersionError,
)
from app.catalog.models import Amenity, PropertySubtype, PropertyType
from app.catalog.repository import ReferenceRepository
from app.catalog.transactions import run_in_transaction
from app.contacts.repository import ContactRepository
from app.core.security.access_tokens import utc_now
from app.properties.constants import PropertyStatus
from app.properties.models import Property, PropertyOwnership, Unit
from app.properties.ownership import SHARE_LIMIT, UNAVAILABLE_CONTACT
from app.properties.repository import OwnershipRepository, PropertyRepository
from app.properties.rules import (
    ensure_amenities_assignable,
    ensure_classification_assignable,
    ensure_mode_change_allowed,
    ensure_unit_subtype_assignable,
)
from app.properties.schemas import (
    PropertyCreate,
    PropertyDetail,
    PropertyListQuery,
    PropertySummary,
    PropertyUpdate,
    owners_view,
    property_detail_view,
    property_rule_errors,
    property_summary_view,
)
from app.properties.shares import MAX_TOTAL, ShareSpan, peak_known_share, share_summary

ENTITY_TYPE = "property"
# Archival keeps no previous status, so a restored property returns as inactive and
# staff reactivate it deliberately.
RESTORED_STATUS = PropertyStatus.INACTIVE
UNKNOWN_TYPE = "The property type does not exist."
UNKNOWN_SUBTYPE = "The subtype does not exist."
UNKNOWN_AMENITY = "One or more amenities do not exist."
UNITS_USE_TYPE = "Clear the subtype of every active unit before changing the property type."


@contextmanager
def _field_prefix(prefix: str) -> Iterator[None]:
    """Point a nested record's error fields at its place in the request (``units.2.x``)."""
    try:
        yield
    except InvalidRelationshipError as exc:
        fields = {f"{prefix}.{name}": messages for name, messages in (exc.fields or {}).items()}
        raise InvalidRelationshipError(fields) from None


class PropertyService:
    def __init__(self, db: AsyncSession, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._db = db
        self._properties = PropertyRepository(db)
        self._ownerships = OwnershipRepository(db)
        self._contacts = ContactRepository(db)
        self._reference = ReferenceRepository(db)
        self._clock = clock

    # --- Reads ---------------------------------------------------------------------------

    async def list_properties(
        self, actor: Actor, query: PropertyListQuery
    ) -> tuple[list[PropertySummary], int]:
        """Archived properties appear only with ``include_archived`` (or an archived status
        filter), which requires ``properties:archive``."""
        require_permissions(actor, Permission.PROPERTIES_READ)
        if query.include_archived:
            require_permissions(actor, Permission.PROPERTIES_ARCHIVE)
        rows, total = await self._properties.list_page(
            query, search_owners=has_permissions(actor, Permission.PROPERTY_OWNERSHIP_READ)
        )
        ids = [row.id for row in rows]
        unit_counts = await self._properties.active_unit_counts(ids)
        covers = await self._properties.cover_media_ids(ids)
        return [
            property_summary_view(
                row, unit_count=unit_counts.get(row.id, 0), cover_media_id=covers.get(row.id)
            )
            for row in rows
        ], total

    async def get_property(self, actor: Actor, property_id: uuid.UUID) -> PropertyDetail:
        """Any ``properties:read`` holder may open a property directly, archived or not,
        so history (audit events, documents) always resolves. Private sections follow
        the caller's permissions."""
        require_permissions(actor, Permission.PROPERTIES_READ)
        return await self._detail(actor, property_id)

    # --- Mutations -----------------------------------------------------------------------

    async def create_property(
        self, actor: Actor, data: PropertyCreate, *, request_id: str | None = None
    ) -> PropertyDetail:
        """Create the property and any initial amenities, owners, and units atomically.
        Initial owners and units also need their own manage permissions."""
        require_permissions(actor, Permission.PROPERTIES_CREATE)
        if data.owners:
            require_permissions(actor, Permission.PROPERTY_OWNERSHIP_MANAGE)
        if data.units:
            require_permissions(actor, Permission.PROPERTY_UNITS_MANAGE)

        async def work() -> PropertyDetail:
            property_type, subtype = await self._classification(
                data.property_type_id, data.property_subtype_id
            )
            ensure_classification_assignable(property_type, subtype)
            amenities = await self._amenities(data.amenity_ids, field="amenity_ids")
            ensure_amenities_assignable(amenities)
            row = Property(
                id=uuid.uuid4(),
                **data.model_dump(exclude={"amenity_ids", "owners", "units"}),
                created_by_id=actor.user_id,
                updated_by_id=actor.user_id,
            )
            row.amenities = amenities
            self._db.add(row)
            await self._db.flush()
            await self._add_initial_owners(actor, row, data, request_id)
            await self._add_initial_units(actor, row, property_type, data, request_id)
            self._audit(
                AuditEventCode.PROPERTY_CREATED,
                actor,
                row.id,
                request_id,
                {
                    "amenity_count": len(amenities),
                    "owner_count": len(data.owners),
                    "unit_count": len(data.units),
                },
            )
            await self._db.flush()
            return await self._detail(actor, row.id)

        return await run_in_transaction(self._db, work)

    async def update_property(
        self,
        actor: Actor,
        property_id: uuid.UUID,
        data: PropertyUpdate,
        *,
        request_id: str | None = None,
    ) -> PropertyDetail:
        require_permissions(actor, Permission.PROPERTIES_UPDATE)

        async def work() -> PropertyDetail:
            row = await self._locked(property_id, with_amenities=True)
            if row.is_archived:
                raise ArchivedRecordError()
            if row.version != data.version:
                raise StaleVersionError()
            requested = data.changes()
            requested.pop("amenity_ids", None)
            changes = {
                name: value for name, value in requested.items() if getattr(row, name) != value
            }
            await self._check_classification_change(row, data, changes)
            if "management_mode" in changes:
                ensure_mode_change_allowed(
                    data.management_mode or row.management_mode,
                    await self._properties.count_active_units(row.id),
                )
            new_amenities = await self._amenity_change(row, data.amenity_ids)
            if new_amenities is not None:
                changes["amenity_ids"] = data.amenity_ids
            if not changes:
                return await self._detail(actor, row.id)
            for name, value in changes.items():
                if name != "amenity_ids":
                    setattr(row, name, value)
            errors = property_rule_errors(row)
            if errors:
                raise CatalogValidationError(errors)
            if new_amenities is not None:
                row.amenities = new_amenities
            row.updated_by_id = actor.user_id
            # Always write the row, so the version moves even when only amenity links
            # changed (updated_by_id may already hold this actor).
            row.updated_at = func.now()
            await self._db.flush()
            self._audit(
                AuditEventCode.PROPERTY_UPDATED,
                actor,
                row.id,
                request_id,
                {"changed_fields": sorted(changes), "version": row.version},
            )
            return await self._detail(actor, row.id)

        return await run_in_transaction(self._db, work)

    async def archive_property(
        self, actor: Actor, property_id: uuid.UUID, *, request_id: str | None = None
    ) -> PropertyDetail:
        """Archive instead of deleting. Idempotent; children are kept unchanged."""
        require_permissions(actor, Permission.PROPERTIES_ARCHIVE)

        async def work() -> PropertyDetail:
            row = await self._locked(property_id)
            if row.is_archived:
                return await self._detail(actor, row.id)
            row.status = PropertyStatus.ARCHIVED
            row.archived_at = self._clock()
            row.archived_by_id = actor.user_id
            row.updated_by_id = actor.user_id
            await self._db.flush()
            self._audit(
                AuditEventCode.PROPERTY_ARCHIVED,
                actor,
                row.id,
                request_id,
                {"version": row.version},
            )
            return await self._detail(actor, row.id)

        return await run_in_transaction(self._db, work)

    async def restore_property(
        self, actor: Actor, property_id: uuid.UUID, *, request_id: str | None = None
    ) -> PropertyDetail:
        """Restore as ``inactive``. Idempotent. References need no re-check: types,
        subtypes, and amenities are never deleted, and disabled ones stay valid on
        records that already use them."""
        require_permissions(actor, Permission.PROPERTIES_ARCHIVE)

        async def work() -> PropertyDetail:
            row = await self._locked(property_id)
            if not row.is_archived:
                return await self._detail(actor, row.id)
            row.status = RESTORED_STATUS
            row.archived_at = None
            row.archived_by_id = None
            row.updated_by_id = actor.user_id
            await self._db.flush()
            self._audit(
                AuditEventCode.PROPERTY_RESTORED,
                actor,
                row.id,
                request_id,
                {"version": row.version},
            )
            return await self._detail(actor, row.id)

        return await run_in_transaction(self._db, work)

    # --- Helpers -------------------------------------------------------------------------

    async def _locked(self, property_id: uuid.UUID, *, with_amenities: bool = False) -> Property:
        row = await self._properties.get(
            property_id, for_update=True, with_amenities=with_amenities
        )
        if row is None:
            raise CatalogNotFoundError()
        return row

    async def _detail(self, actor: Actor, property_id: uuid.UUID) -> PropertyDetail:
        row = await self._properties.get_detail(property_id)
        if row is None:
            raise CatalogNotFoundError()
        owners = None
        if has_permissions(actor, Permission.PROPERTY_OWNERSHIP_READ):
            links = await self._ownerships.list_for_property(property_id)
            spans = [
                ShareSpan(link.share_percentage, link.start_date, link.end_date) for link in links
            ]
            owners = owners_view(actor, links, share_summary(spans, self._clock().date()))
        covers = await self._properties.cover_media_ids([property_id])
        return property_detail_view(
            actor, row, cover_media_id=covers.get(property_id), owners=owners
        )

    async def _classification(
        self, property_type_id: uuid.UUID, subtype_id: uuid.UUID | None
    ) -> tuple[PropertyType, PropertySubtype | None]:
        property_type = await self._reference.property_type(property_type_id)
        if property_type is None:
            raise InvalidRelationshipError({"property_type_id": [UNKNOWN_TYPE]})
        subtype = None
        if subtype_id is not None:
            subtype = await self._reference.subtype(subtype_id)
            if subtype is None:
                raise InvalidRelationshipError({"property_subtype_id": [UNKNOWN_SUBTYPE]})
        return property_type, subtype

    async def _check_classification_change(
        self, row: Property, data: PropertyUpdate, changes: dict[str, object]
    ) -> None:
        if not {"property_type_id", "property_subtype_id"} & changes.keys():
            return
        type_id = data.property_type_id if "property_type_id" in changes else None
        type_id = type_id or row.property_type_id
        subtype_id = (
            data.property_subtype_id
            if "property_subtype_id" in changes
            else row.property_subtype_id
        )
        property_type, subtype = await self._classification(type_id, subtype_id)
        ensure_classification_assignable(
            property_type,
            subtype,
            current_type_id=row.property_type_id,
            current_subtype_id=row.property_subtype_id,
        )
        if type_id != row.property_type_id and await self._properties.count_typed_units(row.id):
            # Unit subtypes belong to the property's type; changing it would orphan them.
            raise DependencyConflictError({"property_type_id": [UNITS_USE_TYPE]})

    async def _amenities(self, amenity_ids: list[uuid.UUID], *, field: str) -> list[Amenity]:
        amenities = await self._reference.amenities(amenity_ids)
        if len(amenities) != len(set(amenity_ids)):
            raise InvalidRelationshipError({field: [UNKNOWN_AMENITY]})
        return amenities

    async def _amenity_change(
        self, row: Property, amenity_ids: list[uuid.UUID] | None
    ) -> list[Amenity] | None:
        """The new amenity list, or ``None`` when the set is unchanged or not supplied."""
        if amenity_ids is None:
            return None
        current = {amenity.id for amenity in row.amenities}
        if set(amenity_ids) == current:
            return None
        amenities = await self._amenities(amenity_ids, field="amenity_ids")
        ensure_amenities_assignable(amenities, current_ids=current)
        return amenities

    async def _add_initial_owners(
        self, actor: Actor, row: Property, data: PropertyCreate, request_id: str | None
    ) -> None:
        spans: list[ShareSpan] = []
        for index, owner in enumerate(data.owners):
            # Share lock: a concurrent archive of the contact waits for this transaction.
            contact = await self._contacts.get(owner.contact_id, lock="share")
            if contact is None or contact.is_archived:
                raise InvalidRelationshipError(
                    {f"owners.{index}.contact_id": [UNAVAILABLE_CONTACT]}
                )
            spans.append(ShareSpan(owner.share_percentage, owner.start_date, owner.end_date))
        if peak_known_share(spans) > MAX_TOTAL:
            raise CatalogConflictError({"owners": [SHARE_LIMIT]})
        for owner in data.owners:
            link = PropertyOwnership(
                id=uuid.uuid4(),
                property_id=row.id,
                **owner.model_dump(),
                created_by_id=actor.user_id,
                updated_by_id=actor.user_id,
            )
            self._db.add(link)
            self._audit(
                AuditEventCode.PROPERTY_OWNER_ADDED,
                actor,
                row.id,
                request_id,
                {"ownership_id": str(link.id), "contact_id": str(link.contact_id)},
            )

    async def _add_initial_units(
        self,
        actor: Actor,
        row: Property,
        property_type: PropertyType,
        data: PropertyCreate,
        request_id: str | None,
    ) -> None:
        for index, unit_data in enumerate(data.units):
            if unit_data.property_subtype_id is not None:
                subtype = await self._reference.subtype(unit_data.property_subtype_id)
                if subtype is None:
                    raise InvalidRelationshipError(
                        {f"units.{index}.property_subtype_id": [UNKNOWN_SUBTYPE]}
                    )
                with _field_prefix(f"units.{index}"):
                    ensure_unit_subtype_assignable(property_type, subtype)
            amenities = await self._amenities(
                unit_data.amenity_ids, field=f"units.{index}.amenity_ids"
            )
            with _field_prefix(f"units.{index}"):
                ensure_amenities_assignable(amenities)
            unit = Unit(
                id=uuid.uuid4(),
                property_id=row.id,
                **unit_data.model_dump(exclude={"amenity_ids"}, exclude_none=True),
                created_by_id=actor.user_id,
                updated_by_id=actor.user_id,
            )
            unit.amenities = amenities
            self._db.add(unit)
            record_audit_event(
                self._db,
                AuditEventCode.UNIT_CREATED,
                actor_id=actor.user_id,
                request_id=request_id,
                entity_type="unit",
                entity_id=unit.id,
                metadata={"property_id": str(row.id)},
            )

    def _audit(
        self,
        code: AuditEventCode,
        actor: Actor,
        property_id: uuid.UUID,
        request_id: str | None,
        metadata: dict[str, Any],
    ) -> None:
        record_audit_event(
            self._db,
            code,
            actor_id=actor.user_id,
            request_id=request_id,
            entity_type=ENTITY_TYPE,
            entity_id=property_id,
            metadata=metadata,
        )
