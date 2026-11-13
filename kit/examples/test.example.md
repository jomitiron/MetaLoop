# B2 · Failed syncs and Retry now

Hint: Needs a second sandbox account for the currency case: `ledger.py needs` (do not pause).
Requires: webhooks

- **Page:** Settings › Integrations › Accounting › Failed syncs
- **Needs:** a connected sandbox account; an order whose invoice the accounting system will refuse once

## Steps
1. Make the invoice sync fail once (FILL IN how, without touching the database).
2. Open Failed syncs. Fix the cause. Press Retry now.

## App shows
- The row reads "Failed · {reason}" with the support reference under it.
- After Retry now the row leaves the list within a minute.

## Check in the third party
- The invoice exists once, with the order's total.

## Watch
- A retry that re-sends a stale payload (suspected; V3).
