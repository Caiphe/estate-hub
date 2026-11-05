"""Factories for property-catalog tests. Every test creates the records it needs."""

import uuid
from datetime import UTC, datetime
from typing import Any

from auth_support import Sessions, create_staff
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.auth.policy import Actor
from app.catalog.models import PropertySubtype, PropertyType
from app.contacts.constants import ContactKind
from app.contacts.models import Contact
from app.properties.constants import ManagementMode, PropertyStatus
from app.properties.models import Property


async def actor_for(session_factory: Sessions, role: str) -> Actor:
    user = await create_staff(session_factory, [role])
    return Actor(user_id=user.id, role_codes=frozenset({role}), active=True)


async def create_property_type(session_factory: Sessions, *subtypes: str) -> uuid.UUID:
    async with session_factory() as db:
        property_type = PropertyType(name=f"Type {uuid.uuid4().hex[:6]}")
        property_type.subtypes = [PropertySubtype(name=name) for name in subtypes]
        db.add(property_type)
        await db.commit()
        return property_type.id


async def subtype_id(session_factory: Sessions, type_id: uuid.UUID, name: str) -> uuid.UUID:
    async with session_factory() as db:
        found = await db.scalar(
            select(PropertySubtype.id).where(
                PropertySubtype.property_type_id == type_id, PropertySubtype.name == name
            )
        )
        assert found is not None
        return found


async def create_property(
    session_factory: Sessions,
    *,
    status: PropertyStatus = PropertyStatus.ACTIVE,
    management_mode: ManagementMode = ManagementMode.WHOLE,
    property_type_id: uuid.UUID | None = None,
) -> uuid.UUID:
    type_id = property_type_id or await create_property_type(session_factory)
    async with session_factory() as db:
        row = Property(
            name="Rose Cottage",
            property_type_id=type_id,
            management_mode=management_mode,
            address_line_1="1 High Street",
            locality="Bath",
            region="Somerset",
            country_code="GB",
            status=status,
            archived_at=datetime.now(UTC) if status == PropertyStatus.ARCHIVED else None,
        )
        db.add(row)
        await db.commit()
        return row.id


async def create_contact(session_factory: Sessions, **overrides: Any) -> uuid.UUID:
    values: dict[str, Any] = {
        "kind": ContactKind.PERSON,
        "display_name": "Olive Owner",
        "email": f"owner-{uuid.uuid4().hex[:6]}@example.com",
    }
    async with session_factory() as db:
        contact = Contact(**(values | overrides))
        db.add(contact)
        await db.commit()
        return contact.id


async def audit_events(session_factory: Sessions, code: str | None = None) -> list[AuditEvent]:
    async with session_factory() as db:
        statement = select(AuditEvent).order_by(AuditEvent.occurred_at, AuditEvent.id)
        if code is not None:
            statement = statement.where(AuditEvent.event_code == code)
        return list(await db.scalars(statement))
