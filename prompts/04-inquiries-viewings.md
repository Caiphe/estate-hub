# Prompt 04: Inquiries, Activities, and Viewings

## Objective

Convert public interest into an organized, auditable staff follow-up workflow.

## Scope

- Inquiry, assignment, activity, internal-note, and viewing models and migrations.
- Public inquiry and viewing-request forms protected by validation, throttling, and abuse controls.
- Safe contact matching that avoids accidental duplicates without merging unrelated people.
- Staff inbox with status, assignment, priority, filters, follow-up date, activity history, and notes.
- Viewing scheduling, rescheduling, cancellation, completion, outcome, and reminders.
- Celery notifications and reminders with idempotent delivery records.

## Acceptance criteria

- Public submissions expose no staff or contact data.
- Duplicate retries do not create repeated inquiries or notifications.
- Agents see and modify only records allowed by assignment policy; managers can reassign.
- Dates are stored in UTC and displayed in the configured business timezone.
- Notification failures retry safely and end in a visible terminal state.
- Playwright covers public inquiry through assigned and completed viewing.
- All earlier milestone checks still pass.
