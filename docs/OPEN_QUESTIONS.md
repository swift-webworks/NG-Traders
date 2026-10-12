# Open questions for the owner / decisions made safely in the meantime

| # | Unknown | What the system does until answered |
|---|---|---|
| 1 | Billing software, file format, stock features | Import from a CSV/Excel export only. Stock not imported or promised. Please send a sample export. |
| 2 | Shop UPI ID / QR | UPI is **off**. Enter the ID in Admin → Shop settings and tick Enable UPI. |
| 3 | Is cash on delivery allowed? | **Off**. Tick in Shop settings if allowed. |
| 4 | Delivery fee and delivery area | Fee is ₹0 (free). No area limit is enforced. Set the fee in Shop settings. |
| 5 | Shop address (for bills) | Blank (not printed). |
| 6 | Real products, prices, Tamil names | None loaded. `seed_demo` data is fake and development-only. |
| 7 | Which products are sold in packs (6/12/24) | Set *Minimum quantity* and *Quantity increment* per product. |
| 8 | Printer type (A4 or thermal) | A4 print layout provided. Thermal can be added once the model/paper width is known. |
| 9 | Opening hours / order cut-off | Not enforced. Orders are accepted any time. |
| 10 | Domain name and VPS details | Placeholders in `deploy/`. |
| 11 | Real spoken phrases and local product names | Aliases are added by the owner; send recordings/phrases from real customers during the pilot so number/unit words and aliases can be extended (`voice/numbers.py`). |

## Known limitations (be honest with the client)
* Speech recognition quality (especially Tamil and mixed Tamil-English) depends on the phone's browser. Chrome on Android is the best option; iPhone/Safari and Firefox are limited. The typed fallback always works.
* Tamil number words/units and aliases cover common forms only; unusual accents/words will go to the "please confirm" screen rather than being guessed.
* No stock tracking or reservation (stock source unknown). Availability is a manual switch.
* No SMS/WhatsApp notification; the dashboard polls every 15 seconds and shows an alert while it is open.
* UPI is manual verification (no payment gateway).
* Rate limits are per server worker (see DEPLOYMENT.md).
* No customer accounts: customers track orders via their secret link or order number + phone.
