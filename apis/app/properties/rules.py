"""Classification and amenity rules that depend on stored reference data.

The database guarantees a subtype belongs to its type. Whether a reference may be
*newly* assigned depends on what the property already uses, so it is checked here, by
services, before a create or update. Disabled references a property already has stay
valid; the caller passes them as ``current_*``.
"""

import uuid
from collections.abc import Collection, Iterable

from app.catalog.errors import (
    CatalogConflictError,
    DependencyConflictError,
    InvalidRelationshipError,
)
from app.catalog.models import Amenity, PropertySubtype, PropertyType
from app.properties.constants import ManagementMode

DISABLED = "This option is disabled and cannot be newly assigned."
WRONG_PARENT = "The subtype does not belong to the selected property type."


def ensure_classification_assignable(
    property_type: PropertyType,
    subtype: PropertySubtype | None,
    *,
    current_type_id: uuid.UUID | None = None,
    current_subtype_id: uuid.UUID | None = None,
) -> None:
    fields: dict[str, list[str]] = {}
    if not property_type.is_active and property_type.id != current_type_id:
        fields["property_type_id"] = [DISABLED]
    if subtype is not None:
        if subtype.property_type_id != property_type.id:
            fields["property_subtype_id"] = [WRONG_PARENT]
        elif subtype.id != current_subtype_id and not (
            subtype.is_active and property_type.is_active
        ):
            # A disabled type also makes its subtypes unselectable.
            fields["property_subtype_id"] = [DISABLED]
    if fields:
        raise InvalidRelationshipError(fields)


def ensure_amenities_assignable(
    amenities: Iterable[Amenity], *, current_ids: Collection[uuid.UUID] = ()
) -> None:
    if any(not a.is_active and a.id not in current_ids for a in amenities):
        raise InvalidRelationshipError({"amenity_ids": [DISABLED]})


# --- Management mode and units -----------------------------------------------------------

WHOLE_PROPERTY = "This property is managed as a whole; change its management mode first."
HAS_ACTIVE_UNITS = "Archive the property's active units before managing it as a whole."


def ensure_mode_allows_units(mode: ManagementMode) -> None:
    """A ``whole`` property has no active units, so none can be added or restored."""
    if mode == ManagementMode.WHOLE:
        raise CatalogConflictError({"management_mode": [WHOLE_PROPERTY]})


def ensure_mode_change_allowed(new_mode: ManagementMode, active_units: int) -> None:
    if new_mode == ManagementMode.WHOLE and active_units:
        raise DependencyConflictError({"management_mode": [HAS_ACTIVE_UNITS]})


def ensure_unit_subtype_assignable(
    property_type: PropertyType,
    subtype: PropertySubtype,
    *,
    current_subtype_id: uuid.UUID | None = None,
) -> None:
    """A unit's subtype must belong to its property's type.

    The type itself is already the property's, so a disabled type does not block the
    unit; it does block newly choosing any of its subtypes.
    """
    ensure_classification_assignable(
        property_type,
        subtype,
        current_type_id=property_type.id,
        current_subtype_id=current_subtype_id,
    )
