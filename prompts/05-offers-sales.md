# Prompt 05: Offers and Sales

## Objective

Track a qualified buyer from offer through an auditable completed property sale.

## Scope

- Offer, offer-status history, sale, sale milestone, commission, and sale-document models and migrations.
- Offer creation, revision/counteroffer, acceptance, rejection, withdrawal, and expiry.
- Sale workflow from accepted offer through agreement and completion.
- Validation for currency, fixed-precision amounts, dates, and listing availability.
- Staff pipeline, offer comparison, sale detail, milestones, and completion UI.
- Listing status updates driven by sale state without losing marketing history.

Do not implement conveyancing, escrow, online payments, or formal general-ledger accounting.

## Acceptance criteria

- Only valid offers can be accepted and only authorized roles can complete a sale.
- Concurrent attempts cannot complete contradictory deals for the same asset.
- Completed sales are corrected through explicit amendment/reversal behavior, not silent edits.
- Audit events capture financial and status changes.
- Playwright covers inquiry, viewing, offer, acceptance, and completion.
- All earlier milestone checks still pass.
