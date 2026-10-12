# Test report (development environment, 12 Oct 2026)

Environment: Python 3.13, Django 5.2, SQLite, headless Chromium (Playwright). **PostgreSQL, Gunicorn, Nginx, HTTPS and real phones were NOT available and were NOT tested.**

## Executed and passing
* `python manage.py test` → **145 tests, all passing**:
  * Parsing / numbers / units: English, Tamil script and Tamil-in-English-letters numbers, half/quarter/one-and-a-half, 500 ml, 1 kg, conflicting quantities, missing quantity, multiple products, "salt and pepper" not split.
  * Matching: exact English/Tamil, alias, plural, similar names (Lux vs Lux Rose) → ambiguous, unknown product, typo never "confident", empty catalogue, new alias effective immediately.
  * Selling rules: minimum, increments (6/12), fractional steps, unit mismatch, measure never converted to a count.
  * Billing: line totals, subtotal, delivery fee, rounding, no float errors, price change after cart creation, browser-supplied prices ignored.
  * Orders: success, failure rollback, duplicate/retry (including a simulated race), validation, historical bills after price/name change, product deletion.
  * Payments/status: allowed/blocked transitions, UPI claim ≠ paid, owner verification, cash collection, reject needs reason, refund only by owner after paid rejection, cannot complete unpaid order.
  * Security: anonymous/customer/staff/owner access, CSRF on API and owner forms, order access only by secret token or number+phone, phone masking, rate limiting, order-view-only in Django Admin.
  * Import: preview writes nothing, error rows skipped, re-import updates not duplicates, rollback on failure, CSV/XLSX, command, web confirmation.
* `manage.py check`, `makemigrations --check` → clean. `check --deploy` with production-style env → only two optional HSTS notes (intentional).
* Browser end-to-end (headless Chromium, 28 checks, all passing): phone layout without horizontal scroll; Tamil+English sentence → 4 review cards → bill → total ₹215.00 from the server; quantity +/remove recalculation; conflict asks and does not guess; delivery + UPI checkout; confirmation page; "I have paid" → awaiting verification; owner login, verify payment, accept; print page and print CSS (A4 PDF generated); customer page reflects owner changes; desktop layout; voice code path with a *mocked* recogniser; microphone-denied message.
* The browser run found and fixed two real bugs that unit tests missed (config double-encoding, and a `no-referrer` tag breaking the CSRF check). Regression tests were added for both.

## NOT verified (must be checked by a person)
* Real speech recognition quality in Tamil / mixed language on real Android and iPhone devices (only a mocked recogniser was used).
* Visual check on tablets and large monitors, and real A4 printer output (a PDF was generated, not printed).
* Concurrency on PostgreSQL under real parallel load (row locking is used; the race was simulated on SQLite).
* Production deployment, HTTPS, backups and restore.
* Import from the shop's actual billing export (format unknown).

Run a supervised pilot before relying on the system for daily billing.
