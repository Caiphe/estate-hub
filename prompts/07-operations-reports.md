# Prompt 07: Expenses, Maintenance, Dashboards, and Reports

## Objective

Give staff the operational tools and reports required to manage active properties.

## Scope

- Expense category, expense, maintenance request, assignment, status history, attachment, and cost models and migrations.
- Maintenance intake, triage, assignment, scheduling, progress, resolution, cancellation, and cost recording.
- Expense entry, approval rules, evidence documents, filtering, and export.
- Dashboards and reports for occupancy, listing status, inquiries, viewings, sales, rent, income, expenses, maintenance, and expiring leases.
- Date/currency filters and CSV export through idempotent background jobs where appropriate.

Reports are operational and must not be represented as double-entry accounting statements.

## Acceptance criteria

- Private maintenance and financial data cannot appear on public endpoints.
- Report totals reconcile to source records in automated tests.
- Large exports run outside HTTP request processing and expose visible success/failure state.
- Role-specific dashboards avoid disclosing unauthorized financial information.
- Playwright covers maintenance lifecycle, expense recording, and a reconciled report.
- All earlier milestone checks still pass.
