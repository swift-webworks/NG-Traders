"""
Glue between the pure parser/matcher and the real catalogue.

`interpret(text)` turns a sentence into reviewable items. Every item has a
`status`; only status "ok" can be added to the bill without further customer input.

    ok                 product + quantity understood and valid
    needs_quantity     product found, no quantity heard
    needs_unit         number heard without a unit for a measured product ("2 palm oil")
    unit_mismatch      spoken unit does not fit the product's selling unit
    conflict           more than one different quantity heard
    invalid_rules      quantity breaks min / increment rule (a valid suggestion is offered)
    ambiguous_product  several possible products
    unknown_product    nothing similar found
    unavailable        product exists but is not currently available
"""
from decimal import Decimal

from django.db.models import Count, Max

from catalogue import units as U
from catalogue.models import Category, Product, ProductAlias
from catalogue.services import (msg, nearest_valid_quantity, product_payload, unavailable_message,
                                validate_quantity)
from catalogue.units import fmt_qty

from .matcher import build_entries, match_product
from .parser import QuantityCandidate, parse_order_text

MAX_TEXT_LENGTH = 1000
MAX_ITEMS = 30

_index_cache = {"fingerprint": None, "entries": None}


def _fingerprint():
    p = Product.objects.aggregate(n=Count("id"), m=Max("updated_at"))
    a = ProductAlias.objects.aggregate(n=Count("id"), m=Max("updated_at"))
    c = Category.objects.aggregate(n=Count("id"), m=Max("updated_at"))
    return (p["n"], p["m"], a["n"], a["m"], c["n"], c["m"])


def get_entries():
    """Searchable catalogue index, rebuilt automatically when products/aliases/categories change."""
    fp = _fingerprint()
    if _index_cache["fingerprint"] != fp:
        raw = []
        products = Product.objects.filter(category__is_active=True).prefetch_related("aliases")
        for p in products:
            names = [p.name_en, p.name_ta] + [a.text for a in p.aliases.all()]
            if p.pack_description:
                names.append(f"{p.name_en} {p.pack_description}")
            raw.append((p.pk, [n for n in names if n]))
        _index_cache.update(fingerprint=fp, entries=build_entries(raw))
    return _index_cache["entries"]


def _label(value, unit_code, product=None):
    """('0.5', LITRE) -> {'en': '0.5 litre', 'ta': '0.5 லிட்டர்'}"""
    if unit_code is None:
        return {"en": fmt_qty(value), "ta": fmt_qty(value)}
    return {"en": f"{fmt_qty(value)} {U.unit_label(unit_code, value)}",
            "ta": f"{fmt_qty(value)} {U.unit_label(unit_code, lang='ta')}"}


def _raw_to_json(quantities):
    return [{"value": None if q.value is None else str(q.value), "unit": q.unit} for q in quantities]


def raw_from_json(data):
    out = []
    for q in data or []:
        try:
            value = None if q.get("value") in (None, "") else Decimal(str(q["value"]))
        except Exception:
            continue
        unit = q.get("unit")
        if unit is not None and unit not in U.UNIT_INFO:
            continue
        out.append(QuantityCandidate(value, unit, ""))
    return out


def _convert(cand, product):
    """
    Express one spoken quantity in the product's selling unit.
    Returns (quantity|None, kind) with kind in ok | needs_unit | mismatch.
    Only same-dimension measures are converted; a measure is NEVER turned into a count.
    """
    if cand.unit is None:
        return (cand.value, "ok") if not U.is_measure(product.unit) else (cand.value, "needs_unit")
    if cand.unit == product.unit:
        return cand.value.quantize(Decimal("0.001")), "ok"
    if U.is_measure(cand.unit) and U.is_measure(product.unit) \
            and U.dimension(cand.unit) == U.dimension(product.unit):
        converted = U.convert_quantity(cand.value, cand.unit, product.unit)
        return (converted, "ok") if converted is not None else (None, "mismatch")
    return None, "mismatch"


def resolve_quantity(raw_quantities, product):
    """Decide what the customer's quantity words mean for this product. Never guesses."""
    name_en = product.display_name_en
    name_ta = product.display_name_ta or product.display_name_en
    unit_en, unit_ta = product.unit_label_en, product.unit_label_ta
    cands = [q for q in raw_quantities if q.value is not None]

    base = {"status": "", "quantity": None, "suggested_quantity": None, "options": [], "message": msg("", "")}

    if not cands:
        base.update(status="needs_quantity", message=msg(
            f"How many {unit_en} of {name_en} do you want?",
            f"{name_ta} எத்தனை {unit_ta} வேண்டும்?"))
        return base

    converted = [(c, *_convert(c, product)) for c in cands]
    distinct = {}
    for c, qty, kind in converted:
        key = (qty, kind) if qty is not None else ("raw", c.value, c.unit)
        distinct.setdefault(key, (c, qty, kind))

    if len(distinct) > 1:
        options = []
        for c, qty, kind in distinct.values():
            if qty is not None and kind in ("ok", "needs_unit"):
                options.append({"quantity": fmt_qty(qty), "label": _label(c.value, c.unit)})
        base.update(status="conflict", options=options, message=msg(
            f"I heard more than one quantity for {name_en}. Which one do you want?",
            f"{name_ta} க்கு ஒன்றுக்கு மேற்பட்ட அளவு கேட்டது. எது வேண்டும்?"))
        return base

    c, qty, kind = next(iter(distinct.values()))
    if kind == "needs_unit":
        base.update(status="needs_unit", suggested_quantity=fmt_qty(qty), message=msg(
            f"{name_en} is sold by {unit_en}. Did you mean {fmt_qty(qty)} {unit_en}?",
            f"{name_ta} {unit_ta} கணக்கில் விற்கப்படுகிறது. {fmt_qty(qty)} {unit_ta} வேண்டுமா?"))
        return base
    if kind == "mismatch":
        suggestion = None
        if c.unit and not U.is_measure(c.unit) and not U.is_measure(product.unit):
            suggestion = fmt_qty(c.value)  # packets <-> pieces: only suggested, customer must confirm
        base.update(status="unit_mismatch", suggested_quantity=suggestion, message=msg(
            f"{name_en} is sold per {unit_en}, not per {U.unit_label(c.unit) if c.unit else 'that unit'}. "
            f"Please enter how many {unit_en} you want.",
            f"{name_ta} {unit_ta} கணக்கில் விற்கப்படுகிறது. எத்தனை {unit_ta} வேண்டும் என்று உள்ளிடவும்."))
        return base

    problems = validate_quantity(product, qty)
    if problems:
        suggestion = nearest_valid_quantity(product, qty) if qty and qty > 0 else product.min_quantity
        base.update(status="invalid_rules", quantity=None, suggested_quantity=fmt_qty(suggestion),
                    message=problems[0])
        return base
    base.update(status="ok", quantity=fmt_qty(qty))
    return base


def check_typed_quantity(product, quantity):
    """Customer typed a quantity themselves: validate against the selling rules."""
    try:
        qty = Decimal(str(quantity))
    except Exception:
        return {"status": "invalid_rules", "quantity": None, "suggested_quantity": None, "options": [],
                "message": msg("That quantity is not a number.", "இது சரியான எண் அல்ல.")}
    problems = validate_quantity(product, qty)
    if problems:
        suggestion = nearest_valid_quantity(product, qty) if qty > 0 else product.min_quantity
        return {"status": "invalid_rules", "quantity": None, "suggested_quantity": fmt_qty(suggestion),
                "options": [], "message": problems[0]}
    return {"status": "ok", "quantity": fmt_qty(qty), "suggested_quantity": None, "options": [],
            "message": msg("", "")}


def build_item(raw_text, product_text, raw_quantities, product):
    """Item dict for a chosen product (used by interpret() and by the resolve endpoint)."""
    item = {"raw": raw_text, "product_text": product_text, "raw_quantities": _raw_to_json(raw_quantities),
            "candidates": [], "product": product_payload(product)}
    if not product.is_orderable:
        item.update(status="unavailable", quantity=None, suggested_quantity=None, options=[],
                    message=unavailable_message(product))
        return item
    item.update(resolve_quantity(raw_quantities, product))
    return item


def interpret(text):
    """Main entry: spoken/typed text -> {"items": [...]} for the review screen."""
    text = (text or "").strip()[:MAX_TEXT_LENGTH]
    parsed = parse_order_text(text)[:MAX_ITEMS]
    if not parsed:
        return {"items": [], "empty": True}
    entries = get_entries()
    results = [(p, match_product(p.product_text, entries)) for p in parsed]
    ids = {pid for _, r in results for pid, _s in r.candidates}
    products = {p.pk: p for p in Product.objects.filter(pk__in=ids).select_related("category")}

    items = []
    for p, r in results:
        if r.status == "matched":
            items.append(build_item(p.raw, p.product_text, p.quantities, products[r.candidates[0][0]]))
            continue
        base = {"raw": p.raw, "product_text": p.product_text, "raw_quantities": _raw_to_json(p.quantities),
                "product": None, "quantity": None, "suggested_quantity": None, "options": []}
        if r.status == "ambiguous":
            cands = []
            for pid, score in r.candidates:
                if pid in products:
                    d = product_payload(products[pid])
                    d["score"] = score
                    cands.append(d)
            base.update(status="ambiguous_product", candidates=cands, message=msg(
                f"Which product did you mean by “{p.product_text}”?",
                f"“{p.product_text}” – எந்த பொருள் வேண்டும்?"))
        else:
            base.update(status="unknown_product", candidates=[], message=msg(
                f"I could not find “{p.product_text}”. Please search by name or try again.",
                f"“{p.product_text}” கிடைக்கவில்லை. பெயரால் தேடவும் அல்லது மீண்டும் சொல்லவும்."))
        items.append(base)
    return {"items": items, "empty": False}


def search_products(query, limit=8):
    """Typeahead for the 'search by name' fallback. Uses the same matcher; never returns hidden categories."""
    entries = get_entries()
    r = match_product(query, entries)
    ids = [pid for pid, _ in r.candidates][:limit]
    if not ids:
        # fall back to simple substring search so short queries still find something
        qs = Product.objects.filter(category__is_active=True, name_en__icontains=query.strip())[:limit]
        return [product_payload(p) for p in qs.select_related("category")]
    products = {p.pk: p for p in Product.objects.filter(pk__in=ids).select_related("category")}
    return [product_payload(products[i]) for i in ids if i in products]
