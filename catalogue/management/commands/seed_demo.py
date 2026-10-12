"""
DEVELOPMENT ONLY: create clearly labelled demo products so the app can be tried.

    python manage.py seed_demo            # add demo data
    python manage.py seed_demo --remove   # delete it again

Demo products have codes starting with DEMO- and PLACEHOLDER prices. They are NOT
NG Traders' real prices. Refuses to run when DEBUG is off unless --force is given.
"""
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from catalogue import units as U
from catalogue.models import Category, Product, ProductAlias
from catalogue.textnorm import loose_key

# (code, category_en, category_ta, name_en, name_ta, unit, price, min, step, pack, aliases[(text, lang)])
DEMO = [
    ("DEMO-001", "Soaps", "சோப்புகள்", "Lux Soap", "லக்ஸ் சோப்பு", U.PIECE, "40", "1", "1", "100 g",
     [("லக்ஸ் சோப்", "ta"), ("lux soappu", "tanglish"), ("lux sabun", "tanglish")]),
    ("DEMO-002", "Biscuits", "பிஸ்கட்", "Milk Biscuits", "மில்க் பிஸ்கட்", U.PACKET, "10", "1", "1", "",
     [("மில்க் பிஸ்கட்டு", "ta"), ("milk biscuit", "en")]),
    ("DEMO-003", "Oils", "எண்ணெய்", "Palm Oil", "பாமாயில்", U.LITRE, "120", "0.5", "0.5", "",
     [("பாம் ஆயில்", "ta"), ("palm oil", "en"), ("pamoil", "tanglish")]),
    ("DEMO-004", "Groceries", "மளிகை", "Sugar", "சர்க்கரை", U.KG, "45", "0.25", "0.25", "",
     [("சீனி", "ta"), ("sakkarai", "tanglish"), ("seeni", "tanglish")]),
    ("DEMO-005", "Groceries", "மளிகை", "Raw Rice", "பச்சரிசி", U.KG, "55", "1", "1", "",
     [("அரிசி", "ta"), ("arisi", "tanglish"), ("rice", "en")]),
    ("DEMO-006", "Groceries", "மளிகை", "Toor Dal", "துவரம் பருப்பு", U.KG, "130", "0.5", "0.5", "",
     [("thuvaram paruppu", "tanglish"), ("tur dal", "en"), ("பருப்பு", "ta")]),
    ("DEMO-007", "Soaps", "சோப்புகள்", "Lux Soap Rose", "லக்ஸ் ரோஸ் சோப்பு", U.PIECE, "42", "1", "1", "100 g",
     [("lux rose", "en")]),
    ("DEMO-008", "Snacks", "தின்பண்டம்", "Instant Noodles", "இன்ஸ்டன்ட் நூடுல்ஸ்", U.PACKET, "14", "6", "6", "sold in 6s",
     [("noodles", "en"), ("நூடுல்ஸ்", "ta")]),
    ("DEMO-009", "Groceries", "மளிகை", "Salt", "உப்பு", U.PACKET, "20", "1", "1", "1 kg pack",
     [("uppu", "tanglish")]),
    ("DEMO-010", "Oils", "எண்ணெய்", "Coconut Oil", "தேங்காய் எண்ணெய்", U.BOTTLE, "180", "1", "1", "500 ml",
     [("thengai ennai", "tanglish"), ("coconut oil", "en")]),
]


class Command(BaseCommand):
    help = "Create (or remove) clearly labelled DEMO products for development."

    def add_arguments(self, parser):
        parser.add_argument("--remove", action="store_true")
        parser.add_argument("--force", action="store_true", help="Allow when DEBUG is off.")

    def handle(self, *args, remove=False, force=False, **opts):
        if not settings.DEBUG and not force:
            raise CommandError("Refusing to seed demo data while DEBUG is off (use --force if you really mean it).")
        if remove:
            n, _ = Product.objects.filter(external_code__startswith="DEMO-").delete()
            self.stdout.write(f"Removed demo products ({n} rows incl. aliases).")
            return
        for code, cat_en, cat_ta, en, ta, unit, price, mn, step, pack, aliases in DEMO:
            cat, _ = Category.objects.get_or_create(name_en=cat_en, defaults={"name_ta": cat_ta})
            product, created = Product.objects.get_or_create(
                external_code=code,
                defaults=dict(category=cat, name_en=en, name_ta=ta, unit=unit, price=Decimal(price),
                              min_quantity=Decimal(mn), quantity_step=Decimal(step), pack_description=pack))
            if created:
                for text, lang in aliases:
                    ProductAlias.objects.get_or_create(
                        normalized=loose_key(text),
                        defaults=dict(product=product, text=text, language=lang))
        self.stdout.write(self.style.WARNING(
            "DEMO data created. Prices are placeholders, NOT real NG Traders prices."))
