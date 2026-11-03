# Prompt 03: Listings and Public Website

## Objective

Let staff create and publish valid property listings and let visitors discover them through a fast, indexable public website.

## Scope

- Listing models, amenities, ordered media, status history, availability, prices, currency, and pricing period.
- Transaction types `sale` and `rent`; rental categories `residential`, `holiday`, `student`, and `commercial`.
- Listing target constraint: exactly one property or unit.
- Draft, review, publish, withdraw, expire, complete, and archive transitions.
- Publication validation and public/private response schemas.
- Public paginated search, filters, sorting, listing detail, SEO metadata, sitemap behavior, and empty/error states.
- Staff listing editor, preview, status actions, and listing table.
- Celery image derivatives and scheduled activation/expiry where configured.

## Acceptance criteria

- Invalid status transitions and incomplete publication attempts are rejected.
- Only published, currently available listings appear publicly.
- Public endpoints never expose private catalog or workflow data.
- Search filters compose correctly and use appropriate PostgreSQL indexes.
- Public listing pages are server-rendered and have canonical metadata.
- Playwright covers draft creation, publication, public discovery, withdrawal, and authorization.
- All earlier milestone checks still pass.
