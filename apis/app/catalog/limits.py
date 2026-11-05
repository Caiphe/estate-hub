"""Hard caps that keep every catalog response bounded.

History-growing collections (units, owners, images, documents) are paginated. These
caps bound what is returned whole: reference lists and reorders (forms and reorder
requests need the complete set), a parent's active image gallery, and the active units
and current owners embedded in a property detail. Reaching a cap is ``409 conflict``.
"""

from app.catalog.errors import CatalogConflictError
from app.core.pagination import MAX_PAGE_SIZE

MAX_PROPERTY_TYPES = 100
MAX_SUBTYPES_PER_TYPE = 100
MAX_AMENITIES = 200
MAX_ACTIVE_UNITS_PER_PROPERTY = 500
MAX_CURRENT_OWNERS_PER_PROPERTY = 50
# One page holds a whole active gallery, so a gallery can be read and reordered at once.
MAX_ACTIVE_IMAGES_PER_PARENT = MAX_PAGE_SIZE


def ensure_below(count: int, limit: int, field: str) -> None:
    """Refuse adding one more record when ``count`` already reached ``limit``."""
    if count >= limit:
        raise CatalogConflictError({field: [f"This list has reached its limit of {limit}."]})
