import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.events import AuditEventCode
from app.audit.service import record_audit_event
from app.auth.permissions import Permission
from app.auth.policy import Actor, require_permissions
from app.catalog.errors import (
    ArchivedRecordError,
    CatalogConflictError,
    CatalogNotFoundError,
    CatalogValidationError,
    DuplicateReferenceError,
    InvalidRelationshipError,
)
from app.catalog.limits import MAX_CURRENT_OWNERS_PER_PROPERTY, ensure_below
from app.contacts.repository import ContactRepository
from app.core.pagination import MAX_PAGE_SIZE
from app.core.security.access_tokens import utc_now
from app.properties.models import Property, PropertyOwnership
from app.properties.repository import OwnershipRepository, PropertyRepository
from app.properties.schemas import DATES_ORDERED, OwnershipCreate, OwnershipUpdate
from app.properties.shares import (
    MAX_TOTAL,
    ShareSpan,
    ShareSummary,
    peak_known_share,
    share_summary,
)

ENTITY_TYPE = "property"
SHARE_LIMIT = "Known ownership shares in force on the same day would exceed 100%."
DUPLICATE_OWNER = "This contact already owns the property."
UNAVAILABLE_CONTACT = "The contact does not exist or is archived."


def _span(link: PropertyOwnership) -> ShareSpan:
    return ShareSpan(link.share_percentage, link.start_date, link.end_date)


class OwnershipService:
    """Owners of a property.

    Every change locks the property row first, so concurrent changes to one property's
    owners run one at a time and cannot both pass the share-total or duplicate checks.
    Adding an owner also takes a share lock on the contact, which conflicts with the
    lock taken to archive it. Audit events hold the ownership and contact IDs and changed
    field names, never contact details, shares, or notes.
    """

    def __init__(self, db: AsyncSession, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._db = db
        self._properties = PropertyRepository(db)
        self._ownerships = OwnershipRepository(db)
        self._contacts = ContactRepository(db)
        self._clock = clock

    # --- Reads ---------------------------------------------------------------------------

    async def list_owners(
        self,
        actor: Actor,
        property_id: uuid.UUID,
        *,
        include_ended: bool = False,
        limit: int = MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> tuple[list[PropertyOwnership], ShareSummary]:
        """One page of links, and today's share summary over every current link (at most
        MAX_CURRENT_OWNERS_PER_PROPERTY), whatever the page."""
        require_permissions(actor, Permission.PROPERTY_OWNERSHIP_READ)
        await self._property(property_id)
        links = await self._ownerships.list_for_property(
            property_id, include_ended=include_ended, limit=limit, offset=offset
        )
        current = await self._ownerships.list_for_property(property_id)
        return links, share_summary(list(map(_span, current)), self._clock().date())

    async def count_owners(
        self, actor: Actor, property_id: uuid.UUID, *, include_ended: bool = False
    ) -> int:
        require_permissions(actor, Permission.PROPERTY_OWNERSHIP_READ)
        await self._property(property_id)
        return await self._ownerships.count_for_property(property_id, include_ended=include_ended)

    async def get_owner(
        self, actor: Actor, property_id: uuid.UUID, ownership_id: uuid.UUID
    ) -> PropertyOwnership:
        """A current or ended link of this property; a link of another is not found."""
        require_permissions(actor, Permission.PROPERTY_OWNERSHIP_READ)
        await self._property(property_id)
        return await self._link(property_id, ownership_id)

    # --- Mutations -----------------------------------------------------------------------

    async def add_owner(
        self,
        actor: Actor,
        property_id: uuid.UUID,
        data: OwnershipCreate,
        *,
        request_id: str | None = None,
    ) -> PropertyOwnership:
        require_permissions(actor, Permission.PROPERTY_OWNERSHIP_MANAGE)

        async def work() -> PropertyOwnership:
            await self._changeable_property(property_id)
            contact = await self._contacts.get(data.contact_id, lock="share")
            if contact is None or contact.is_archived:
                raise InvalidRelationshipError({"contact_id": [UNAVAILABLE_CONTACT]})
            current = await self._ownerships.list_for_property(property_id)
            ensure_below(len(current), MAX_CURRENT_OWNERS_PER_PROPERTY, "contact_id")
            if any(link.contact_id == contact.id for link in current):
                raise DuplicateReferenceError({"contact_id": [DUPLICATE_OWNER]})
            link = PropertyOwnership(
                id=uuid.uuid4(),
                property_id=property_id,
                **data.model_dump(),
                created_by_id=actor.user_id,
                updated_by_id=actor.user_id,
            )
            self._check_shares([*map(_span, current), _span(link)])
            self._db.add(link)
            await self._flush()
            self._audit(
                AuditEventCode.PROPERTY_OWNER_ADDED,
                actor,
                link,
                request_id,
                {"ownership_id": str(link.id), "contact_id": str(link.contact_id)},
            )
            return await self._reload(link)

        return await self._unit_of_work(work)

    async def update_owner(
        self,
        actor: Actor,
        property_id: uuid.UUID,
        ownership_id: uuid.UUID,
        data: OwnershipUpdate,
        *,
        request_id: str | None = None,
    ) -> PropertyOwnership:
        require_permissions(actor, Permission.PROPERTY_OWNERSHIP_MANAGE)

        async def work() -> PropertyOwnership:
            await self._changeable_property(property_id)
            link = await self._link(property_id, ownership_id)
            if link.is_archived:
                raise ArchivedRecordError()
            changes = {
                name: value
                for name, value in data.changes().items()
                if getattr(link, name) != value
            }
            if not changes:
                return link
            # Load the other links before changing this one: a query may autoflush.
            others = [
                other
                for other in await self._ownerships.list_for_property(property_id)
                if other.id != link.id
            ]
            for name, value in changes.items():
                setattr(link, name, value)
            if link.start_date and link.end_date and link.end_date < link.start_date:
                raise CatalogValidationError({"end_date": [DATES_ORDERED]})
            self._check_shares([*map(_span, others), _span(link)])
            link.updated_by_id = actor.user_id
            await self._flush()
            self._audit(
                AuditEventCode.PROPERTY_OWNER_UPDATED,
                actor,
                link,
                request_id,
                {
                    "ownership_id": str(link.id),
                    "contact_id": str(link.contact_id),
                    "changed_fields": sorted(changes),
                },
            )
            return await self._reload(link)

        return await self._unit_of_work(work)

    async def end_owner(
        self,
        actor: Actor,
        property_id: uuid.UUID,
        ownership_id: uuid.UUID,
        *,
        request_id: str | None = None,
    ) -> PropertyOwnership:
        """End a link. Final and idempotent: the record stays as history."""
        require_permissions(actor, Permission.PROPERTY_OWNERSHIP_MANAGE)

        async def work() -> PropertyOwnership:
            await self._changeable_property(property_id)
            link = await self._link(property_id, ownership_id)
            if link.is_archived:
                return link
            link.archived_at = self._clock()
            link.archived_by_id = actor.user_id
            link.updated_by_id = actor.user_id
            await self._flush()
            self._audit(
                AuditEventCode.PROPERTY_OWNER_REMOVED,
                actor,
                link,
                request_id,
                {"ownership_id": str(link.id), "contact_id": str(link.contact_id)},
            )
            return await self._reload(link)

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

    async def _link(self, property_id: uuid.UUID, ownership_id: uuid.UUID) -> PropertyOwnership:
        link = await self._ownerships.get(property_id, ownership_id)
        if link is None:
            raise CatalogNotFoundError()
        return link

    async def _reload(self, link: PropertyOwnership) -> PropertyOwnership:
        """Reload with the contact so the response needs no implicit I/O."""
        return await self._link(link.property_id, link.id)

    @staticmethod
    def _check_shares(spans: list[ShareSpan]) -> None:
        if peak_known_share(spans) > MAX_TOTAL:
            raise CatalogConflictError({"share_percentage": [SHARE_LIMIT]})

    async def _flush(self) -> None:
        try:
            await self._db.flush()
        except IntegrityError as exc:
            # The property lock prevents this; the unique index is the final guard.
            if "uq_property_ownerships_current_link" in str(exc.orig):
                raise DuplicateReferenceError({"contact_id": [DUPLICATE_OWNER]}) from None
            raise

    def _audit(
        self,
        code: AuditEventCode,
        actor: Actor,
        link: PropertyOwnership,
        request_id: str | None,
        metadata: dict[str, Any],
    ) -> None:
        record_audit_event(
            self._db,
            code,
            actor_id=actor.user_id,
            request_id=request_id,
            entity_type=ENTITY_TYPE,
            entity_id=link.property_id,
            metadata=metadata,
        )
