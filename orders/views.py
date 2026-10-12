"""Customer-facing pages."""
from urllib.parse import quote

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

from . import services
from .models import Order, ShopSettings
from .ratelimit import rate_limit


@ensure_csrf_cookie
def home(request):
    shop = ShopSettings.load()
    config = {
        "delivery_enabled": shop.enable_delivery,
        "delivery_fee": str(shop.delivery_fee),
        "payment_methods": {
            Order.PICKUP: shop.allowed_payment_methods(Order.PICKUP),
            Order.DELIVERY: shop.allowed_payment_methods(Order.DELIVERY) if shop.enable_delivery else [],
        },
    }
    return render(request, "orders/home.html", {"config": config})


STATUS_STEPS_PICKUP = [Order.PENDING, Order.ACCEPTED, Order.PREPARING, Order.READY, Order.COMPLETED]
STATUS_STEPS_DELIVERY = [Order.PENDING, Order.ACCEPTED, Order.PREPARING, Order.OUT_FOR_DELIVERY, Order.COMPLETED]


def _upi_link(shop, order):
    if not (shop.upi_id and order.payment_method == Order.PAY_UPI):
        return ""
    return (f"upi://pay?pa={quote(shop.upi_id)}&pn={quote(shop.upi_payee_name or shop.shop_name)}"
            f"&am={order.total}&cu=INR&tn={quote(order.order_number)}")


def order_detail(request, token):
    """Confirmation + status page. Reachable only with the order's secret token."""
    order = get_object_or_404(Order.objects.prefetch_related("items"), public_token=token)
    shop = ShopSettings.load()
    steps = STATUS_STEPS_PICKUP if order.fulfilment == Order.PICKUP else STATUS_STEPS_DELIVERY
    labels = dict(Order.STATUS_CHOICES)
    if order.status in (Order.REJECTED, Order.CANCELLED):
        timeline = None
    else:
        idx = steps.index(order.status) if order.status in steps else 0
        timeline = [{"label": labels[s], "done": i < idx, "current": i == idx} for i, s in enumerate(steps)]
    show_upi = (order.payment_method == Order.PAY_UPI and not order.is_terminal
                and order.payment_status in (Order.PAY_PENDING, Order.PAY_FAILED, Order.PAY_AWAITING))
    return render(request, "orders/order_detail.html", {
        "order": order, "timeline": timeline, "upi_link": _upi_link(shop, order) if show_upi else "",
        "show_upi": show_upi, "just_placed": request.GET.get("placed") == "1",
    })


@require_POST
@rate_limit("claim", 10, 60, as_json=False)
def order_claim_paid(request, token):
    order = get_object_or_404(Order, public_token=token)
    try:
        services.customer_claims_payment(order.pk, request.POST.get("reference", ""))
        messages.success(request, "Thank you. The shop will check your payment and confirm it. / நன்றி. கடை உங்கள் கட்டணத்தை சரிபார்த்து உறுதி செய்யும்.")
    except services.TransitionError as exc:
        messages.error(request, str(exc))
    return redirect("order_detail", token=token)


@require_http_methods(["GET", "POST"])
@rate_limit("lookup", 15, 60, as_json=False)
def order_lookup(request):
    """Find an order by number + phone. The same generic message is used for every miss."""
    if request.method == "POST":
        number = request.POST.get("order_number", "").strip().upper()
        phone = services.normalize_phone(request.POST.get("phone"))
        order = Order.objects.filter(order_number=number, customer_phone=phone).first() if phone else None
        if order:
            return redirect("order_detail", token=order.public_token)
        messages.error(request, "We could not find an order with those details. / அந்த விவரங்களுடன் ஆர்டர் கிடைக்கவில்லை.")
    return render(request, "orders/lookup.html")
