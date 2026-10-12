"""Business rules shared by voice parsing, billing and order submission."""
from decimal import ROUND_CEILING, Decimal

from .units import fmt_qty

MAX_QUANTITY = Decimal("10000")


def msg(en, ta):
    return {"en": en, "ta": ta}


def validate_quantity(product, qty):
    """
    Check `qty` against the product's selling rules.
    Returns a list of {"en","ta"} messages; an empty list means valid.
    """
    problems = []
    unit_en = product.unit_label_en
    unit_ta = product.unit_label_ta
    name_en, name_ta = product.display_name_en, product.display_name_ta or product.display_name_en

    if qty is None:
        return [msg("Please enter a quantity.", "அளவை உள்ளிடவும்.")]
    if not isinstance(qty, Decimal):
        try:
            qty = Decimal(str(qty))
        except Exception:
            return [msg("That quantity is not a number.", "இது சரியான எண் அல்ல.")]
    if not qty.is_finite() or qty <= 0:
        return [msg("Please enter a quantity greater than zero.", "பூஜ்ஜியத்தை விட அதிகமான அளவை உள்ளிடவும்.")]
    if qty > MAX_QUANTITY:
        return [msg("That quantity is too large. Please call the shop for big orders.",
                    "அளவு மிகவும் அதிகம். பெரிய ஆர்டருக்கு கடையை அழைக்கவும்.")]
    if qty != qty.quantize(Decimal("0.001")):
        return [msg("Please use at most 3 decimal places.", "தசமத்தில் 3 இடங்கள் வரை மட்டும் பயன்படுத்தவும்.")]
    if qty < product.min_quantity:
        problems.append(msg(
            f"{name_en}: minimum order is {fmt_qty(product.min_quantity)} {unit_en}.",
            f"{name_ta}: குறைந்தபட்சம் {fmt_qty(product.min_quantity)} {unit_ta} வேண்டும்."))
    elif qty % product.quantity_step != 0:
        problems.append(msg(
            f"{name_en} is sold only in multiples of {fmt_qty(product.quantity_step)} {unit_en}.",
            f"{name_ta} {fmt_qty(product.quantity_step)} {unit_ta} மடங்குகளில் மட்டுமே கிடைக்கும்."))
    return problems


def nearest_valid_quantity(product, qty):
    """Smallest valid quantity >= qty (used only as a *suggestion* the customer must confirm)."""
    step = product.quantity_step
    base = max(Decimal(qty), product.min_quantity)
    steps = (base / step).to_integral_value(rounding=ROUND_CEILING)
    return (steps * step).quantize(Decimal("0.001"))


def unavailable_message(product):
    return msg(f"{product.display_name_en} is not available right now.",
               f"{product.display_name_ta or product.display_name_en} தற்போது கிடைக்கவில்லை.")


def product_payload(product):
    """JSON-safe description of a product for the browser. Prices are strings."""
    return {
        "id": product.pk,
        "name_en": product.display_name_en,
        "name_ta": product.display_name_ta,
        "unit": product.unit,
        "unit_en": product.unit_label_en,
        "unit_ta": product.unit_label_ta,
        "price": str(product.price),
        "min_quantity": fmt_qty(product.min_quantity),
        "step": fmt_qty(product.quantity_step),
        "available": product.is_orderable,
        "image": product.image.url if product.image else "",
    }
