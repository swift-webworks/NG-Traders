# Manual test checklist (do this on real devices before launch)

Tick each item on every device. Use real phones: Android Chrome, an iPhone (Safari), a laptop (Chrome/Edge), a tablet.

## Voice and fallback
- [ ] Mic button visible and large; tap shows "Listening", then the words appear in the text box
- [ ] Tamil + English mode: say "ரெண்டு லக்ஸ் சோப்பு", "two Lux soap", "moonu milk biscuit venum"
- [ ] English-only mode works
- [ ] Say "half litre palm oil, two litres" → site **asks** which quantity (no guess)
- [ ] Deny microphone permission → clear message and typing still works
- [ ] Browser without speech support (e.g. Firefox) → message + typing works
- [ ] Switch network off while ordering → clear error, nothing lost; retry works
- [ ] Edit the recognised text then tap *Find my items*

## Review and bill
- [ ] Unknown product → "not found" + search box; unavailable product → clearly refused
- [ ] Two similar products (e.g. Lux vs Lux Rose) → customer chooses
- [ ] Pack rule product (e.g. sold in 6s): 4 is refused with a simple message and a suggestion
- [ ] +/− buttons, typing a quantity, Remove, Add more items by voice
- [ ] Bill totals match a calculator; price change in admin → new price at next bill refresh/order
- [ ] No sideways scrolling on a small phone; Tamil text renders correctly

## Order and payment
- [ ] Pickup + cash; Delivery (address required) + the payment methods the owner enabled
- [ ] Double-tap *Place order* → only **one** order
- [ ] Order page shows number, items, status; UPI page shows the right amount and UPI ID
- [ ] "I have paid" → shows *Awaiting verification* (never *Paid*)
- [ ] Order page link opened by someone else without the link → not found; Track order needs number **and** phone

## Owner
- [ ] Login; wrong password refused; Staff user cannot verify payments or edit prices
- [ ] New order alert appears within ~15 s; accept → prepare → ready/out → verify payment → complete
- [ ] Cannot complete an unpaid order; reject needs a reason
- [ ] Paid order rejected → red "refund needed" notice; stays *Paid* until the owner records the refund
- [ ] Edit price in Admin → price log entry; mark product unavailable → customers cannot order it
- [ ] Add alias in Admin → works immediately in voice
- [ ] Print preview on A4: no menus/buttons, correct totals, unpaid orders say payment not received

## Deployment
- [ ] HTTPS works, HTTP redirects; `check --deploy` reviewed; admin password strong
- [ ] Backup runs; **restore tested**; backup copied off the server
- [ ] Supervised pilot with the owner and a few customers before relying on it daily
