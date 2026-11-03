# EstateHub Design Specification

**Date:** 2026-11-03  
**Status:** Approved design, pending written-spec review  
**Product:** EstateHub  
**Audience:** Product owner, developers, testers, and deployment operators

## 1. Purpose

EstateHub is a property sales, lettings, and management platform for one property-management company. It combines a public property-discovery website with a protected staff workspace. It is not a multi-tenant SaaS product: all staff and managed properties belong to one organization.

The first release must let the company publish properties, receive and manage customer interest, complete sales and rental workflows, and operate active rentals. It must support residential, holiday, student, and commercial properties without requiring code changes whenever the company adds a new property subtype.

## 2. Goals and Success Criteria

EstateHub version 1 succeeds when:

1. An authorized staff member can create a property or unit, classify it, add media, create a listing, and publish it.
2. A visitor can find published listings through search and filters, view a complete listing, and submit an inquiry or viewing request.
3. Staff can follow an inquiry through contact, viewing, offer, and either a completed sale or an active rental arrangement.
4. Staff can manage long-term leases, student occupancy, commercial leases, and staff-managed holiday bookings.
5. Staff can record rent or booking payments, expenses, maintenance work, documents, and important dates.
6. Scheduled reminders and overdue checks run reliably through background workers.
7. Access to staff functions and private information is restricted by role and recorded in an audit trail.
8. Automated API and browser tests protect the primary workflows.

## 3. Scope

### 3.1 Public website

- Home and property-discovery pages.
- Published listing search, filtering, sorting, and pagination.
- Filters for transaction type, rental category, property type, location, price, bedrooms, bathrooms, and availability.
- SEO-friendly listing detail pages with images, description, amenities, pricing, and public location information.
- Inquiry and viewing-request forms.
- Responsive layouts for mobile, tablet, and desktop.

### 3.2 Staff workspace

- Staff authentication and role-based access.
- Staff user and role administration.
- Configurable property types, property subtypes, amenities, and other reference data.
- Properties, units, addresses, ownership contacts, media, and documents.
- Draft, review, publication, withdrawal, and archival of listings.
- Contacts acting as owners, sellers, buyers, tenants, or prospects.
- Inquiry, viewing, offer, sale, lease, and holiday-booking workflows.
- Rent or booking schedules and manual payment recording.
- Property expenses and maintenance requests.
- Notifications, reminders, audit history, and operational reports.

### 3.3 Reports

- Available, occupied, and unavailable properties or units.
- Active, draft, expired, withdrawn, and completed listings.
- Inquiry and viewing activity.
- Active leases and upcoming expirations.
- Expected, received, outstanding, and overdue rent.
- Recorded income and expenses by property and period.
- Sales pipeline and completed deals.

These are operational reports. Version 1 does not implement double-entry accounting, tax filing, or foreign-exchange accounting.

### 3.4 Explicitly deferred

- Separate owner and tenant self-service portals.
- Online card, bank, or mobile-money collection.
- Public self-service holiday booking and checkout.
- Live chat.
- External property-portal synchronization.
- Native mobile applications.
- Multi-company tenancy.
- Full general-ledger accounting.

## 4. Users and Authorization

The system has public visitors and four staff roles. Permissions are enforced by the API, never only by the user interface.

| Role | Primary responsibilities |
| --- | --- |
| Administrator | Full access, staff accounts, roles, reference data, and system configuration |
| Manager | Properties, listings, deals, rentals, maintenance, reports, and approvals |
| Agent | Assigned properties, listings, contacts, inquiries, viewings, offers, and deals |
| Accountant | Payment records, rent schedules, expenses, financial reports, and read-only property context |

The initial implementation uses role-based permissions while keeping the authorization layer capable of supporting finer-grained permissions later.

## 5. Property and Listing Classification

EstateHub separates the asset from the advertisement:

- A **property** is a physical building, parcel, or development.
- A **unit** is a separately managed space within a property, such as an apartment, office, shop, or student room.
- A **listing** advertises either one property or one unit.

Each listing contains:

- Transaction type: `sale` or `rent`.
- Rental category when the transaction type is `rent`: `residential`, `holiday`, `student`, or `commercial`.
- An administrator-managed property type and subtype, such as house, apartment, villa, office, shop, warehouse, or student room.
- Price, ISO 4217 currency, pricing period where applicable, availability, status, description, amenities, and media.

Property types and subtypes are data records rather than source-code enums. Administrators can create, reorder, disable, and reactivate them. Records already using a disabled type remain valid.

## 6. Core Domain Model

### 6.1 Identity and configuration

- `User`, `Role`, and role membership.
- `RefreshSession` for revocable refresh-token rotation.
- `PropertyType`, `PropertySubtype`, `Amenity`, and organization settings.
- `AuditEvent` for security-sensitive and important business actions.

### 6.2 Property catalog

- `Property` with reference number, name, description, address, coordinates, features, management status, and audit fields.
- `Unit` with unit identifier, floor, capacity, room counts, features, and occupancy status.
- `Contact` with contact details and one or more business roles.
- `PropertyOwnership`, allowing a property to have one or more owner contacts.
- `MediaAsset` and `Document`, stored outside PostgreSQL with metadata and access rules in PostgreSQL.

### 6.3 Marketing and customer relationship management

- `Listing`, attached to exactly one property or one unit.
- `ListingAmenity` and ordered listing media.
- `Inquiry` and `Viewing`, linked to a contact and listing.
- `Activity` and internal notes for follow-up history.
- `Offer`, including amount, currency, status, dates, and conditions.

### 6.4 Transactions and rentals

- `Sale` for accepted offers, agreement milestones, commission, and completion.
- `Lease` for residential, student, and commercial rental terms.
- `Booking` for staff-managed holiday reservations and blocked availability periods.
- `ChargeSchedule` for expected rent or booking charges.
- `Payment` for manually recorded receipts and allocation to expected charges.
- `Expense` for property-related operational costs.
- `MaintenanceRequest`, assignments, status changes, cost, and resolution.

All mutable business records use UUID primary keys, creation and update timestamps, and the responsible staff user where relevant. Monetary values use fixed-precision decimal columns and explicit currencies. Application timestamps are stored in UTC and displayed using the configured business timezone.

## 7. Primary Workflows

### 7.1 Publish a listing

1. Staff creates or selects a property and, when needed, a unit.
2. Staff supplies classification, features, ownership, location, media, and documents.
3. Staff creates a listing as a draft and supplies its commercial terms.
4. The API validates that required fields and publishable media are present.
5. Authorized staff publishes the listing.
6. The public website includes it in search and creates an indexable detail page.

### 7.2 Inquiry to transaction

1. A visitor submits an inquiry or viewing request for a published listing.
2. The API creates or safely matches a contact and creates the inquiry.
3. Staff assigns, qualifies, and follows up on the inquiry.
4. Staff schedules and records a viewing.
5. Staff records an offer or proceeds to rental terms.
6. A successful workflow creates a sale, lease, or holiday booking and updates listing availability.

### 7.3 Rental operation

1. Staff creates and activates a lease with occupants, dates, deposit, rent, frequency, and terms.
2. The system generates expected charges for the lease period.
3. Staff records payments and allocations; the system calculates balances rather than accepting a manually entered balance.
4. Scheduled jobs identify upcoming, due, and overdue charges and lease expirations.
5. Staff records expenses and maintenance against the applicable property or unit.
6. Lease termination or expiry releases the unit after the required checkout process.

Holiday lettings use bookings and availability periods instead of long-term leases. Version 1 bookings are created by staff after an inquiry; the public site does not take payment or confirm a booking automatically.

## 8. System Architecture

EstateHub uses a modular monolith in a single repository:

```text
property_management/
├── apis/                  # FastAPI application and Celery workers
├── web/                   # Next.js public site and staff workspace
├── docs/                  # Product and engineering documentation
├── prompts/               # Sequential implementation prompts
├── compose.yaml           # Local service orchestration
└── .env.example           # Documented, non-secret configuration template
```

### 8.1 Backend

The FastAPI application is divided into business modules with explicit public interfaces. Expected modules include:

- `auth`, `users`, and `audit`.
- `properties`, `catalog`, and `media`.
- `listings` and `public_search`.
- `contacts`, `inquiries`, and `viewings`.
- `sales`, `leases`, `bookings`, and `payments`.
- `expenses`, `maintenance`, `notifications`, and `reports`.
- `core` for configuration, database sessions, security primitives, errors, logging, and shared infrastructure.

Route handlers validate transport input and call application services. Business rules live in services and domain-focused modules. SQLAlchemy repositories handle persistence. Pydantic v2 schemas are not reused as SQLAlchemy models.

SQLAlchemy 2.x uses its modern typed mapping API. Alembic is the only supported mechanism for changing the PostgreSQL schema. Database migrations must be reviewed and exercised in tests before deployment.

### 8.2 Frontend

Next.js uses the App Router and TypeScript. Route groups separate public pages from the authenticated workspace while sharing the design system and typed API client.

Public listing pages are server-rendered where it benefits search indexing and initial load time. Interactive search filters and staff forms use client-side components only where needed. The staff workspace provides accessible forms, tables, filters, status indicators, and task-oriented dashboards.

The frontend treats API responses as untrusted external data and validates important response boundaries. It does not contain authoritative authorization or financial calculations.

### 8.3 Infrastructure

Docker Compose provides these local services:

- `api`: FastAPI HTTP application.
- `web`: Next.js application.
- `db`: PostgreSQL.
- `redis`: Celery broker, cache, rate-limit state, and temporary security state.
- `worker`: Celery workers.
- `beat`: scheduled Celery tasks.

Media files are not stored in PostgreSQL. Development uses a mounted local storage volume behind a storage interface. Production can replace it with S3-compatible object storage without changing domain logic.

## 9. API Design

- REST endpoints are versioned under `/api/v1`.
- FastAPI generates the OpenAPI contract and interactive API documentation.
- Collection endpoints use a common pagination response and consistent `filter`, `sort`, and search conventions.
- Public endpoints return only explicitly public schemas; they never serialize staff notes, ownership details, private documents, or internal financial data.
- Mutating endpoints enforce optimistic or status-based transition rules so stale requests cannot silently reverse completed workflows.
- Idempotency protection is applied where retries could duplicate inquiries, payments, bookings, or background jobs.

The standard error body is:

```json
{
  "error": {
    "code": "stable_machine_readable_code",
    "message": "A safe human-readable explanation",
    "fields": {},
    "request_id": "request-correlation-id"
  }
}
```

Pydantic validation errors are normalized to this format. Internal exceptions are logged with the request ID but do not expose stack traces or secrets to clients.

## 10. Authentication and Security

- OAuth2 password flow authenticates staff credentials.
- Passwords use Argon2id hashing through a maintained password-hashing library.
- JWT access tokens are short-lived.
- Refresh tokens are rotated, revocable, and represented by server-side session records.
- Browser token handling uses secure, HTTP-only cookies where applicable; cookie-authenticated state changes include CSRF protection.
- The API also supports standards-compliant bearer access tokens for OpenAPI and trusted API clients.
- Authorization checks apply at service boundaries as well as routes handling sensitive operations.
- Login, public form, and other abuse-prone endpoints are rate-limited using Redis.
- CORS uses an explicit environment-specific allowlist.
- File uploads are restricted by size and allowlisted content type, stored under generated names, and never executed.
- Secrets come from environment or secret-management systems and are never committed.
- Authentication events, publication, financial changes, permission changes, and transaction status changes create audit events.

## 11. Background Work

Celery handles work that should not hold an HTTP request open:

- Email notifications and reminders.
- Image resizing and derivative generation.
- Upcoming viewing, booking, payment, and lease reminders.
- Overdue-charge checks.
- Scheduled listing activation or expiry.
- Report exports and other long-running exports.

Tasks must be retry-safe and idempotent. Failures use bounded retries with backoff, structured logs, and visible terminal failure states. Celery Beat owns schedules; HTTP application instances do not run their own schedulers.

## 12. Validation and Business Rules

Pydantic v2 validates request shape and cross-field input constraints. Services enforce business rules that depend on stored state. Important rules include:

- A listing targets a property or a unit, never both and never neither.
- Rental categories are rejected for sale listings.
- Disabled property types cannot be assigned to new listings.
- Only listings meeting publication requirements can become public.
- Private, withdrawn, expired, or archived listings are absent from public results.
- Overlapping active leases or confirmed bookings for the same rentable space are rejected.
- Completed sales and posted payment records cannot be silently edited into a contradictory state; corrections use explicit reversal or amendment actions.
- Stored payment balances are derived from charges and allocations.

## 13. Testing Strategy

### 13.1 API and worker tests

- Pytest for unit, service, authorization, and integration tests.
- HTTPX with FastAPI's ASGI support for endpoint tests.
- A dedicated PostgreSQL test database so PostgreSQL behavior is tested directly.
- Migration tests that upgrade a clean database to the current schema.
- Celery eager mode for ordinary tests and targeted worker integration tests for task serialization and retry behavior.
- Factories and fixtures for users, properties, listings, contacts, and transactions.

### 13.2 Frontend and end-to-end tests

- Component and utility tests for important UI behavior and typed API integration.
- Playwright for browser workflows.
- Required Playwright coverage includes staff login, listing publication, public search and inquiry, viewing management, sale completion, lease activation, payment recording, and authorization boundaries.

### 13.3 Quality gates

Continuous integration must run formatting, linting, type checking, migration validation, API tests, frontend tests, production builds, and Playwright smoke tests. A change that fails a required gate is not releasable.

## 14. Observability and Operations

- Structured application and worker logs include request or task correlation IDs.
- Health endpoints distinguish process health from readiness for database and Redis traffic.
- Production errors are reportable to an error-monitoring service through a replaceable integration.
- PostgreSQL and media storage require documented backups and restoration tests.
- Deployment runs migrations as a controlled release step before new application instances receive traffic.

## 15. Delivery Sequence

EstateHub will be delivered in vertical milestones:

1. Repository, Docker, configuration, health checks, and development standards.
2. PostgreSQL foundation, SQLAlchemy, Alembic, authentication, roles, and audit events.
3. Property catalog, configurable types, units, contacts, media, and documents.
4. Listing lifecycle and public website search and detail pages.
5. Inquiries, viewings, activities, and notifications.
6. Offers and sales.
7. Leases, holiday bookings, charge schedules, and payment recording.
8. Expenses, maintenance, dashboards, and reports.
9. Security hardening, complete browser tests, deployment documentation, and release readiness.

Each milestone must include migrations, API behavior, user interface, permissions, tests, and documentation for the workflow it introduces. Prompt files will follow this sequence and must reference this specification as their source of truth.

## 16. Documentation Set

After approval of this specification, the project documentation will be expanded into focused guides:

- Product requirements and glossary.
- Architecture and repository conventions.
- Domain model and database conventions.
- API, validation, error, and pagination standards.
- Authentication and security model.
- Docker development environment and configuration.
- Testing strategy and commands.
- Delivery roadmap.
- Sequential implementation prompts with acceptance criteria and verification steps.

