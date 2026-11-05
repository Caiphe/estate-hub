"""Import every ORM model so mappers and ``Base.metadata`` are complete.

Alembic and tests import this module; application code imports models from their own
modules.
"""

from app.audit.models import AuditEvent
from app.auth.models import RefreshSession
from app.catalog.models import Amenity, PropertySubtype, PropertyType
from app.contacts.models import Contact
from app.media.models import Document, MediaAsset
from app.properties.models import (
    Property,
    PropertyOwnership,
    Unit,
    property_amenities,
    unit_amenities,
)
from app.users.models import Role, User, user_roles

__all__ = [
    "Amenity",
    "AuditEvent",
    "Contact",
    "Document",
    "MediaAsset",
    "Property",
    "PropertyOwnership",
    "PropertySubtype",
    "PropertyType",
    "RefreshSession",
    "Role",
    "Unit",
    "User",
    "property_amenities",
    "unit_amenities",
    "user_roles",
]
