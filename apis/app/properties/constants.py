from enum import StrEnum

PROPERTY_REFERENCE_PREFIX = "PR-"
PROPERTY_REFERENCE_MAX_LENGTH = 20
PROPERTY_NAME_MAX_LENGTH = 200
PROPERTY_DESCRIPTION_MAX_LENGTH = 5_000
PROPERTY_NOTES_MAX_LENGTH = 10_000
ADDRESS_LINE_MAX_LENGTH = 200
LOCALITY_MAX_LENGTH = 100
REGION_MAX_LENGTH = 100
POSTAL_CODE_MAX_LENGTH = 20
OWNERSHIP_NOTES_MAX_LENGTH = 2_000
YEAR_BUILT_MIN = 1000
YEAR_BUILT_MAX = 2999


class PropertyStatus(StrEnum):
    """Management lifecycle of the physical asset, not of any advertisement.

    ``archived`` is the only archival marker; related tables never carry their own flag
    for "the property is archived".
    """

    DRAFT = "draft"  # Being set up; not yet under management.
    ACTIVE = "active"  # Under management.
    INACTIVE = "inactive"  # Temporarily not managed, such as during renovation.
    ARCHIVED = "archived"  # Retired from normal use; kept for history.


class FurnishedState(StrEnum):
    FURNISHED = "furnished"
    PART_FURNISHED = "part_furnished"
    UNFURNISHED = "unfurnished"


class AreaUnit(StrEnum):
    # One unit per record, shared by floor and land area, so they are always comparable.
    SQUARE_METRE = "square_metre"
    SQUARE_FOOT = "square_foot"


class ManagementMode(StrEnum):
    """How a property is managed and, later, listed. One column; no derived flags.

    ``whole`` properties have no active units. ``units`` properties are managed through
    their units. ``mixed`` properties are managed both as a whole and by unit.
    """

    WHOLE = "whole"
    UNITS = "units"
    MIXED = "mixed"


class UnitStatus(StrEnum):
    """Operational state of a unit. Archival is separate (``archived_at``)."""

    AVAILABLE = "available"
    OCCUPIED = "occupied"
    UNAVAILABLE = "unavailable"


UNIT_IDENTIFIER_MAX_LENGTH = 50
UNIT_NAME_MAX_LENGTH = 200
FLOOR_LABEL_MAX_LENGTH = 50
