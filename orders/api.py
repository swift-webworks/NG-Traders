import logging

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from . import services
from .billing import build_bill
from .http import BadRequest, bad_request, json_body
from .models import Order
from .ratelimit import rate_limit

log = logging.getLogger(__name__)


@require_POST
@rate_limit("bill", 120, 60)
def bill_view(request):
    """Price a cart. Only product ids and quantities are read from the browser."""
    try:
        data = json_body(request)
    except BadRequest:
        return bad_request()
    fulfilment = data.get("fulfilment") if data.get("fulfilment") in (Order.PICKUP, Order.DELIVERY) else Order.PICKUP
    return JsonResponse(build_bill(data.get("items"), fulfilment).as_dict())


@require_POST
@rate_limit("order", 12, 60)
def create_order_view(request):
    try:
        data = json_body(request)
    except BadRequest:
        return bad_request()
    try:
        order, created, errors = services.create_order(data)
    except Exception:
        log.exception("order creation failed")  # no customer details in the log line
        return bad_request("We could not save your order. Nothing was ordered and you were not charged. "
                           "Please try again in a moment or call the shop.",
                           "ஆர்டரை சேமிக்க முடியவில்லை. எதுவும் ஆர்டர் செய்யப்படவில்லை. சிறிது நேரம் கழித்து முயற்சிக்கவும் அல்லது கடையை அழைக்கவும்.", 500)
    if errors:
        return JsonResponse({"error": errors}, status=400)
    return JsonResponse({
        "order_number": order.order_number,
        "url": reverse("order_detail", args=[order.public_token]),
        "duplicate": not created,
    }, status=201 if created else 200)


@require_GET
@rate_limit("orderstatus", 120, 60)
def order_status_json(request, token):
    order = get_object_or_404(Order, public_token=token)
    return JsonResponse({"status": order.status, "payment_status": order.payment_status,
                         "updated": order.updated_at.isoformat()})
