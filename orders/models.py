import secrets
from decimal import Decimal

from django.conf import settings
from django.db import models

from catalogue.models import Product


class ShopSettings(models.Model):
    """
    Single-row settings the owner edits in the admin (no code changes needed).
    Defaults come from settings.SHOP. UPI, delivery fee and COD stay OFF/zero until the owner confirms them.
    """
    shop_name = models.CharField(max_length=100, default="NG Traders")
    phone_primary = models.CharField(max_length=20, default="8610527033")
    phone_secondary = models.CharField(max_length=20, blank=True, default="6369603873")
    address = models.TextField(blank=True, help_text="Shown on bills. Leave blank if not confirmed.")
    enable_delivery = models.BooleanField(default=True)
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"),
                                       help_text="Flat fee for home delivery. 0 = free delivery.")
    enable_upi = models.BooleanField(default=False, help_text="Tick only after entering the shop's real UPI ID.")
    upi_id = models.CharField("UPI ID", max_length=100, blank=True)
    upi_payee_name = models.CharField(max_length=100, default="NG Traders", blank=True)
    upi_qr_image = models.ImageField("UPI QR image (optional)", upload_to="upi/", blank=True)
    enable_cash_on_pickup = models.BooleanField(default=True)
    enable_cash_on_delivery = models.BooleanField(default=False, help_text="Tick only if the owner permits COD.")

    class Meta:
        verbose_name = "shop settings"
        verbose_name_plural = "shop settings"

    def __str__(self):
        return "Shop settings"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={
            "shop_name": settings.SHOP["NAME"], "phone_primary": settings.SHOP["PHONE_PRIMARY"],
            "phone_secondary": settings.SHOP["PHONE_SECONDARY"], "address": settings.SHOP["ADDRESS"],
            "enable_delivery": settings.SHOP["ENABLE_DELIVERY"], "delivery_fee": settings.SHOP["DELIVERY_FEE"],
            "enable_upi": settings.SHOP["ENABLE_UPI"] and bool(settings.SHOP["UPI_ID"]),
            "upi_id": settings.SHOP["UPI_ID"], "upi_payee_name": settings.SHOP["UPI_PAYEE_NAME"],
            "enable_cash_on_pickup": settings.SHOP["ENABLE_CASH_ON_PICKUP"],
            "enable_cash_on_delivery": settings.SHOP["ENABLE_CASH_ON_DELIVERY"],
        })
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # singleton
        pass

    def allowed_payment_methods(self, fulfilment):
        """Payment methods valid for this fulfilment type, given the owner's settings."""
        methods = []
        if self.enable_upi and self.upi_id:
            methods.append(Order.PAY_UPI)
        if fulfilment == Order.PICKUP and self.enable_cash_on_pickup:
            methods.append(Order.PAY_CASH_PICKUP)
        if fulfilment == Order.DELIVERY and self.enable_cash_on_delivery:
            methods.append(Order.PAY_COD)
        return methods


def new_public_token():
    return secrets.token_urlsafe(24)


class Order(models.Model):
    PICKUP, DELIVERY = "PICKUP", "DELIVERY"
    FULFILMENT_CHOICES = [(PICKUP, "Store Pickup"), (DELIVERY, "Home Delivery")]

    PAY_UPI, PAY_CASH_PICKUP, PAY_COD = "UPI", "CASH_PICKUP", "COD"
    PAYMENT_METHOD_CHOICES = [(PAY_UPI, "UPI"), (PAY_CASH_PICKUP, "Cash on pickup"), (PAY_COD, "Cash on delivery")]

    PENDING, ACCEPTED, PREPARING = "PENDING", "ACCEPTED", "PREPARING"
    READY, OUT_FOR_DELIVERY, COMPLETED = "READY_FOR_PICKUP", "OUT_FOR_DELIVERY", "COMPLETED"
    REJECTED, CANCELLED = "REJECTED", "CANCELLED"
    STATUS_CHOICES = [
        (PENDING, "Pending"), (ACCEPTED, "Accepted"), (PREPARING, "Preparing"),
        (READY, "Ready for pickup"), (OUT_FOR_DELIVERY, "Out for delivery"),
        (COMPLETED, "Completed"), (REJECTED, "Rejected"), (CANCELLED, "Cancelled"),
    ]
    TERMINAL_STATUSES = {COMPLETED, REJECTED, CANCELLED}

    PAY_PENDING, PAY_AWAITING, PAY_PAID = "PENDING", "AWAITING_VERIFICATION", "PAID"
    PAY_FAILED, PAY_REFUNDED = "FAILED", "REFUNDED"
    PAYMENT_STATUS_CHOICES = [
        (PAY_PENDING, "Pending"), (PAY_AWAITING, "Awaiting verification"), (PAY_PAID, "Paid"),
        (PAY_FAILED, "Failed / rejected"), (PAY_REFUNDED, "Refunded"),
    ]

    order_number = models.CharField(max_length=20, unique=True, editable=False)
    # Unguessable token used in customer links; the order number alone never grants access.
    public_token = models.CharField(max_length=64, unique=True, default=new_public_token, editable=False)
    # Sent by the browser once per checkout; makes retries/double-taps return the same order.
    idempotency_key = models.CharField(max_length=64, unique=True, editable=False)

    customer_name = models.CharField(max_length=80)
    customer_phone = models.CharField(max_length=15, db_index=True)
    delivery_address = models.TextField(blank=True)
    notes = models.TextField(blank=True, max_length=500)

    fulfilment = models.CharField(max_length=10, choices=FULFILMENT_CHOICES)
    payment_method = models.CharField(max_length=12, choices=PAYMENT_METHOD_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    payment_status = models.CharField(max_length=24, choices=PAYMENT_STATUS_CHOICES, default=PAY_PENDING)
    customer_payment_ref = models.CharField("UPI reference given by customer", max_length=60, blank=True)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    delivery_charge = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        permissions = [
            ("manage_orders", "Can view and update orders"),
            ("verify_payments", "Can verify and record payments"),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(total__gte=0), name="order_total_nonneg"),
        ]

    def __str__(self):
        return self.order_number

    @property
    def is_terminal(self):
        return self.status in self.TERMINAL_STATUSES

    @property
    def refund_due(self):
        """Paid order that was rejected/cancelled: the owner still has to resolve the money."""
        return self.status in (self.REJECTED, self.CANCELLED) and self.payment_status == self.PAY_PAID

    @property
    def masked_phone(self):
        p = self.customer_phone
        return f"{'•' * max(len(p) - 4, 0)}{p[-4:]}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    # Reference kept for reporting only; the snapshot fields below are what the bill shows.
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    position = models.PositiveSmallIntegerField(default=1)
    name_en = models.CharField(max_length=220)
    name_ta = models.CharField(max_length=220, blank=True)
    unit_code = models.CharField(max_length=10)
    unit_label = models.CharField(max_length=40)
    quantity = models.DecimalField(max_digits=10, decimal_places=3)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["position", "id"]
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0), name="orderitem_qty_positive")]

    def __str__(self):
        return f"{self.name_en} × {self.quantity}"


class OrderStatusLog(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="status_logs")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class PaymentRecord(models.Model):
    """Append-only history of payment decisions (who verified / rejected / collected cash / refunded)."""
    ACTIONS = [
        ("CUSTOMER_CLAIMED", "Customer says paid (unverified)"),
        ("VERIFIED_UPI", "UPI payment verified"),
        ("CASH_COLLECTED", "Cash collected"),
        ("REJECTED", "Payment rejected"),
        ("REFUNDED", "Refund completed"),
    ]
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payment_records")
    action = models.CharField(max_length=20, choices=ACTIONS)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    reference = models.CharField(max_length=100, blank=True)
    note = models.CharField(max_length=300, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
