import logging

from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from catalogue.models import Product
from catalogue.services import msg
from orders.http import BadRequest, bad_request, json_body
from orders.ratelimit import rate_limit

from . import service

log = logging.getLogger(__name__)


@require_POST
@rate_limit("parse", 40, 60)
def parse_view(request):
    """Spoken/typed text -> reviewable items. Does not change anything; no audio is ever received."""
    try:
        data = json_body(request)
    except BadRequest:
        return bad_request()
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        return bad_request("Please say or type your order first.", "முதலில் உங்கள் ஆர்டரை சொல்லவும் அல்லது தட்டச்சு செய்யவும்.")
    try:
        return JsonResponse(service.interpret(text))
    except Exception:  # never leak internals; log without the customer's words
        log.exception("parse failed")
        return bad_request("We could not understand that. Please try again or type the items.",
                           "புரிந்துகொள்ள முடியவில்லை. மீண்டும் முயற்சிக்கவும் அல்லது பொருட்களை தட்டச்சு செய்யவும்.", 500)


@require_POST
@rate_limit("resolve", 80, 60)
def resolve_view(request):
    """
    Customer picked a product (or typed a quantity) for an item that needed clarification.
    The server re-checks everything; the browser's idea of price/availability is never trusted.
    """
    try:
        data = json_body(request)
        pid = int(data.get("product_id"))
    except (BadRequest, TypeError, ValueError):
        return bad_request()
    product = Product.objects.select_related("category").filter(pk=pid, category__is_active=True).first()
    if product is None:
        return bad_request("That product was not found.", "அந்த பொருள் கிடைக்கவில்லை.", 404)
    raw_text = str(data.get("raw", ""))[:300]
    product_text = str(data.get("product_text", ""))[:200]
    raw_q = service.raw_from_json(data.get("raw_quantities"))
    item = service.build_item(raw_text, product_text, raw_q, product)
    typed = data.get("quantity")
    if typed not in (None, "") and item["status"] != "unavailable":
        item.update(service.check_typed_quantity(product, typed))
    return JsonResponse({"item": item})


@require_GET
@rate_limit("search", 90, 60)
def search_view(request):
    q = request.GET.get("q", "").strip()[:100]
    if len(q) < 2:
        return JsonResponse({"products": []})
    return JsonResponse({"products": service.search_products(q)})
