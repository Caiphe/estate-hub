# Prompt 08: Security Hardening and Release Readiness

## Objective

Prepare EstateHub for a controlled production release with evidence that security, recovery, accessibility, performance, and operations meet the design.

## Scope

- Threat-model review of authentication, authorization, uploads, public forms, cookies, CSRF, CORS, secrets, injection, and rate limiting.
- Consistent safe API errors, structured logs, request/task IDs, health/readiness, and error-monitoring integration boundary.
- PostgreSQL and media backup/restore procedures with a tested restoration record.
- Production images, non-root execution, dependency and container vulnerability review, and deployment migration procedure.
- Accessibility review for primary public and staff flows.
- Query/index review and representative public-search and dashboard performance checks.
- Complete CI pipeline and release checklist.
- Final documentation for local development, deployment, operations, and incident recovery.

## Acceptance criteria

- No known critical or high-severity issue remains without an explicit accepted-risk record.
- Backup restoration is performed successfully in a disposable environment.
- Primary Playwright workflows pass against a production build.
- Public discovery and critical staff workflows meet documented accessibility checks.
- Migration rollback/forward and failed-worker procedures are documented and exercised.
- CI runs every required quality gate from the design specification.
- The release checklist identifies environment ownership, secrets, backups, monitoring, and rollback responsibility.
