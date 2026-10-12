"""
Authoritative billing. The browser only ever sends (product_id, quantity);
every name, unit, price and total here is read from the database. All money is Decimal.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import List

from catalogue.models import Product
from catalogue.services import msg, unavailable_message, validate_quantity
from catalogue.units import fmt_qty

from .models import Order, ShopSettings

TWO_DP = Decimal("0.01")
MAX_LINES = 100


def money(value):
    return Decimal(value).quantize(TWO_DP, rounding=ROUND_HALF_UP)


@dataclass
class BillLine:
    product: Product
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    errors: List[dict] = field(default_factory=list)

    def as_dict(self, position):
        p = self.product
        return {
            "no": position, "product_id": p.pk, "name_en": p.display_name_en, "name_ta": p.display_name_ta,
            "unit_en": p.unit_label_en, "unit_ta": p.unit_label_ta, "quantity": fmt_qty(self.quantity),
            "unit_price": str(self.unit_price), "line_total": str(self.line_total),
            "step": fmt_qty(p.quantity_step), "min_quantity": fmt_qty(p.min_quantity),
            "errors": self.errors,
        }


@dataclass
class Bill:
    lines: List[BillLine]
    subtotal: Decimal
    delivery_charge: Decimal
    total: Decimal
    errors: List[dict]  # bill-level problems (empty cart, too many lines, ...)

    @property
    def ok(self):
        return not self.errors and bool(self.lines) and all(not l.errors for l in self.lines)

    def as_dict(self):
        return {
            "ok": self.ok,
            "lines": [l.as_dict(i) for i, l in enumerate(self.lines, 1)],
            "subtotal": str(self.subtotal), "delivery_charge": str(self.delivery_charge),
            "total": str(self.total), "errors": self.errors,
        }


def parse_requested_items(raw_items):
    """
    Clean the browser's cart: [{product_id, quantity}] -> ordered dict {product_id: Decimal}.
    Duplicate products are merged. Returns (items, errors).
    """
    errors, merged = [], {}
    if not isinstance(raw_items, list):
        return {}, [msg("Your bill could not be read. Please refresh the page.", "பில் படிக்க முடியவில்லை. பக்கத்தை புதுப்பிக்கவும்.")]
    for entry in raw_items[:MAX_LINES + 1]:
        try:
            pid = int(entry["product_id"])
            qty = Decimal(str(entry["quantity"]))
            if not qty.is_finite():
                raise ValueError
        except Exception:
            errors.append(msg("One of the items in your bill is not valid. Please remove it and add it again.",
                              "பில்லில் உள்ள ஒரு பொருள் சரியானது அல்ல. நீக்கிவிட்டு மீண்டும் சேர்க்கவும்."))
            continue
        merged[pid] = merged.get(pid, Decimal(0)) + qty
    if len(merged) > MAX_LINES:
        errors.append(msg(f"Too many items (maximum {MAX_LINES}).", f"அதிக பொருட்கள் (அதிகபட்சம் {MAX_LINES})."))
    return merged, errors


def build_bill(raw_items, fulfilment=Order.PICKUP, lock=False, shop=None):
    """
    Price a cart from the database. With lock=True (inside a transaction) the product rows are locked
    in a stable order so a concurrent price edit cannot slip in between pricing and saving.
    """
    shop = shop or ShopSettings.load()
    requested, errors = parse_requested_items(raw_items)
    if not requested and not errors:
        errors.append(msg("Your bill is empty. Please add at least one item.", "பில் காலியாக உள்ளது. குறைந்தது ஒரு பொருளைச் சேர்க்கவும்."))

    qs = Product.objects.filter(pk__in=list(requested)).select_related("category").order_by("pk")
    if lock:
        qs = qs.select_for_update(of=("self",))
    products = {p.pk: p for p in qs}

    lines, subtotal = [], Decimal("0.00")
    for pid, qty in requested.items():
        product = products.get(pid)
        if product is None:
            errors.append(msg("An item in your bill is no longer in our catalogue. Please remove it.",
                              "பில்லில் உள்ள ஒரு பொருள் இனி இல்லை. அதை நீக்கவும்."))
            continue
        line_errors = []
        if not product.is_orderable:
            line_errors.append(unavailable_message(product))
        line_errors.extend(validate_quantity(product, qty))
        total = money(product.price * qty) if not line_errors else Decimal("0.00")
        lines.append(BillLine(product=product, quantity=qty, unit_price=product.price,
                              line_total=total, errors=line_errors))
        subtotal += total

    delivery = money(shop.delivery_fee) if fulfilment == Order.DELIVERY else Decimal("0.00")
    return Bill(lines=lines, subtotal=money(subtotal), delivery_charge=delivery,
                total=money(subtotal + delivery), errors=errors)
