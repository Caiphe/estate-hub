# EstateHub Implementation Roadmap

This roadmap turns the approved EstateHub design into independently verifiable vertical milestones. Complete the milestones in order. A milestone is complete only when its migrations, API, interface, authorization, tests, and documentation satisfy its acceptance criteria.

## Milestone sequence

| No. | Milestone | User-visible outcome |
| --- | --- | --- |
| 00 | Project foundation | Docker starts the web, API, PostgreSQL, Redis, Celery worker, and scheduler with health checks |
| 01 | Authentication and access | Staff can sign in securely and access only the functions allowed by their role |
| 02 | Property catalog | Staff can manage contacts, configurable property types, properties, units, amenities, media, and documents |
| 03 | Listings and public website | Staff can publish listings; visitors can browse, filter, and view them |
| 04 | Inquiries and viewings | Visitors can inquire; staff can qualify leads, record activity, and schedule viewings |
| 05 | Offers and sales | Staff can manage offers and complete property sales |
| 06 | Leases, bookings, and payments | Staff can operate long-term rentals, student/commercial leases, holiday bookings, charges, and receipts |
| 07 | Maintenance, expenses, and reports | Staff can manage operations and view useful portfolio reports |
| 08 | Hardening and release | EstateHub passes security, recovery, performance, accessibility, and release-readiness checks |

## Cross-cutting completion rules

Every milestone must:

1. Keep route handlers thin and business rules in services.
2. Keep Pydantic transport schemas separate from SQLAlchemy models.
3. Change the database only through reviewed Alembic migrations.
4. Enforce authorization in the API.
5. Normalize errors and avoid exposing internal data.
6. Add Pytest/HTTPX coverage for backend behavior.
7. Add frontend tests and Playwright coverage for the milestone's primary workflow.
8. Pass formatting, linting, type checking, tests, and production builds.
9. Update the relevant documentation before being marked complete.

## Dependency order

```text
Foundation
  └── Authentication and RBAC
        └── Property catalog
              └── Listings and public website
                    └── Inquiries and viewings
                          ├── Offers and sales
                          └── Leases, bookings, and payments
                                └── Maintenance, expenses, and reports
                                      └── Hardening and release
```

Sales and rentals share contacts, properties, listings, inquiries, and viewings. They separate only after a customer proceeds toward a transaction.
