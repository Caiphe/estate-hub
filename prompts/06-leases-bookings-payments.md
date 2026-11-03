# Prompt 06: Leases, Holiday Bookings, Charges, and Payments

## Objective

Operate residential, student, commercial, and holiday rentals while calculating balances from expected charges and payment allocations.

## Scope

- Lease, occupant, deposit, booking, availability block, charge schedule, charge, payment, and allocation models and migrations.
- Lease draft, activation, renewal, termination, expiry, and checkout.
- Staff-created holiday bookings with confirmation, cancellation, check-in, and checkout.
- Overlap prevention for active leases, confirmed bookings, and blocked dates.
- Recurring charge generation with explicit rounding and idempotency rules.
- Manual payment recording, allocation, receipt reference, reversal, and outstanding-balance calculation.
- Celery reminders for upcoming charges, overdue charges, bookings, and lease expirations.
- Rental dashboard and customer/property ledgers.

Do not add online payment collection or a tenant self-service portal.

## Acceptance criteria

- Monetary values use decimals and explicit ISO currencies.
- Stored balances are not directly editable; reports derive them from charges and allocations.
- Duplicate task execution cannot create duplicate charges or reminders.
- Confirmed occupancy periods cannot overlap for the same space.
- Reversals retain an audit trail.
- Playwright covers lease activation, charge generation, payment allocation, overdue state, and holiday booking.
- All earlier milestone checks still pass.
