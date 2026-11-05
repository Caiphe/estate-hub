"""The property-catalog route inventory, fixed before the routes are implemented.

Every catalog endpoint is listed here with its exact permission and success status. Later
stages register routes that match this table, and tests compare the two. Conventions:

- Plural kebab-case resources under ``/api/v1``; path IDs are named ``{<resource>_id}``.
- ``DELETE`` archives and returns the archived record (``200``). Hard deletion is not
  part of ordinary CRUD. Archived properties, units, and contacts come back through an
  explicit ``POST .../restore``. Ending an ownership link, and archiving media or a
  document, is final: add a new link or upload again instead.
- Reference data is never deleted; ``disable`` and ``reactivate`` replace it.
- ``PUT .../order`` replaces a whole ordering in one request.
- The route permission is checked before any record is loaded, so a caller without it
  receives ``403`` whether or not the ID exists. With it, a missing record and a record
  under a different parent are both ``404 not_found``.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from fastapi import status

from app.auth.permissions import Permission

P = Permission
Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


@dataclass(frozen=True, slots=True)
class RouteContract:
    method: Method
    path: str
    permission: Permission
    success_status: int
    summary: str


# Permissions that filter fields inside responses rather than guarding a route.
FIELD_LEVEL_PERMISSIONS: dict[Permission, str] = {
    P.PROPERTIES_READ_INTERNAL: "Internal notes on property and unit responses.",
    P.PROPERTY_OWNERSHIP_READ: "Owner summaries inside property detail.",
    P.CONTACTS_READ: "Owner email, telephone, and address inside ownership responses.",
    P.PROPERTIES_ARCHIVE: "Archived properties in `GET /properties` (`include_archived=true`).",
    P.REFERENCE_DATA_MANAGE: "Disabled records in reference-data lists (`include_inactive`).",
}

CATALOG_PERMISSIONS = frozenset(
    {
        P.PROPERTIES_READ,
        P.PROPERTIES_CREATE,
        P.PROPERTIES_UPDATE,
        P.PROPERTIES_ARCHIVE,
        P.PROPERTIES_READ_INTERNAL,
        P.PROPERTY_UNITS_MANAGE,
        P.PROPERTY_MEDIA_MANAGE,
        P.PROPERTY_DOCUMENTS_READ,
        P.PROPERTY_DOCUMENTS_MANAGE,
        P.PROPERTY_OWNERSHIP_READ,
        P.PROPERTY_OWNERSHIP_MANAGE,
        P.CONTACTS_READ,
        P.CONTACTS_MANAGE,
        P.REFERENCE_DATA_MANAGE,
    }
)

# Path segments that name an action or a singular sub-resource rather than a collection.
ACTION_SEGMENTS = frozenset({"restore", "disable", "reactivate", "order", "cover", "content"})


def _r(method: Method, path: str, permission: Permission, summary: str) -> RouteContract:
    # POST to a collection creates (201 with Location); POST to an action returns the record.
    creates = method == "POST" and path.rsplit("/", 1)[-1] not in ACTION_SEGMENTS
    success = status.HTTP_201_CREATED if creates else status.HTTP_200_OK
    return RouteContract(method, path, permission, success, summary)


def _reference(collection: str, item: str, noun: str, plural: str) -> Iterator[RouteContract]:
    manage = P.REFERENCE_DATA_MANAGE
    article = "an" if noun[0] in "aeiou" else "a"
    yield _r("POST", collection, manage, f"Create {article} {noun}")
    yield _r("PATCH", item, manage, f"Update {article} {noun}")
    yield _r("POST", f"{item}/disable", manage, f"Disable {article} {noun}")
    yield _r("POST", f"{item}/reactivate", manage, f"Reactivate {article} {noun}")
    yield _r("PUT", f"{collection}/order", manage, f"Reorder {plural}")


def _files(parent: str, label: str) -> Iterator[RouteContract]:
    media, media_item = f"{parent}/media", f"{parent}/media/{{media_id}}"
    yield _r("GET", media, P.PROPERTIES_READ, f"List {label} images")
    yield _r("POST", media, P.PROPERTY_MEDIA_MANAGE, f"Upload a {label} image")
    yield _r("GET", f"{media_item}/content", P.PROPERTIES_READ, f"Download a {label} image")
    yield _r("PATCH", media_item, P.PROPERTY_MEDIA_MANAGE, f"Update {label} image alt text")
    yield _r("PUT", f"{media}/order", P.PROPERTY_MEDIA_MANAGE, f"Reorder {label} images")
    yield _r("POST", f"{media_item}/cover", P.PROPERTY_MEDIA_MANAGE, f"Set the {label} cover")
    yield _r("DELETE", media_item, P.PROPERTY_MEDIA_MANAGE, f"Archive a {label} image")

    docs, doc = f"{parent}/documents", f"{parent}/documents/{{document_id}}"
    read, manage = P.PROPERTY_DOCUMENTS_READ, P.PROPERTY_DOCUMENTS_MANAGE
    yield _r("GET", docs, read, f"List {label} documents")
    yield _r("POST", docs, manage, f"Upload a {label} document")
    yield _r("GET", doc, read, f"Get {label} document metadata")
    yield _r("GET", f"{doc}/content", read, f"Download a {label} document")
    yield _r("PATCH", doc, manage, f"Update {label} document metadata")
    yield _r("PUT", f"{doc}/content", manage, f"Replace a {label} document file")
    yield _r("DELETE", doc, manage, f"Archive a {label} document")


def _inventory() -> Iterator[RouteContract]:
    # Reference data. Reading active options is part of reading the catalog.
    types, type_item = "/property-types", "/property-types/{property_type_id}"
    yield _r("GET", types, P.PROPERTIES_READ, "List property types with subtypes")
    yield _r("GET", type_item, P.PROPERTIES_READ, "Get a property type")
    yield from _reference(types, type_item, "property type", "property types")
    subtype_item = f"{type_item}/subtypes/{{property_subtype_id}}"
    yield _r("GET", subtype_item, P.PROPERTIES_READ, "Get a property subtype")
    yield from _reference(
        f"{type_item}/subtypes", subtype_item, "property subtype", "property subtypes"
    )
    yield _r("GET", "/amenities", P.PROPERTIES_READ, "List amenities")
    yield _r("GET", "/amenities/{amenity_id}", P.PROPERTIES_READ, "Get an amenity")
    yield from _reference("/amenities", "/amenities/{amenity_id}", "amenity", "amenities")

    contacts, contact = "/contacts", "/contacts/{contact_id}"
    yield _r("GET", contacts, P.CONTACTS_READ, "List contacts")
    yield _r("POST", contacts, P.CONTACTS_MANAGE, "Create a contact")
    yield _r("GET", contact, P.CONTACTS_READ, "Get a contact")
    yield _r("PATCH", contact, P.CONTACTS_MANAGE, "Update a contact")
    yield _r("DELETE", contact, P.CONTACTS_MANAGE, "Archive a contact")
    yield _r("POST", f"{contact}/restore", P.CONTACTS_MANAGE, "Restore a contact")

    properties, prop = "/properties", "/properties/{property_id}"
    yield _r("GET", properties, P.PROPERTIES_READ, "List properties")
    yield _r("POST", properties, P.PROPERTIES_CREATE, "Create a property")
    yield _r("GET", prop, P.PROPERTIES_READ, "Get a property")
    yield _r("PATCH", prop, P.PROPERTIES_UPDATE, "Update a property")
    yield _r("DELETE", prop, P.PROPERTIES_ARCHIVE, "Archive a property")
    yield _r("POST", f"{prop}/restore", P.PROPERTIES_ARCHIVE, "Restore a property")

    owners, owner = f"{prop}/owners", f"{prop}/owners/{{ownership_id}}"
    yield _r("GET", owners, P.PROPERTY_OWNERSHIP_READ, "List property owners")
    yield _r("POST", owners, P.PROPERTY_OWNERSHIP_MANAGE, "Add a property owner")
    yield _r("GET", owner, P.PROPERTY_OWNERSHIP_READ, "Get a property ownership")
    yield _r("PATCH", owner, P.PROPERTY_OWNERSHIP_MANAGE, "Update a property ownership")
    yield _r("DELETE", owner, P.PROPERTY_OWNERSHIP_MANAGE, "End a property ownership")

    units, unit = f"{prop}/units", f"{prop}/units/{{unit_id}}"
    yield _r("GET", units, P.PROPERTIES_READ, "List units")
    yield _r("POST", units, P.PROPERTY_UNITS_MANAGE, "Create a unit")
    yield _r("GET", unit, P.PROPERTIES_READ, "Get a unit")
    yield _r("PATCH", unit, P.PROPERTY_UNITS_MANAGE, "Update a unit")
    yield _r("DELETE", unit, P.PROPERTY_UNITS_MANAGE, "Archive a unit")
    yield _r("POST", f"{unit}/restore", P.PROPERTY_UNITS_MANAGE, "Restore a unit")

    yield from _files(prop, "property")
    yield from _files(unit, "unit")


CATALOG_ROUTES: tuple[RouteContract, ...] = tuple(_inventory())

# Collections whose plural does not end in "s".
UNCOUNTABLE_COLLECTIONS = frozenset({"media"})
# The ID parameter that must follow each collection segment.
ID_PARAMETERS: dict[str, str] = {
    "property-types": "property_type_id",
    "subtypes": "property_subtype_id",
    "amenities": "amenity_id",
    "contacts": "contact_id",
    "properties": "property_id",
    "owners": "ownership_id",
    "units": "unit_id",
    "media": "media_id",
    "documents": "document_id",
}


def render_routes_markdown() -> str:
    """The inventory as a Markdown table; the README embeds this exact text."""
    lines = [
        "| Method | Path | Permission | Success | Summary |",
        "| --- | --- | --- | :---: | --- |",
    ]
    for route in CATALOG_ROUTES:
        lines.append(
            f"| `{route.method}` | `{route.path}` | `{route.permission.value}` "
            f"| `{route.success_status}` | {route.summary} |"
        )
    return "\n".join(lines)
