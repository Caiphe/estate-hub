# Prompt 02: Property Catalog

## Objective

Allow authorized staff to manage the reusable property and contact records on which listings and transactions depend.

## Scope

- Models and migrations for contacts, contact roles, property types, subtypes, amenities, properties, units, ownership, media metadata, and documents.
- UUID identifiers, UTC timestamps, archive/disable behavior, and audit fields.
- Administrator interfaces for configurable types, subtypes, and amenities.
- Staff CRUD, filtering, sorting, pagination, and detail views for contacts, properties, and units.
- Storage interface with local-volume implementation, secure upload validation, ordered images, and private-document authorization.
- Clear validation between whole properties and separately rentable/saleable units.

## Required rules

- Disabled reference data remains valid on existing records but cannot be selected for new assignments.
- Archiving records must not erase transaction history.
- A property may have multiple owners with explicit ownership shares when known.
- Public schemas must not expose owner details, private documents, or staff notes.

## Acceptance criteria

- Migrations upgrade and downgrade cleanly in the documented development path.
- Role permissions are tested for every modifying endpoint.
- Staff can create a multi-unit property and a standalone property from the UI.
- Media and document failure cases are tested.
- Playwright covers property type creation and property/unit creation.
- All earlier milestone checks still pass.
