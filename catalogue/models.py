from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from . import units
from .textnorm import loose_key


class Category(models.Model):
    name_ta = models.CharField("Tamil name", max_length=120, blank=True)
    name_en = models.CharField("English name", max_length=120, unique=True)
    is_active = models.BooleanField("Active", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name_en"]

    def __str__(self):
        return self.name_en


class Product(models.Model):
    # Code from the existing billing software (if the owner can export it). Used to match on import.
    external_code = models.CharField(max_length=64, unique=True, null=True, blank=True,
                                     help_text="Product code from the existing billing system, if any.")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    name_en = models.CharField("English name", max_length=200)
    name_ta = models.CharField("Tamil name", max_length=200, blank=True)
    price = models.DecimalField("Price per selling unit (₹)", max_digits=10, decimal_places=2)
    unit = models.CharField("Selling unit", max_length=10, choices=units.UNIT_CHOICES, default=units.PIECE)
    pack_description = models.CharField(
        "Pack description", max_length=100, blank=True,
        help_text="Optional text shown to customers, e.g. '250 g pack' or '6 in a pack'.")
    min_quantity = models.DecimalField("Minimum quantity", max_digits=10, decimal_places=3, default=Decimal("1"))
    quantity_step = models.DecimalField(
        "Quantity increment", max_digits=10, decimal_places=3, default=Decimal("1"),
        help_text="Quantity must be a multiple of this (e.g. 6 = sold only in 6s, 0.5 = half-litre steps).")
    is_available = models.BooleanField(
        "Available", default=True,
        help_text="Owner-controlled. Stock levels are NOT tracked automatically.")
    image = models.ImageField(upload_to="products/", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name_en"]
        constraints = [
            models.CheckConstraint(condition=models.Q(price__gt=0), name="product_price_positive"),
            models.CheckConstraint(condition=models.Q(min_quantity__gt=0), name="product_minqty_positive"),
            models.CheckConstraint(condition=models.Q(quantity_step__gt=0), name="product_step_positive"),
            models.UniqueConstraint(Lower("name_en"), Lower("pack_description"), name="product_unique_name_pack"),
        ]
        indexes = [models.Index(fields=["is_available"]), models.Index(fields=["name_en"])]

    def __str__(self):
        return self.display_name_en

    # Set by from_db() so we can detect price edits without extra queries.
    _original_price = None
    _changed_by = None

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._original_price = instance.__dict__.get("price")  # None if deferred
        return instance

    @property
    def display_name_en(self):
        return f"{self.name_en} ({self.pack_description})" if self.pack_description else self.name_en

    @property
    def display_name_ta(self):
        if not self.name_ta:
            return ""
        return f"{self.name_ta} ({self.pack_description})" if self.pack_description else self.name_ta

    @property
    def unit_label_en(self):
        return units.unit_label(self.unit)

    @property
    def unit_label_ta(self):
        return units.unit_label(self.unit, lang="ta")

    @property
    def is_orderable(self):
        return self.is_available and self.category.is_active

    def clean(self):
        super().clean()
        if self.external_code is not None:
            self.external_code = self.external_code.strip() or None
        if self.quantity_step and self.min_quantity and self.min_quantity % self.quantity_step != 0:
            raise ValidationError({"min_quantity": "Minimum quantity must be a multiple of the quantity increment."})
        if self.unit in (units.PIECE, units.PACKET, units.BOTTLE, units.PACK) and self.quantity_step is not None \
                and self.quantity_step % 1 != 0:
            raise ValidationError({"quantity_step": "Counted items (pieces, packets, bottles, packs) must use whole-number steps."})

    def save(self, *args, **kwargs):
        if isinstance(self.external_code, str):
            self.external_code = self.external_code.strip() or None
        old_price = self._original_price
        super().save(*args, **kwargs)
        # Audit trail: every real price change is recorded with who made it.
        if old_price is not None and old_price != self.price:
            PriceChange.objects.create(product=self, old_price=old_price, new_price=self.price,
                                       changed_by=self._changed_by)
        self._original_price = self.price


class ProductAlias(models.Model):
    LANG_CHOICES = [("ta", "Tamil"), ("en", "English"), ("tanglish", "Tamil written in English letters"),
                    ("other", "Other / spoken name")]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="aliases")
    text = models.CharField("Alternate name", max_length=200)
    language = models.CharField(max_length=10, choices=LANG_CHOICES, default="other")
    normalized = models.CharField(max_length=200, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "product aliases"
        ordering = ["product__name_en", "text"]

    def __str__(self):
        return f"{self.text} → {self.product.name_en}"

    def clean(self):
        super().clean()
        key = loose_key(self.text)
        if not key:
            raise ValidationError({"text": "Alias cannot be empty."})
        clash = Alias_conflict(key, exclude_product_id=self.product_id)
        if clash:
            raise ValidationError({"text": f"'{self.text}' is already the name of another product: {clash}."})
        dup = ProductAlias.objects.filter(normalized=key).exclude(pk=self.pk).select_related("product").first()
        if dup:
            raise ValidationError({"text": f"Already used as an alias for '{dup.product.name_en}'."})

    def save(self, *args, **kwargs):
        self.normalized = loose_key(self.text)
        super().save(*args, **kwargs)


def Alias_conflict(key, exclude_product_id=None):
    """Return a product name if `key` equals another product's English/Tamil name, else None."""
    qs = Product.objects.all()
    if exclude_product_id:
        qs = qs.exclude(pk=exclude_product_id)
    for p in qs.only("name_en", "name_ta"):
        if loose_key(p.name_en) == key or (p.name_ta and loose_key(p.name_ta) == key):
            return p.name_en
    return None


class PriceChange(models.Model):
    """Read-only audit log of price edits."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="price_changes")
    old_price = models.DecimalField(max_digits=10, decimal_places=2)
    new_price = models.DecimalField(max_digits=10, decimal_places=2)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.product.name_en}: {self.old_price} → {self.new_price}"


class ImportBatch(models.Model):
    """A previewed (and possibly applied) catalogue import."""
    STATUS = [("PREVIEW", "Preview"), ("APPLIED", "Applied"), ("DISCARDED", "Discarded")]
    filename = models.CharField(max_length=255)
    status = models.CharField(max_length=10, choices=STATUS, default="PREVIEW")
    rows = models.JSONField(default=list)       # validated row dicts
    summary = models.JSONField(default=dict)    # counts + errors
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "import batches"

    def __str__(self):
        return f"{self.filename} ({self.status})"
