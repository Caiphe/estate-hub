"""Which reference records may be newly assigned to a property."""

import uuid

import pytest

from app.catalog.errors import InvalidRelationshipError
from app.catalog.models import Amenity, PropertySubtype, PropertyType
from app.properties.rules import (
    DISABLED,
    WRONG_PARENT,
    ensure_amenities_assignable,
    ensure_classification_assignable,
)


def property_type(*, active: bool = True) -> PropertyType:
    return PropertyType(id=uuid.uuid4(), name="Residential", is_active=active)


def subtype(parent: PropertyType, *, active: bool = True) -> PropertySubtype:
    return PropertySubtype(
        id=uuid.uuid4(), name="House", property_type_id=parent.id, is_active=active
    )


def amenity(*, active: bool = True) -> Amenity:
    return Amenity(id=uuid.uuid4(), name="Pool", is_active=active)


def fields_of(error: pytest.ExceptionInfo[InvalidRelationshipError]) -> dict[str, list[str]]:
    assert error.value.fields is not None
    return error.value.fields


def test_active_classification_is_assignable() -> None:
    parent = property_type()

    ensure_classification_assignable(parent, subtype(parent))
    ensure_classification_assignable(parent, None)


def test_disabled_type_cannot_be_newly_assigned() -> None:
    with pytest.raises(InvalidRelationshipError) as error:
        ensure_classification_assignable(property_type(active=False), None)

    assert fields_of(error) == {"property_type_id": [DISABLED]}


def test_disabled_subtype_cannot_be_newly_assigned() -> None:
    parent = property_type()

    with pytest.raises(InvalidRelationshipError) as error:
        ensure_classification_assignable(parent, subtype(parent, active=False))

    assert fields_of(error) == {"property_subtype_id": [DISABLED]}


def test_subtypes_of_a_disabled_type_cannot_be_newly_assigned() -> None:
    parent = property_type(active=False)
    child = subtype(parent)

    with pytest.raises(InvalidRelationshipError) as error:
        ensure_classification_assignable(parent, child, current_type_id=parent.id)

    assert fields_of(error) == {"property_subtype_id": [DISABLED]}


def test_disabled_references_already_in_use_remain_valid() -> None:
    parent = property_type(active=False)
    child = subtype(parent, active=False)

    ensure_classification_assignable(
        parent, child, current_type_id=parent.id, current_subtype_id=child.id
    )


def test_subtype_of_another_type_is_rejected() -> None:
    other = property_type()

    with pytest.raises(InvalidRelationshipError) as error:
        ensure_classification_assignable(property_type(), subtype(other))

    assert fields_of(error) == {"property_subtype_id": [WRONG_PARENT]}


def test_inactive_amenities_cannot_be_newly_added() -> None:
    kept, added, active = amenity(active=False), amenity(active=False), amenity()

    ensure_amenities_assignable([kept, active], current_ids={kept.id})
    with pytest.raises(InvalidRelationshipError) as error:
        ensure_amenities_assignable([kept, added], current_ids={kept.id})

    assert fields_of(error) == {"amenity_ids": [DISABLED]}
    assert error.value.status_code == 422
