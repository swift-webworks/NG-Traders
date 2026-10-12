"""
Order creation, status transitions and payment decisions.

Everything that changes an order goes through here so the rules live in one place and
are covered by tests. Views stay thin.
"""
import re
import secrets
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from catalogue.services import msg

from .billing import build_bill
from .models import Order, OrderItem, OrderStatusLog, PaymentRecord, ShopSettings

IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9\-]{16,64}$")
_ORDER_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L: easy to read aloud on the phone
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class TransitionError(Exception):
    """A status/payment change that the rules do not allow."""


def clean_text(value, max_len):
    value = _CONTROL_CHARS.sub("", str(value or "")).strip()
    return re.sub(r"[ \t]+", " ", value)[:max_len]


def normalize_phone(raw):
    """Indian mobile numbers: returns the 10 digits or None."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if re.fullmatch(r"[6-9]\d{9}", digits) else None


def _new_order_number():
    stamp = timezone.localtime().strftime("%y%m%d")
    return f"NG-{stamp}-" + "".join(secrets.choice(_ORDER_ALPHABET) for _ in range(5))


# --------------------------------------------------------------------------- creation

def create_order(payload):
    """
    Validate + price + save an order atomically.
    Returns (order, created, errors). `errors` is None on success, else
    {"fields": {name: {"en","ta"}}, "general": [...], "bill": {...}|None}.
    Calling again with the same idempotency_key returns the original order (created=False).
    """
    shop = ShopSettings.load()
    fields, general = {}, []

    key = str(payload.get("idempotency_key", ""))
    if not IDEMPOTENCY_RE.match(key):
        general.append(msg("Something went wrong with your session. Please refresh the page and try again.",
                           "ஏதோ தவறு நடந்தது. பக்கத்தை புதுப்பித்து மீண்டும் முயற்சிக்கவும்."))
        return None, False, {"fields": fields, "general": general, "bill": None}

    existing = Order.objects.filter(idempotency_key=key).first()
    if existing:
        return existing, False, None

    name = clean_text(payload.get("customer_name"), 80)
    if len(name) < 2:
        fields["customer_name"] = msg("Please enter your name.", "உங்கள் பெயரை உள்ளிடவும்.")
    phone = normalize_phone(payload.get("customer_phone"))
    if not phone:
        fields["customer_phone"] = msg("Please enter a valid 10-digit mobile number.",
                                       "சரியான 10 இலக்க மொபைல் எண்ணை உள்ளிடவும்.")

    fulfilment = payload.get("fulfilment")
    if fulfilment not in (Order.PICKUP, Order.DELIVERY) or (fulfilment == Order.DELIVERY and not shop.enable_delivery):
        fields["fulfilment"] = msg("Please choose Store Pickup or Home Delivery.",
                                   "கடையில் எடுத்தல் அல்லது வீட்டுக்கு டெலிவரி என்பதைத் தேர்வு செய்யவும்.")
        fulfilment = None

    address = clean_text(payload.get("delivery_address"), 400)
    if fulfilment == Order.DELIVERY and len(address) < 10:
        fields["delivery_address"] = msg("Please enter your full delivery address.",
                                         "டெலிவரி முகவரியை முழுமையாக உள்ளிடவும்.")
    if fulfilment == Order.PICKUP:
        address = ""

    method = payload.get("payment_method")
    if fulfilment and method not in shop.allowed_payment_methods(fulfilment):
        fields["payment_method"] = msg("Please choose one of the available payment methods.",
                                       "கிடைக்கும் கட்டண முறைகளில் ஒன்றைத் தேர்வு செய்யவும்.")

    notes = clean_text(payload.get("notes"), 500)
    if fields:
        return None, False, {"fields": fields, "general": general, "bill": None}

    try:
        with transaction.atomic():
            bill = build_bill(payload.get("items"), fulfilment, lock=True, shop=shop)
            if not bill.ok:
                raise _BillInvalid(bill)
            order = _save_order(key, name, phone, fulfilment, address, method, notes, bill)
    except _BillInvalid as exc:
        return None, False, {"fields": {}, "general": exc.bill.errors, "bill": exc.bill.as_dict()}
    except IntegrityError:
        # a parallel request with the same idempotency key won the race
        existing = Order.objects.filter(idempotency_key=key).first()
        if existing:
            return existing, False, None
        raise
    return order, True, None


class _BillInvalid(Exception):
    def __init__(self, bill):
        self.bill = bill


def _save_order(key, name, phone, fulfilment, address, method, notes, bill):
    order = None
    for _ in range(10):  # order numbers are random; retry on the (very unlikely) collision
        number = _new_order_number()
        try:
            with transaction.atomic():
                order = Order.objects.create(
                    order_number=number, idempotency_key=key, customer_name=name, customer_phone=phone,
                    delivery_address=address, notes=notes, fulfilment=fulfilment, payment_method=method,
                    subtotal=bill.subtotal, delivery_charge=bill.delivery_charge, total=bill.total)
            break
        except IntegrityError:
            if Order.objects.filter(idempotency_key=key).exists():
                raise
            continue
    if order is None:
        raise RuntimeError("Could not allocate an order number")
    OrderItem.objects.bulk_create([
        OrderItem(order=order, product=l.product, position=i, name_en=l.product.display_name_en,
                  name_ta=l.product.display_name_ta, unit_code=l.product.unit, unit_label=l.product.unit_label_en,
                  quantity=l.quantity, unit_price=l.unit_price, line_total=l.line_total)
        for i, l in enumerate(bill.lines, 1)
    ])
    OrderStatusLog.objects.create(order=order, from_status="", to_status=Order.PENDING, note="Order placed")
    return order


# --------------------------------------------------------------------------- status

def allowed_next_statuses(order):
    s = order.status
    if s == Order.PENDING:
        return [Order.ACCEPTED, Order.REJECTED]
    if s == Order.ACCEPTED:
        return [Order.PREPARING, Order.CANCELLED]
    if s == Order.PREPARING:
        return [Order.READY if order.fulfilment == Order.PICKUP else Order.OUT_FOR_DELIVERY, Order.CANCELLED]
    if s in (Order.READY, Order.OUT_FOR_DELIVERY):
        return [Order.COMPLETED, Order.CANCELLED]
    return []


def change_status(order_id, new_status, user, note=""):
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if new_status not in allowed_next_statuses(order):
            raise TransitionError(f"Cannot change an order from '{order.get_status_display()}' to "
                                  f"'{dict(Order.STATUS_CHOICES).get(new_status, new_status)}'.")
        if new_status in (Order.REJECTED, Order.CANCELLED) and not clean_text(note, 300):
            raise TransitionError("Please give a short reason when rejecting or cancelling an order.")
        if new_status == Order.COMPLETED and order.payment_status != Order.PAY_PAID:
            raise TransitionError("Record the payment first (verify UPI or mark cash collected), then complete the order.")
        old = order.status
        order.status = new_status
        order.save(update_fields=["status", "updated_at"])
        OrderStatusLog.objects.create(order=order, from_status=old, to_status=new_status,
                                      changed_by=user, note=clean_text(note, 300))
    return order


# --------------------------------------------------------------------------- payments

def _lock(order_id):
    return Order.objects.select_for_update().get(pk=order_id)


def customer_claims_payment(order_id, reference=""):
    """Customer says they paid by UPI. This is NOT proof: status becomes 'awaiting verification' only."""
    with transaction.atomic():
        order = _lock(order_id)
        if order.payment_method != Order.PAY_UPI:
            raise TransitionError("This order is not a UPI order.")
        if order.is_terminal:
            raise TransitionError("This order is closed.")
        if order.payment_status not in (Order.PAY_PENDING, Order.PAY_FAILED, Order.PAY_AWAITING):
            raise TransitionError("Payment is already recorded for this order.")
        order.payment_status = Order.PAY_AWAITING
        order.customer_payment_ref = clean_text(reference, 60)
        order.save(update_fields=["payment_status", "customer_payment_ref", "updated_at"])
        PaymentRecord.objects.create(order=order, action="CUSTOMER_CLAIMED", amount=order.total,
                                     reference=order.customer_payment_ref, note="Customer reported payment")
    return order


def verify_upi_payment(order_id, user, reference="", note=""):
    with transaction.atomic():
        order = _lock(order_id)
        if order.payment_method != Order.PAY_UPI:
            raise TransitionError("Only UPI orders can be verified this way.")
        if order.status in (Order.REJECTED, Order.CANCELLED):
            raise TransitionError("This order was rejected or cancelled.")
        if order.payment_status not in (Order.PAY_PENDING, Order.PAY_AWAITING, Order.PAY_FAILED):
            raise TransitionError("Payment is already recorded for this order.")
        order.payment_status = Order.PAY_PAID
        order.save(update_fields=["payment_status", "updated_at"])
        PaymentRecord.objects.create(order=order, action="VERIFIED_UPI", amount=order.total,
                                     reference=clean_text(reference or order.customer_payment_ref, 100),
                                     note=clean_text(note, 300), recorded_by=user)
    return order


def collect_cash(order_id, user, note=""):
    with transaction.atomic():
        order = _lock(order_id)
        if order.payment_method not in (Order.PAY_CASH_PICKUP, Order.PAY_COD):
            raise TransitionError("This is not a cash order.")
        if order.status in (Order.REJECTED, Order.CANCELLED):
            raise TransitionError("This order was rejected or cancelled.")
        if order.payment_status != Order.PAY_PENDING:
            raise TransitionError("Payment is already recorded for this order.")
        order.payment_status = Order.PAY_PAID
        order.save(update_fields=["payment_status", "updated_at"])
        PaymentRecord.objects.create(order=order, action="CASH_COLLECTED", amount=order.total,
                                     note=clean_text(note, 300), recorded_by=user)
    return order


def reject_payment(order_id, user, note=""):
    note = clean_text(note, 300)
    if not note:
        raise TransitionError("Please give a short reason for rejecting the payment.")
    with transaction.atomic():
        order = _lock(order_id)
        if order.payment_status not in (Order.PAY_PENDING, Order.PAY_AWAITING):
            raise TransitionError("Only a pending payment can be rejected.")
        order.payment_status = Order.PAY_FAILED
        order.save(update_fields=["payment_status", "updated_at"])
        PaymentRecord.objects.create(order=order, action="REJECTED", amount=order.total, note=note, recorded_by=user)
    return order


def confirm_refund(order_id, user, reference="", note=""):
    """Owner confirms money has ACTUALLY been returned. Never called automatically."""
    with transaction.atomic():
        order = _lock(order_id)
        if not order.refund_due:
            raise TransitionError("A refund can only be recorded for a paid order that was rejected or cancelled.")
        order.payment_status = Order.PAY_REFUNDED
        order.save(update_fields=["payment_status", "updated_at"])
        PaymentRecord.objects.create(order=order, action="REFUNDED", amount=order.total,
                                     reference=clean_text(reference, 100), note=clean_text(note, 300),
                                     recorded_by=user)
    return order
