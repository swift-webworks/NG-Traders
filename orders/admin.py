from django.contrib import admin

from .models import Order, OrderItem, OrderStatusLog, PaymentRecord, ShopSettings


@admin.register(ShopSettings)
class ShopSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Shop", {"fields": ("shop_name", "phone_primary", "phone_secondary", "address")}),
        ("Delivery", {"fields": ("enable_delivery", "delivery_fee")}),
        ("Payments", {"fields": ("enable_upi", "upi_id", "upi_payee_name", "upi_qr_image",
                                 "enable_cash_on_pickup", "enable_cash_on_delivery")}),
    )

    def has_add_permission(self, request):
        return not ShopSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class ReadOnlyInline(admin.TabularInline):
    can_delete = False
    extra = 0

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class OrderItemInline(ReadOnlyInline):
    model = OrderItem
    fields = ("position", "name_en", "unit_label", "quantity", "unit_price", "line_total")


class StatusLogInline(ReadOnlyInline):
    model = OrderStatusLog
    fields = ("created_at", "from_status", "to_status", "changed_by", "note")


class PaymentRecordInline(ReadOnlyInline):
    model = PaymentRecord
    fields = ("created_at", "action", "amount", "reference", "note", "recorded_by")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """
    VIEW ONLY. Orders and bills are never edited here, so totals and history cannot be altered by accident.
    Status and payment changes are made on the owner dashboard, which enforces the allowed transitions.
    """
    list_display = ("order_number", "created_at", "customer_name", "customer_phone", "fulfilment",
                    "payment_method", "status", "payment_status", "total")
    list_filter = ("status", "payment_status", "fulfilment", "payment_method")
    search_fields = ("order_number", "customer_name", "customer_phone")
    date_hierarchy = "created_at"
    inlines = [OrderItemInline, PaymentRecordInline, StatusLogInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False  # view-only (the 'view' permission still lets staff open orders)

    def has_delete_permission(self, request, obj=None):
        return False
