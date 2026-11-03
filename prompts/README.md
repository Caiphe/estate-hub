# EstateHub Sequential Prompts

These prompts guide implementation one verified milestone at a time. The approved design specification at `docs/superpowers/specs/2026-11-03-estatehub-design.md` is the source of truth.

## How to use the prompts

1. Start with the lowest-numbered incomplete prompt.
2. Give the complete prompt file to the coding assistant working in this repository.
3. Do not combine prompts or begin the next prompt while acceptance criteria remain unmet.
4. Review migrations and security-sensitive changes before accepting a milestone.
5. Commit the completed milestone before moving forward.

## Execution contract

The implementer must:

- Inspect the existing code and documentation before editing.
- Preserve unrelated user changes.
- State assumptions that materially affect product behavior.
- Implement only the current milestone and avoid speculative abstractions.
- Add tests alongside behavior, including failure and authorization cases.
- Run the milestone's verification commands and report exact results.
- Update documentation when commands, environment variables, endpoints, or workflows change.
- Never declare completion while required checks are failing.

## Prompt order

1. [`00-project-foundation.md`](./00-project-foundation.md)
2. [`01-authentication-rbac.md`](./01-authentication-rbac.md)
3. [`02-property-catalog.md`](./02-property-catalog.md)
4. [`03-listings-public-site.md`](./03-listings-public-site.md)
5. [`04-inquiries-viewings.md`](./04-inquiries-viewings.md)
6. [`05-offers-sales.md`](./05-offers-sales.md)
7. [`06-leases-bookings-payments.md`](./06-leases-bookings-payments.md)
8. [`07-operations-reports.md`](./07-operations-reports.md)
9. [`08-hardening-release.md`](./08-hardening-release.md)
