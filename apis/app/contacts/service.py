import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.events import AuditEventCode
from app.audit.service import record_audit_event
from app.auth.permissions import Permission
from app.auth.policy import Actor, require_permissions
from app.catalog.errors import (
    ArchivedRecordError,
    CatalogNotFoundError,
    CatalogValidationError,
    DependencyConflictError,
    StaleVersionError,
)
from app.contacts.constants import ContactStatus
from app.contacts.models import Contact
from app.contacts.repository import ContactRepository
from app.contacts.rules import contact_rule_errors
from app.contacts.schemas import ContactCreate, ContactListQuery, ContactUpdate
from app.core.security.access_tokens import utc_now

ENTITY_TYPE = "contact"


class ContactService:
    """Staff management of contacts.

    Each mutation is one transaction containing the change and its audit event. Audit
    metadata holds the contact kind, changed field names, and the version: never an
    email, telephone, address, or note. Permissions are checked here as well as on the
    routes, so non-HTTP callers cannot bypass them.
    """

    def __init__(self, db: AsyncSession, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._db = db
        self._contacts = ContactRepository(db)
        self._clock = clock

    # --- Reads ---------------------------------------------------------------------------

    async def list_contacts(
        self, actor: Actor, query: ContactListQuery
    ) -> tuple[list[Contact], int]:
        require_permissions(actor, Permission.CONTACTS_READ)
        return await self._contacts.list(query)

    async def get_contact(self, actor: Actor, contact_id: uuid.UUID) -> Contact:
        require_permissions(actor, Permission.CONTACTS_READ)
        return await self._get(contact_id)

    # --- Mutations -----------------------------------------------------------------------

    async def create_contact(
        self, actor: Actor, data: ContactCreate, *, request_id: str | None = None
    ) -> Contact:
        require_permissions(actor, Permission.CONTACTS_MANAGE)

        async def work() -> Contact:
            contact = Contact(
                id=uuid.uuid4(),
                **data.model_dump(),
                created_by_id=actor.user_id,
                updated_by_id=actor.user_id,
            )
            self._db.add(contact)
            await self._db.flush()
            self._audit(
                AuditEventCode.CONTACT_CREATED, actor, contact, request_id, {"kind": contact.kind}
            )
            return contact

        return await self._unit_of_work(work)

    async def update_contact(
        self,
        actor: Actor,
        contact_id: uuid.UUID,
        data: ContactUpdate,
        *,
        request_id: str | None = None,
    ) -> Contact:
        require_permissions(actor, Permission.CONTACTS_MANAGE)

        async def work() -> Contact:
            contact = await self._get(contact_id, lock=True)
            if contact.is_archived:
                raise ArchivedRecordError()
            if contact.version != data.version:
                raise StaleVersionError()
            changes = {
                name: value
                for name, value in data.changes().items()
                if getattr(contact, name) != value
            }
            if not changes:
                return contact
            for name, value in changes.items():
                setattr(contact, name, value)
            errors = contact_rule_errors(contact)
            if errors:
                raise CatalogValidationError(errors)
            contact.updated_by_id = actor.user_id
            await self._db.flush()
            self._audit(
                AuditEventCode.CONTACT_UPDATED,
                actor,
                contact,
                request_id,
                {"changed_fields": sorted(changes), "version": contact.version},
            )
            return contact

        return await self._unit_of_work(work)

    async def archive_contact(
        self, actor: Actor, contact_id: uuid.UUID, *, request_id: str | None = None
    ) -> Contact:
        """Archive a contact that owns nothing now. Idempotent for an archived contact.

        The row lock conflicts with the share lock taken when an owner is added, so an
        ownership cannot be created for a contact while it is being archived.
        """
        require_permissions(actor, Permission.CONTACTS_MANAGE)

        async def work() -> Contact:
            contact = await self._get(contact_id, lock=True)
            if contact.is_archived:
                return contact
            now = self._clock()
            if await self._contacts.has_current_ownership(contact.id, now.date()):
                raise DependencyConflictError()
            contact.status = ContactStatus.ARCHIVED
            contact.archived_at = now
            contact.archived_by_id = actor.user_id
            contact.updated_by_id = actor.user_id
            await self._db.flush()
            self._audit(
                AuditEventCode.CONTACT_ARCHIVED,
                actor,
                contact,
                request_id,
                {"version": contact.version},
            )
            return contact

        return await self._unit_of_work(work)

    async def restore_contact(
        self, actor: Actor, contact_id: uuid.UUID, *, request_id: str | None = None
    ) -> Contact:
        require_permissions(actor, Permission.CONTACTS_MANAGE)

        async def work() -> Contact:
            contact = await self._get(contact_id, lock=True)
            if not contact.is_archived:
                return contact
            contact.status = ContactStatus.ACTIVE
            contact.archived_at = None
            contact.archived_by_id = None
            contact.updated_by_id = actor.user_id
            await self._db.flush()
            self._audit(
                AuditEventCode.CONTACT_RESTORED,
                actor,
                contact,
                request_id,
                {"version": contact.version},
            )
            return contact

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

    async def _get(self, contact_id: uuid.UUID, *, lock: bool = False) -> Contact:
        contact = await self._contacts.get(contact_id, lock="update" if lock else None)
        if contact is None:
            raise CatalogNotFoundError()
        return contact

    def _audit(
        self,
        code: AuditEventCode,
        actor: Actor,
        contact: Contact,
        request_id: str | None,
        metadata: dict[str, Any],
    ) -> None:
        record_audit_event(
            self._db,
            code,
            actor_id=actor.user_id,
            request_id=request_id,
            entity_type=ENTITY_TYPE,
            entity_id=contact.id,
            metadata=metadata,
        )
