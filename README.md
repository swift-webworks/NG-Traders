# NG Traders — Tamil/English Voice-Ordering & Billing

Project owner: Swift Web Works · Client: NG Traders (8610527033, 6369603873)

Customers speak (or type) their order in Tamil, English or a mix; the server finds the products,
checks the selling rules, prices the bill, and the owner manages orders from a dashboard.

## Run it on your computer (5 minutes)

```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py setup_roles                            # creates Owner and Staff groups
python manage.py createsuperuser                        # the shop owner's login
python manage.py seed_demo                              # OPTIONAL: fake demo products (placeholder prices!)
python manage.py runserver
```

* Customer site: http://127.0.0.1:8000/
* Owner dashboard: http://127.0.0.1:8000/owner/ (log in; add the user to the **Owner** group in `/admin/` → Users, or just use the superuser)
* Django Admin (products, prices, aliases, shop settings): http://127.0.0.1:8000/admin/

Voice recognition needs a secure page: `localhost` works; on a phone you need HTTPS (see DEPLOYMENT.md).
Remove demo data with `python manage.py seed_demo --remove`.

## What is where

| Folder | Purpose |
|---|---|
| `catalogue/` | Products, categories, aliases, price audit log, units, text normalising, CSV/Excel import |
| `voice/` | `numbers.py` (number/unit words), `parser.py` (sentence → items), `matcher.py` (confidence matching), `service.py` (links to catalogue), JSON endpoints |
| `orders/` | `billing.py` (authoritative prices, Decimal), `services.py` (create order, status, payments), customer pages, owner dashboard, print bill |
| `templates/`, `static/` | Brand-styled UI (Bootstrap 5 served locally, no CDN), `static/js/app.js` ordering page |
| `deploy/` | Gunicorn service, Nginx config, backup script, sample CSV |
| `docs/` | Deployment, import format, manual test checklist, open questions, test report |

## Key design rules (billing correctness first)

* The browser sends only product IDs and quantities. **Every name, price and total is recalculated on the server** from the database, inside a transaction, when the order is placed.
* Money is `Decimal` everywhere. Order lines store a **snapshot** of name/unit/price, so later price edits never change old bills.
* Double taps and retries use an **idempotency key** → one order only.
* Speech only becomes text in the browser. Matching is confidence-based: unsure matches are shown to the customer, **never silently added**. Conflicting quantities ("half litre palm oil, two litres") ask the customer.
* A measure is never converted into a count (2 kg ≠ 2 soaps). Only kg↔g and litre↔ml convert.
* Payment status is separate from order status. UPI "I have paid" only sets *Awaiting verification*; only the owner marks *Paid*. Refunds are recorded only when the owner confirms the money was returned.
* Customer order pages need a long secret link (or order number + phone). Order numbers alone give no access.

## Owner setup checklist (before going live)

1. `/admin/` → **Shop settings**: confirm address, delivery fee, UPI ID (then tick *Enable UPI*), whether cash on delivery is allowed.
2. Import or enter real products and prices (DEMO products must be removed).
3. Add Tamil names and aliases for products (`Products` → each product → *Aliases*). Add the words customers really say.
4. Create staff users (tick *Staff status*, add to **Staff** group: can handle orders but not verify payments or change prices).
5. Run a supervised pilot with a few customers (see `docs/TEST_CHECKLIST.md`).

## Tests

```bash
python manage.py test        # 145 automated tests
```
See `docs/TEST_REPORT.md` for exactly what was run and what still needs real-device checking.
