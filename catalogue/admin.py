from django.contrib import admin, messages

from .models import Category, ImportBatch, PriceChange, Product, ProductAlias

admin.site.site_header = "NG Traders — Owner Admin"
admin.site.site_title = "NG Traders Admin"
admin.site.index_title = "Products, prices and settings"


class AliasInline(admin.TabularInline):
    model = ProductAlias
    extra = 1
    fields = ("text", "language")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name_en", "name_ta", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name_en", "name_ta")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name_en", "name_ta", "pack_description", "category", "price", "unit", "min_quantity",
                    "quantity_step", "is_available", "external_code")
    list_filter = ("is_available", "category", "unit")
    list_editable = ("is_available",)
    search_fields = ("name_en", "name_ta", "external_code", "aliases__text")
    list_select_related = ("category",)
    inlines = [AliasInline]
    actions = ["mark_available", "mark_unavailable"]

    def save_model(self, request, obj, form, change):
        obj._changed_by = request.user  # recorded in the price-change audit log
        super().save_model(request, obj, form, change)

    @admin.action(description="Mark selected products as available")
    def mark_available(self, request, queryset):
        n = queryset.update(is_available=True)
        self.message_user(request, f"{n} product(s) marked available.", messages.SUCCESS)

    @admin.action(description="Mark selected products as NOT available")
    def mark_unavailable(self, request, queryset):
        n = queryset.update(is_available=False)
        self.message_user(request, f"{n} product(s) marked unavailable.", messages.SUCCESS)


@admin.register(ProductAlias)
class ProductAliasAdmin(admin.ModelAdmin):
    list_display = ("text", "language", "product")
    list_filter = ("language",)
    search_fields = ("text", "product__name_en", "product__name_ta")
    autocomplete_fields = ("product",)


@admin.register(PriceChange)
class PriceChangeAdmin(admin.ModelAdmin):
    """Audit log: view only."""
    list_display = ("changed_at", "product", "old_price", "new_price", "changed_by")
    list_filter = ("changed_at",)
    search_fields = ("product__name_en",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ("created_at", "filename", "status", "created_by")
    readonly_fields = ("filename", "status", "rows", "summary", "created_by", "created_at", "applied_at")

    def has_add_permission(self, request):
        return False
