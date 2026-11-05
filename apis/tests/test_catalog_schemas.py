"""Schema boundaries: normalization, validation, omitted-vs-null, privacy, and OpenAPI."""

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

import pytest
from auth_support import Sessions
from catalog_support import actor_for, create_contact
from fastapi import FastAPI, Query
from pydantic import BaseModel, ValidationError

from app.auth.policy import Actor
from app.catalog.errors import CATALOG_ERRORS
from app.catalog.models import Amenity, PropertySubtype, PropertyType
from app.catalog.openapi import codes_by_status, error_responses
from app.catalog.schemas import (
    AmenityCreate,
    AmenityUpdate,
    ReferenceCreate,
    ReferenceOrder,
    ReferenceUpdate,
)
from app.contacts.schemas import ContactCreate, ContactDetail, ContactSummary, ContactUpdate
from app.media.schemas import (
    DocumentCreate,
    DocumentDetail,
    DocumentSummary,
    DocumentUpdate,
    MediaOrder,
    MediaPublic,
    MediaUpdate,
)
from app.properties.constants import ManagementMode, PropertyStatus
from app.properties.models import Property, Unit
from app.properties.ownership import OwnershipService
from app.properties.repository import PropertyRepository
from app.properties.schemas import (
    OwnershipCreate,
    OwnershipUpdate,
    PropertyCreate,
    PropertyDetail,
    PropertyListQuery,
    PropertySort,
    PropertySummary,
    PropertyUpdate,
    PublicProperty,
    UnitCreate,
    UnitUpdate,
    owners_view,
    property_detail_view,
    property_rule_errors,
    property_summary_view,
)

BASE: dict[str, Any] = {
    "name": "Rose Cottage",
    "property_type_id": str(uuid.uuid4()),
    "address_line_1": "1 High Street",
    "locality": "Bath",
    "region": "Somerset",
    "country_code": "gb",
}
WRITE_SCHEMAS: list[type[BaseModel]] = [
    ReferenceCreate,
    ReferenceUpdate,
    AmenityCreate,
    AmenityUpdate,
    ReferenceOrder,
    ContactCreate,
    ContactUpdate,
    OwnershipCreate,
    OwnershipUpdate,
    PropertyCreate,
    PropertyUpdate,
    UnitCreate,
    UnitUpdate,
    MediaUpdate,
    MediaOrder,
    DocumentCreate,
    DocumentUpdate,
    PropertyListQuery,
]
SERVER_CONTROLLED = {
    "id",
    "reference",
    "version_id",
    "created_at",
    "updated_at",
    "created_by_id",
    "updated_by_id",
    "archived_at",
    "archived_by_id",
    "storage_key",
    "uploaded_by_id",
}


# --- Write schemas: shape rules ---------------------------------------------------------


@pytest.mark.parametrize("schema", WRITE_SCHEMAS, ids=lambda s: s.__name__)
def test_write_schemas_reject_unknown_and_server_fields(schema: type[BaseModel]) -> None:
    assert schema.model_config.get("extra") == "forbid"
    assert not SERVER_CONTROLLED & set(schema.model_fields)


def test_property_create_normalizes_and_defaults() -> None:
    created = PropertyCreate.model_validate(
        BASE
        | {
            "name": "  Rose   Cottage ",
            "address_line_2": "   ",
            "postal_code": " ba1  1aa",
            "description": "  ",
            "latitude": "51.381072",
            "longitude": "-2.359910",
            "bathrooms": "1.5",
        }
    )

    assert created.name == "Rose Cottage"
    assert created.address_line_2 is None and created.description is None
    assert (created.postal_code, created.country_code) == ("BA1 1AA", "GB")
    assert created.latitude == Decimal("51.381072")
    assert created.bathrooms == Decimal("1.5")
    assert (created.status, created.management_mode) == (
        PropertyStatus.DRAFT,
        ManagementMode.WHOLE,
    )
    assert (created.amenity_ids, created.owners, created.units) == ([], [], [])


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"name": "   "}, "at least 1 character"),
        ({"name": "x" * 201}, "at most 200"),
        ({"locality": ""}, "at least 1 character"),
        ({"country_code": "GBR"}, "pattern"),
        ({"country_code": "1A"}, "pattern"),
        ({"latitude": "51.5"}, "latitude and longitude"),
        ({"latitude": "90.000001", "longitude": "0"}, "less than or equal to 90"),
        ({"latitude": "1.1234567", "longitude": "0"}, "decimal places"),
        ({"bathrooms": "1.25"}, "multiple of 0.5"),
        ({"bedrooms": -1}, "greater than or equal to 0"),
        ({"bedrooms": 2.5}, "valid integer"),
        ({"floor_area": "80"}, "area_unit is required"),
        ({"area_unit": "square_metre"}, "area_unit is required"),
        ({"floor_area": "1.005", "area_unit": "square_metre"}, "decimal places"),
        ({"year_built": 999}, "greater than or equal to 1000"),
        ({"status": "archived"}, "DELETE"),
        ({"status": "deleted"}, "Input should be"),
        ({"amenity_ids": [str(uuid.UUID(int=1))] * 2}, "must not repeat"),
        ({"units": [{"identifier": "Flat 1"}]}, "management_mode"),
        (
            {
                "management_mode": "units",
                "units": [{"identifier": "Flat 1"}, {"identifier": " flat  1 "}],
            },
            "unique",
        ),
        (
            {
                "owners": [
                    {"contact_id": str(uuid.UUID(int=7))},
                    {"contact_id": str(uuid.UUID(int=7))},
                ]
            },
            "only once",
        ),
        ({"reference": "PR-100001"}, "Extra inputs"),
        ({"version": 1}, "Extra inputs"),
        ({"archived_at": "2026-01-01T00:00:00Z"}, "Extra inputs"),
        ({"price": "250000"}, "Extra inputs"),
    ],
)
def test_property_create_rejects_invalid_input(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError) as error:
        PropertyCreate.model_validate(BASE | changes)

    assert message in str(error.value)


def test_validation_errors_do_not_echo_rejected_values() -> None:
    with pytest.raises(ValidationError) as error:
        PropertyCreate.model_validate(BASE | {"internal_notes": "SECRET-" + "x" * 10_000})

    assert "SECRET-" not in str(error.value)


def test_property_update_distinguishes_omitted_and_null() -> None:
    update = PropertyUpdate.model_validate(
        {"version": 3, "description": None, "postal_code": None, "bedrooms": 4}
    )

    assert update.changes() == {"description": None, "postal_code": None, "bedrooms": 4}
    assert "name" not in update.changes()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"version": 1}, "At least one field"),
        ({"name": "x"}, "version"),
        ({"version": 0, "name": "x"}, "greater than or equal to 1"),
        ({"version": 1, "name": None}, "name cannot be null"),
        ({"version": 1, "country_code": None}, "country_code cannot be null"),
        ({"version": 1, "amenity_ids": None}, "amenity_ids cannot be null"),
        ({"version": 1, "status": "archived"}, "DELETE"),
        ({"version": 1, "latitude": "10", "longitude": None}, "latitude and longitude"),
        ({"version": 1, "owners": []}, "Extra inputs"),
        ({"version": 1, "units": []}, "Extra inputs"),
    ],
)
def test_property_update_rejects_invalid_input(payload: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError) as error:
        PropertyUpdate.model_validate(payload)

    assert message in str(error.value)


def test_partial_pairs_are_left_to_the_service() -> None:
    # Changing only latitude may complete a stored pair; the service checks the merge.
    update = PropertyUpdate.model_validate({"version": 1, "latitude": "10"})
    merged = Property(latitude=update.latitude, longitude=None)

    assert property_rule_errors(merged) == {
        "latitude": ["latitude and longitude must be given together."]
    }


def test_list_query_parses_filters_and_rejects_unknown_values() -> None:
    query = PropertyListQuery.model_validate(
        {"status": ["active", "draft"], "sort": "-name", "country_code": "gb", "q": "rose"}
    )

    assert query.status == [PropertyStatus.ACTIVE, PropertyStatus.DRAFT]
    assert (query.sort, query.country_code) == (PropertySort.NAME_DESC, "GB")
    assert PropertyListQuery().sort == PropertySort.UPDATED_AT_DESC
    for invalid in (
        {"sort": "price"},
        {"sort": "name; DROP TABLE properties"},
        {"status": ["sold"]},
        {"limit": 101},
        {"offset": -1},
        {"q": ""},
        {"status": ["archived"]},
        {"management_mode": ["partial"]},
        {"property_type_id": ["not-a-uuid"]},
        {"colour": "red"},
    ):
        with pytest.raises(ValidationError):
            PropertyListQuery.model_validate(invalid)
    assert PropertyListQuery.model_validate({"status": ["archived"], "include_archived": True})


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (ReferenceCreate, {"name": "  "}),
        (ReferenceCreate, {"name": "House", "display_order": 10_001}),
        (ReferenceUpdate, {}),
        (ReferenceUpdate, {"name": None}),
        (ReferenceUpdate, {"is_active": False}),
        (ReferenceUpdate, {"property_type_id": str(uuid.uuid4())}),
        (AmenityCreate, {"name": "Pool", "category": "Outdoor space"}),
        (ReferenceOrder, {"ids": []}),
        (ReferenceOrder, {"ids": [str(uuid.UUID(int=1))] * 2}),
        (MediaUpdate, {}),
        (MediaUpdate, {"storage_key": "media/aa/" + "a" * 32}),
        (DocumentCreate, {"category": "will", "title": "Will"}),
        (DocumentCreate, {"category": "lease", "title": "Lease", "expiry_date": "2026-02-30"}),
        (DocumentUpdate, {"version": 1}),
        (DocumentUpdate, {"version": 1, "title": None}),
    ],
)
def test_supporting_write_schemas_reject_invalid_input(
    schema: type[BaseModel], payload: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


def test_reference_schemas_normalize() -> None:
    assert ReferenceCreate.model_validate({"name": " Student   room "}).name == "Student room"
    amenity = AmenityCreate.model_validate({"name": "Pool", "category": " Outdoor "})
    assert amenity.category == "outdoor"
    assert ReferenceUpdate.model_validate({"description": None}).changes() == {"description": None}
    assert DocumentUpdate.model_validate({"version": 2, "expiry_date": None}).changes() == {
        "expiry_date": None
    }


# --- Output schemas: privacy ------------------------------------------------------------


@pytest.mark.parametrize(
    "schema",
    [MediaPublic, DocumentSummary, DocumentDetail, PropertySummary, PropertyDetail, PublicProperty],
    ids=lambda s: s.__name__,
)
def test_no_output_schema_exposes_storage(schema: type[BaseModel]) -> None:
    assert not {name for name in schema.model_fields if "storage" in name or "path" in name}


def test_summaries_omit_private_fields() -> None:
    assert not {"address_line_1", "internal_notes", "owners", "postal_code"} & set(
        PropertySummary.model_fields
    )
    assert not {"internal_notes", "address_line_1"} & set(ContactSummary.model_fields)
    assert "internal_notes" in ContactDetail.model_fields


def test_public_property_contains_no_private_information() -> None:
    private = {
        "id",
        "reference",
        "description",
        "address_line_1",
        "address_line_2",
        "postal_code",
        "latitude",
        "longitude",
        "internal_notes",
        "owners",
        "status",
        "version",
        "created_by_id",
        "updated_by_id",
        "archived_at",
    }

    assert not private & set(PublicProperty.model_fields)


async def load_detail(session_factory: Sessions, actor: Actor) -> tuple[Property, Any]:
    contact_id = await create_contact(session_factory, email="olive@example.com")
    async with session_factory() as db:
        parent = PropertyType(name="Residential")
        parent.subtypes = [PropertySubtype(name="Apartment")]
        pool = Amenity(name="Pool")
        db.add_all([parent, pool])
        await db.flush()
        row = Property(
            name="Rose Court",
            property_type_id=parent.id,
            property_subtype_id=parent.subtypes[0].id,
            management_mode=ManagementMode.UNITS,
            address_line_1="1 Private Road",
            locality="Bath",
            region="Somerset",
            postal_code="BA1 1AA",
            country_code="GB",
            latitude=Decimal("51.381072"),
            longitude=Decimal("-2.359910"),
            internal_notes="Alarm code 1234",
            description="Internal description",
        )
        row.amenities = [pool]
        db.add(row)
        await db.flush()
        db.add_all(
            [
                Unit(property_id=row.id, identifier="Flat 1"),
                Unit(property_id=row.id, identifier="Flat 2", archived_at=datetime.now(UTC)),
            ]
        )
        await db.commit()
        row_id = row.id
    manager = await actor_for(session_factory, "manager")
    async with session_factory() as db:
        await OwnershipService(db).add_owner(
            manager, row_id, OwnershipCreate(contact_id=contact_id, notes="Pays late")
        )
    async with session_factory() as db:
        links, summary = await OwnershipService(db).list_owners(manager, row_id)
        loaded = await PropertyRepository(db).get_detail(row_id)
        assert loaded is not None
        return loaded, owners_view(actor, links, summary)


async def test_detail_view_filters_by_permission(session_factory: Sessions) -> None:
    manager = await actor_for(session_factory, "manager")
    accountant = await actor_for(session_factory, "accountant")
    row, manager_owners = await load_detail(session_factory, manager)

    full = property_detail_view(manager, row, cover_media_id=None, owners=manager_owners)
    limited = property_detail_view(accountant, row, cover_media_id=None, owners=manager_owners)

    full_json = full.model_dump(mode="json")
    limited_json = limited.model_dump(mode="json")
    assert full_json["internal_notes"] == "Alarm code 1234"
    assert full_json["owners"]["items"][0]["contact"]["email"] == "olive@example.com"
    assert full_json["owners"]["items"][0]["notes"] == "Pays late"
    assert "internal_notes" not in limited_json and "owners" not in limited_json
    rendered = json.dumps(limited_json)
    for private in ("Alarm code", "olive@example.com", "Pays late"):
        assert private not in rendered
    # Active units only, with exact decimals serialized as strings.
    assert [unit["identifier"] for unit in full_json["units"]] == ["Flat 1"]
    assert full_json["latitude"] == "51.381072"
    assert full_json["amenities"][0]["name"] == "Pool"


async def test_owner_notes_and_contacts_follow_their_own_permissions(
    session_factory: Sessions,
) -> None:
    # Ownership read alone: names only, no contact details or notes.
    restricted = Actor(user_id=uuid.uuid4(), role_codes=frozenset(), active=True)
    _, owners = await load_detail(session_factory, restricted)

    item = owners.model_dump(mode="json")["items"][0]
    assert item["contact_display_name"] == "Olive Owner"
    assert "contact" not in item and "notes" not in item


async def test_summary_and_public_views(session_factory: Sessions) -> None:
    manager = await actor_for(session_factory, "manager")
    row, _ = await load_detail(session_factory, manager)

    summary = property_summary_view(row, unit_count=1, cover_media_id=None)
    public = PublicProperty.from_property(row).model_dump(mode="json")

    assert summary.property_type.name == "Residential"
    assert summary.property_subtype is not None and summary.unit_count == 1
    assert public["approximate_latitude"] == "51.381"
    assert public["approximate_longitude"] == "-2.360"
    assert public["amenities"] == ["Pool"]
    rendered = json.dumps(public)
    for private in ("1 Private Road", "BA1 1AA", "Alarm code", "Internal description", "PR-"):
        assert private not in rendered


# --- OpenAPI ----------------------------------------------------------------------------


def test_error_documentation_lists_every_catalog_code() -> None:
    grouped = codes_by_status()

    for code, spec in CATALOG_ERRORS.items():
        assert code.value in grouped[spec.status_code]
    responses = error_responses(404, 409, 422)
    assert set(responses) == {401, 403, 404, 409, 422}
    assert "`stale_version`" in str(responses[409]["description"])
    assert "`invalid_upload`" in str(responses[422]["description"])
    assert "`csrf_failed`" in str(responses[403]["description"])


def test_generated_openapi_describes_schemas_and_errors() -> None:
    probe = FastAPI()

    @probe.post("/properties", status_code=201, responses=error_responses(409, 422))
    def create(body: PropertyCreate) -> PropertyDetail:  # pragma: no cover
        raise NotImplementedError

    @probe.patch("/properties/{property_id}", responses=error_responses(404, 409, 422))
    def update(property_id: uuid.UUID, body: PropertyUpdate) -> PropertyDetail:  # pragma: no cover
        raise NotImplementedError

    @probe.get("/properties", responses=error_responses(422))
    def directory(
        query: Annotated[PropertyListQuery, Query()],
    ) -> list[PropertySummary]:  # pragma: no cover
        raise NotImplementedError

    spec = probe.openapi()
    components = spec["components"]["schemas"]
    for model in (PropertyCreate, PropertyUpdate):
        documented = set(components[model.__name__]["properties"])
        assert documented == set(model.model_fields)
    create_schema = components["PropertyCreate"]
    assert set(create_schema["required"]) == {
        "name",
        "property_type_id",
        "address_line_1",
        "locality",
        "region",
        "country_code",
    }
    assert create_schema["additionalProperties"] is False
    assert components["PropertyUpdate"]["required"] == ["version"]
    detail_key = next(name for name in components if name.startswith("PropertyDetail"))
    detail = components[detail_key]["properties"]
    assert set(detail) == set(PropertyDetail.model_fields)
    assert "property_ownership:read" in detail["owners"]["description"]
    assert "properties:read_internal" in detail["internal_notes"]["description"]
    operations = spec["paths"]["/properties/{property_id}"]["patch"]["responses"]
    assert {"401", "403", "404", "409", "422"} <= set(operations)
    parameters = {p["name"] for p in spec["paths"]["/properties"]["get"]["parameters"]}
    assert parameters == set(PropertyListQuery.model_fields)
