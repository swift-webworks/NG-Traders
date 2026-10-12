# Importing products from the existing billing system

The existing billing software has **not been inspected yet** (software, file format and stock features are unknown).
The safe route is an **export file** (CSV or Excel). The site never connects to, reads or changes the billing database.

## How
Owner dashboard → **Import** → upload → read the preview → **Apply** (or Discard). Or on the server:
```bash
python manage.py import_products products.csv            # preview only
python manage.py import_products products.csv --apply    # write (take a backup first!)
```
Rows with errors are skipped and listed. Valid rows are applied in one transaction (all or nothing).
Re-importing the same file updates existing products (matched by `code`, else by name + pack) – it does not duplicate them.
Price changes made by an import are recorded in the price audit log.

## Columns (first row = header; extra columns are ignored; save CSV as **UTF-8** to keep Tamil)
| Column (alternatives accepted) | Required | Notes |
|---|---|---|
| `name` (item, product_name, english_name) | yes | English name |
| `price` (rate, selling_price) | yes | per **selling unit**, max 2 decimals |
| `unit` (uom) | yes | piece, packet, bottle, pack, kg, g, litre/l, ml |
| `code` (product_code, sku, id) | no | the billing system's code, used to match on re-import |
| `tamil_name` | no | |
| `category` | no | default "Uncategorised" |
| `pack` (pack_size) | no | text such as "250 g pack"; also tells apart products with the same name |
| `min_quantity` (min_qty) | no | default 1 (a warning is shown for measured units) |
| `step` (increment) | no | default 1. e.g. 6 = sold only in 6s; 0.5 = half-litre steps |
| `available` | no | yes/no. Blank keeps the current value (new products default to available) |
| `aliases` | no | other names, separated by `\|`, e.g. `seeni\|சீனி` |

**Stock quantities are not imported.** Until the stock source is verified, availability is the owner's yes/no switch.
See `deploy/sample_products.csv` for a format example (the prices there are fake).
