"""Staff schemas for property ownership.

Owner contact details are personal data. ``OwnershipPublic.contact`` is filled only for
callers with ``contacts:read``; everyone else with ``property_ownership:read`` sees the
owner's display name and kind, never their email, telephone, or address.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

from app.auth.permissions import Permission
from app.auth.policy import Actor, has_permissions
from app.catalog.fields import (
    AddressLine,
    Area,
    Bathrooms,
    Count,
    CountryCode,
    IdSet,
    Latitude,
    Locality,
    Longitude,
    OptionalAddressLine,
    PostalCode,
    Region,
    label,
    required_label,
    text,
)
from app.catalog.schemas import AmenitySummary, PropertyTypeSummary, SubtypeSummary
from app.catalog.text import normalize_optional_text
from app.contacts.constants import ContactKind
from app.contacts.schemas import ContactSummary
from app.core.pagination import DEFAULT_PAGE_SIZE, PageLimit, PageOffset
from app.properties.constants import (
    FLOOR_LABEL_MAX_LENGTH,
    OWNERSHIP_NOTES_MAX_LENGTH,
    PROPERTY_DESCRIPTION_MAX_LENGTH,
    PROPERTY_NAME_MAX_LENGTH,
    PROPERTY_NOTES_MAX_LENGTH,
    UNIT_IDENTIFIER_MAX_LENGTH,
    UNIT_NAME_MAX_LENGTH,
    YEAR_BUILT_MAX,
    YEAR_BUILT_MIN,
    AreaUnit,
    FurnishedState,
    ManagementMode,
    PropertyStatus,
    UnitStatus,
)
from app.properties.models import Property, PropertyOwnership, Unit
from app.properties.shares import ShareSummary

SharePercentage = Annotated[
    Decimal,
    Field(gt=0, le=100, max_digits=5, decimal_places=2, description="Percent, such as 50.00."),
]
OwnershipNotes = Annotated[
    Annotated[str, Field(max_length=OWNERSHIP_NOTES_MAX_LENGTH)] | None,
    BeforeValidator(lambda v: normalize_optional_text(v) if isinstance(v, str) else v),
]

DATES_ORDERED = "end_date must be on or after start_date."


class OwnershipCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    contact_id: UUID
    share_percentage: SharePercentage | None = None
    start_date: date | None = None
    end_date: date | None = None
    notes: OwnershipNotes = None

    @model_validator(mode="after")
    def _dates_ordered(self) -> Self:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError(DATES_ORDERED)
        return self


class OwnershipUpdate(BaseModel):
    """Partial update. Omitted fields are unchanged; ``null`` clears a field. The contact
    cannot change: end this link and add another instead."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    share_percentage: SharePercentage | None = None
    start_date: date | None = None
    end_date: date | None = None
    notes: OwnershipNotes = None

    @model_validator(mode="after")
    def _has_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        return self

    def changes(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.model_fields_set}


class OwnershipPublic(BaseModel):
    id: UUID
    property_id: UUID
    contact_id: UUID
    contact_display_name: str
    contact_kind: ContactKind
    share_percentage: Decimal | None
    start_date: date | None
    end_date: date | None
    notes: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="Staff note; present only with properties:read_internal.",
    )
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    contact: ContactSummary | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="Owner contact details; present only with contacts:read.",
    )


class OwnerShares(BaseModel):
    """Shares in force today. ``complete`` is true only when every share is known and
    they total 100; unknown shares are never assumed."""

    known_total: Decimal
    unknown_count: int
    complete: bool


class PropertyOwners(BaseModel):
    """A page of links plus today's share summary, which always covers every current
    link whatever the page. Embedded in property detail, it holds all current links."""

    items: list[OwnershipPublic]
    total: int = Field(description="Links matching the filter, across all pages.")
    limit: int
    offset: int
    shares: OwnerShares


def ownership_view(actor: Actor, link: PropertyOwnership) -> OwnershipPublic:
    """Requires ``link.contact`` to be loaded."""
    contact = link.contact
    return OwnershipPublic(
        id=link.id,
        property_id=link.property_id,
        contact_id=link.contact_id,
        contact_display_name=contact.display_name,
        contact_kind=contact.kind,
        share_percentage=link.share_percentage,
        start_date=link.start_date,
        end_date=link.end_date,
        notes=link.notes if has_permissions(actor, Permission.PROPERTIES_READ_INTERNAL) else None,
        archived_at=link.archived_at,
        created_at=link.created_at,
        updated_at=link.updated_at,
        contact=(
            ContactSummary.model_validate(contact)
            if has_permissions(actor, Permission.CONTACTS_READ)
            else None
        ),
    )


def owners_view(
    actor: Actor,
    links: list[PropertyOwnership],
    summary: ShareSummary,
    *,
    total: int | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> PropertyOwners:
    """Without paging values the links are the complete current set."""
    return PropertyOwners(
        items=[ownership_view(actor, link) for link in links],
        total=len(links) if total is None else total,
        limit=len(links) if limit is None else limit,
        offset=offset,
        shares=OwnerShares(
            known_total=summary.known_total,
            unknown_count=summary.unknown_count,
            complete=summary.complete,
        ),
    )


# --- Physical facts, shared by property and unit schemas ---------------------------------


UnitIdentifier = Annotated[
    str, Field(min_length=1, max_length=UNIT_IDENTIFIER_MAX_LENGTH), BeforeValidator(required_label)
]
UnitName = Annotated[
    Annotated[str, Field(max_length=UNIT_NAME_MAX_LENGTH)] | None, BeforeValidator(label)
]
FloorLabel = Annotated[
    Annotated[str, Field(max_length=FLOOR_LABEL_MAX_LENGTH)] | None, BeforeValidator(label)
]
Description = Annotated[
    Annotated[str, Field(max_length=PROPERTY_DESCRIPTION_MAX_LENGTH)] | None,
    BeforeValidator(text),
]
InternalNotes = Annotated[
    Annotated[str, Field(max_length=PROPERTY_NOTES_MAX_LENGTH)] | None, BeforeValidator(text)
]
AmenityIds = IdSet
AREA_UNIT_REQUIRED = "area_unit is required exactly when floor_area is given."


class _UnitFields(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    name: UnitName = None
    floor_label: FloorLabel = None
    description: Description = None
    property_subtype_id: UUID | None = None
    bedrooms: Count | None = None
    bathrooms: Bathrooms | None = None
    capacity: Count | None = None
    floor_area: Area | None = None
    area_unit: AreaUnit | None = None
    furnished_state: FurnishedState | None = None
    status: UnitStatus | None = None
    internal_notes: InternalNotes = None


class UnitCreate(_UnitFields):
    identifier: UnitIdentifier
    amenity_ids: AmenityIds = Field(default_factory=list)

    @model_validator(mode="after")
    def _area_has_unit(self) -> Self:
        if (self.floor_area is None) != (self.area_unit is None):
            raise ValueError(AREA_UNIT_REQUIRED)
        return self


class UnitUpdate(_UnitFields):
    """Partial update. Omitted fields are unchanged; ``null`` clears a field.
    ``amenity_ids`` replaces the whole set. ``version`` must match the stored unit."""

    version: int = Field(ge=1)
    identifier: UnitIdentifier | None = None
    amenity_ids: AmenityIds | None = None

    @model_validator(mode="after")
    def _has_changes(self) -> Self:
        if not self.model_fields_set - {"version"}:
            raise ValueError("At least one field must be provided.")
        for name in ("identifier", "amenity_ids", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null.")
        return self

    def changes(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.model_fields_set - {"version"}}


class UnitSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    property_id: UUID
    identifier: str
    name: str | None
    floor_label: str | None
    property_subtype: SubtypeSummary | None
    bedrooms: int | None
    bathrooms: Decimal | None
    capacity: int | None
    status: UnitStatus
    archived_at: datetime | None
    updated_at: datetime


class UnitDetail(UnitSummary):
    description: str | None
    floor_area: Decimal | None
    area_unit: AreaUnit | None
    furnished_state: FurnishedState | None
    amenities: list[AmenitySummary]
    created_at: datetime
    version: int
    internal_notes: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="Staff note; present only with properties:read_internal.",
    )


def unit_view(actor: Actor, unit: Unit) -> UnitDetail:
    """Requires the unit's subtype and amenities to be loaded."""
    detail = UnitDetail.model_validate(unit)
    if not has_permissions(actor, Permission.PROPERTIES_READ_INTERNAL):
        detail.internal_notes = None
    return detail


# --- Properties --------------------------------------------------------------------------

PropertyName = Annotated[
    str, Field(min_length=1, max_length=PROPERTY_NAME_MAX_LENGTH), BeforeValidator(required_label)
]
YearBuilt = Annotated[int, Field(ge=YEAR_BUILT_MIN, le=YEAR_BUILT_MAX)]
COORDINATES_PAIRED = "latitude and longitude must be given together."
AREA_UNIT_FOR_AREAS = "area_unit is required exactly when land_area or floor_area is given."
ARCHIVE_THROUGH_DELETE = "Archive a property with DELETE, not by setting its status."
UNITS_NEED_MODE = "Units require management_mode units or mixed."
MAX_INITIAL_OWNERS = 50
MAX_INITIAL_UNITS = 200


def _not_archived(status: PropertyStatus) -> PropertyStatus:
    if status == PropertyStatus.ARCHIVED:
        raise ValueError(ARCHIVE_THROUGH_DELETE)
    return status


EditableStatus = Annotated[PropertyStatus, AfterValidator(_not_archived)]


class _PropertyFields(BaseModel):
    """Optional asset fields shared by create and update."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    description: Description = None
    property_subtype_id: UUID | None = None
    address_line_2: OptionalAddressLine = None
    postal_code: PostalCode = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    year_built: YearBuilt | None = None
    bedrooms: Count | None = None
    bathrooms: Bathrooms | None = None
    floors: Count | None = None
    parking_spaces: Count | None = None
    furnished_state: FurnishedState | None = None
    land_area: Area | None = None
    floor_area: Area | None = None
    area_unit: AreaUnit | None = None
    internal_notes: InternalNotes = None


def property_rule_errors(values: _PropertyFields | Property) -> dict[str, list[str]]:
    """Cross-field rules that need no database. Services re-run them on the merged record
    after a partial update."""
    errors: dict[str, list[str]] = {}
    if (values.latitude is None) != (values.longitude is None):
        errors["latitude"] = [COORDINATES_PAIRED]
    has_area = values.land_area is not None or values.floor_area is not None
    if has_area != (values.area_unit is not None):
        errors["area_unit"] = [AREA_UNIT_FOR_AREAS]
    return errors


def _raise_rule_errors(errors: dict[str, list[str]]) -> None:
    if errors:
        raise ValueError(" ".join(m for messages in errors.values() for m in messages))


class PropertyCreate(_PropertyFields):
    """A complete base property, optionally with amenities, owners, and units created in
    the same transaction. Reference, status history, staff IDs, and version are set by
    the server."""

    name: PropertyName
    property_type_id: UUID
    status: EditableStatus = PropertyStatus.DRAFT
    management_mode: ManagementMode = ManagementMode.WHOLE
    address_line_1: AddressLine
    locality: Locality
    region: Region
    country_code: CountryCode
    amenity_ids: AmenityIds = Field(default_factory=list)
    owners: list[OwnershipCreate] = Field(default_factory=list, max_length=MAX_INITIAL_OWNERS)
    units: list[UnitCreate] = Field(default_factory=list, max_length=MAX_INITIAL_UNITS)

    @model_validator(mode="after")
    def _rules(self) -> Self:
        errors = property_rule_errors(self)
        contacts = [owner.contact_id for owner in self.owners]
        if len(set(contacts)) != len(contacts):
            errors["owners"] = ["A contact can appear only once."]
        identifiers = [unit.identifier.lower() for unit in self.units]
        if len(set(identifiers)) != len(identifiers):
            errors["units"] = ["Unit identifiers must be unique, ignoring case."]
        if self.units and self.management_mode == ManagementMode.WHOLE:
            errors.setdefault("units", []).append(UNITS_NEED_MODE)
        _raise_rule_errors(errors)
        return self


class PropertyUpdate(_PropertyFields):
    """Partial update. Omitted fields are unchanged; ``null`` clears an optional field.

    ``version`` must match the stored property (``stale_version`` otherwise).
    ``amenity_ids`` replaces the whole set. Owners and units change through their own
    endpoints, and archival through ``DELETE``. Cross-field rules are checked here when
    both fields are supplied, and by the service against the merged record.
    """

    version: int = Field(ge=1)
    name: PropertyName | None = None
    property_type_id: UUID | None = None
    status: EditableStatus | None = None
    management_mode: ManagementMode | None = None
    address_line_1: AddressLine | None = None
    locality: Locality | None = None
    region: Region | None = None
    country_code: CountryCode | None = None
    amenity_ids: AmenityIds | None = None

    _REQUIRED = (
        "name",
        "property_type_id",
        "status",
        "management_mode",
        "address_line_1",
        "locality",
        "region",
        "country_code",
        "amenity_ids",
    )

    @model_validator(mode="after")
    def _rules(self) -> Self:
        supplied = self.model_fields_set - {"version"}
        if not supplied:
            raise ValueError("At least one field must be provided.")
        for name in self._REQUIRED:
            if name in supplied and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null.")
        # Only a pair supplied together can be judged here; the service re-runs
        # property_rule_errors on the merged record, which covers the area rule too.
        if {"latitude", "longitude"} <= supplied and (self.latitude is None) != (
            self.longitude is None
        ):
            raise ValueError(COORDINATES_PAIRED)
        return self

    def changes(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.model_fields_set - {"version"}}


class PropertySort(StrEnum):
    CREATED_AT = "created_at"
    CREATED_AT_DESC = "-created_at"
    UPDATED_AT = "updated_at"
    UPDATED_AT_DESC = "-updated_at"
    REFERENCE = "reference"
    REFERENCE_DESC = "-reference"
    NAME = "name"
    NAME_DESC = "-name"
    LOCALITY = "locality"
    LOCALITY_DESC = "-locality"


class PropertyListQuery(BaseModel):
    """Filters, ordering, and paging for the property directory.

    Multi-select filters use repeated parameters (``?status=active&status=draft``) and
    match any listed value; ``amenity_id`` matches properties having every listed
    amenity. Unknown parameters and sort keys are rejected, never ignored. The property
    ID breaks sort ties, so pages never overlap.
    """

    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Case-insensitive search in reference, name, locality, region, and "
        "owner name (owner name only with property_ownership:read).",
    )
    status: list[PropertyStatus] = Field(default_factory=list, max_length=4)
    property_type_id: list[UUID] = Field(default_factory=list, max_length=50)
    property_subtype_id: list[UUID] = Field(default_factory=list, max_length=50)
    amenity_id: list[UUID] = Field(default_factory=list, max_length=20)
    management_mode: list[ManagementMode] = Field(default_factory=list, max_length=3)
    locality: Annotated[str, BeforeValidator(label), Field(max_length=100)] | None = None
    region: Annotated[str, BeforeValidator(label), Field(max_length=100)] | None = None
    country_code: CountryCode | None = None
    include_archived: bool = Field(
        default=False,
        description="Include archived properties (requires properties:archive).",
    )
    sort: PropertySort = PropertySort.UPDATED_AT_DESC
    limit: PageLimit = DEFAULT_PAGE_SIZE
    offset: PageOffset = 0

    @model_validator(mode="after")
    def _archived_needs_inclusion(self) -> Self:
        if PropertyStatus.ARCHIVED in self.status and not self.include_archived:
            raise ValueError("Set include_archived=true to filter archived properties.")
        return self


class PropertySummary(BaseModel):
    """A directory row. No address lines, notes, owners, or files."""

    id: UUID
    reference: str
    name: str
    property_type: PropertyTypeSummary
    property_subtype: SubtypeSummary | None
    status: PropertyStatus
    management_mode: ManagementMode
    locality: str
    region: str
    country_code: str
    unit_count: int = Field(description="Active units.")
    cover_media_id: UUID | None = Field(description="The cover image, if any.")
    updated_at: datetime


class PropertyDetail(BaseModel):
    """The staff record. Sections the caller may not see are omitted, not nulled:
    ``internal_notes`` needs properties:read_internal, ``owners`` property_ownership:read.
    Private documents and storage keys are never part of this shape."""

    id: UUID
    reference: str
    name: str
    description: str | None
    property_type: PropertyTypeSummary
    property_subtype: SubtypeSummary | None
    status: PropertyStatus
    management_mode: ManagementMode
    address_line_1: str
    address_line_2: str | None
    locality: str
    region: str
    postal_code: str | None
    country_code: str
    latitude: Decimal | None
    longitude: Decimal | None
    year_built: int | None
    bedrooms: int | None
    bathrooms: Decimal | None
    floors: int | None
    parking_spaces: int | None
    furnished_state: FurnishedState | None
    land_area: Decimal | None
    floor_area: Decimal | None
    area_unit: AreaUnit | None
    amenities: list[AmenitySummary]
    units: list[UnitSummary]
    cover_media_id: UUID | None
    created_by_id: UUID | None
    updated_by_id: UUID | None
    archived_at: datetime | None
    archived_by_id: UUID | None
    created_at: datetime
    updated_at: datetime
    version: int
    internal_notes: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="Present only with properties:read_internal.",
    )
    owners: PropertyOwners | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="Present only with property_ownership:read.",
    )


def property_summary_view(
    row: Property, *, unit_count: int, cover_media_id: UUID | None
) -> PropertySummary:
    """Requires ``property_type`` and ``property_subtype`` to be loaded."""
    return PropertySummary(
        id=row.id,
        reference=row.reference,
        name=row.name,
        property_type=PropertyTypeSummary.model_validate(row.property_type),
        property_subtype=(
            SubtypeSummary.model_validate(row.property_subtype) if row.property_subtype else None
        ),
        status=row.status,
        management_mode=row.management_mode,
        locality=row.locality,
        region=row.region,
        country_code=row.country_code,
        unit_count=unit_count,
        cover_media_id=cover_media_id,
        updated_at=row.updated_at,
    )


def property_detail_view(
    actor: Actor,
    row: Property,
    *,
    cover_media_id: UUID | None,
    owners: PropertyOwners | None,
) -> PropertyDetail:
    """Requires the detail load plan (``PropertyRepository.get_detail``), which loads
    only active units (capped); archived units are paged under ``/units``."""
    units = row.units
    can_read_internal = has_permissions(actor, Permission.PROPERTIES_READ_INTERNAL)
    can_read_owners = has_permissions(actor, Permission.PROPERTY_OWNERSHIP_READ)
    fields = {name: getattr(row, name) for name in _DETAIL_COLUMNS}
    return PropertyDetail(
        **fields,
        property_type=PropertyTypeSummary.model_validate(row.property_type),
        property_subtype=(
            SubtypeSummary.model_validate(row.property_subtype) if row.property_subtype else None
        ),
        amenities=[AmenitySummary.model_validate(a) for a in row.amenities],
        units=[UnitSummary.model_validate(unit) for unit in units],
        cover_media_id=cover_media_id,
        internal_notes=row.internal_notes if can_read_internal else None,
        owners=owners if can_read_owners else None,
    )


_DETAIL_COLUMNS = tuple(
    name
    for name in PropertyDetail.model_fields
    if name
    not in {
        "property_type",
        "property_subtype",
        "amenities",
        "units",
        "cover_media_id",
        "internal_notes",
        "owners",
    }
)

PUBLIC_COORDINATE_PLACES = 3


class PublicProperty(BaseModel):
    """Future-safe public shape (prompt 03 decides when to publish it).

    Only physical facts and coarse location: no reference, address lines, postal code,
    internal description, notes, owners, documents, staff IDs, or versions. Coordinates
    are rounded to three decimal places (about 100 m).
    """

    name: str
    property_type: str
    property_subtype: str | None
    locality: str
    region: str
    country_code: str
    approximate_latitude: Decimal | None
    approximate_longitude: Decimal | None
    year_built: int | None
    bedrooms: int | None
    bathrooms: Decimal | None
    floors: int | None
    parking_spaces: int | None
    furnished_state: FurnishedState | None
    land_area: Decimal | None
    floor_area: Decimal | None
    area_unit: AreaUnit | None
    amenities: list[str]

    @classmethod
    def from_property(cls, row: Property) -> PublicProperty:
        """Requires classification and amenities to be loaded. Disabled amenities and
        classifications are still named: they describe the asset as recorded."""
        places = Decimal(1).scaleb(-PUBLIC_COORDINATE_PLACES)
        return cls(
            name=row.name,
            property_type=row.property_type.name,
            property_subtype=row.property_subtype.name if row.property_subtype else None,
            locality=row.locality,
            region=row.region,
            country_code=row.country_code,
            approximate_latitude=row.latitude.quantize(places) if row.latitude else None,
            approximate_longitude=row.longitude.quantize(places) if row.longitude else None,
            year_built=row.year_built,
            bedrooms=row.bedrooms,
            bathrooms=row.bathrooms,
            floors=row.floors,
            parking_spaces=row.parking_spaces,
            furnished_state=row.furnished_state,
            land_area=row.land_area,
            floor_area=row.floor_area,
            area_unit=row.area_unit,
            amenities=[amenity.name for amenity in row.amenities],
        )


class ArchivedQuery(BaseModel):
    """Paging and ``include_archived`` for unit, image, document, and owner lists.

    ``limit`` is at most 100, so a parent's whole active gallery (capped at 100) fits in
    one page."""

    model_config = ConfigDict(extra="forbid")

    include_archived: bool = False
    limit: PageLimit = DEFAULT_PAGE_SIZE
    offset: PageOffset = 0
