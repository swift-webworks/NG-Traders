from decimal import Decimal as D

from django.contrib.auth.models import Group, User
from django.core.management import call_command

from catalogue import units as U
from catalogue.models import Category, Product, ProductAlias
from catalogue.textnorm import loose_key


def make_product(name_en, price, unit=U.PIECE, min_q="1", step="1", name_ta="", pack="", aliases=(), available=True,
                 category=None):
    category = category or Category.objects.get_or_create(name_en="Test Cat")[0]
    p = Product.objects.create(category=category, name_en=name_en, name_ta=name_ta, price=D(price), unit=unit,
                               min_quantity=D(min_q), quantity_step=D(step), pack_description=pack,
                               is_available=available)
    for a in aliases:
        ProductAlias.objects.create(product=p, text=a)
    return p


def make_catalogue():
    """Small TEST catalogue (prices are fake test values)."""
    return {
        "soap": make_product("Lux Soap", "40.00", U.PIECE, name_ta="லக்ஸ் சோப்பு", aliases=["lux soappu"]),
        "biscuit": make_product("Milk Biscuits", "10.00", U.PACKET, name_ta="மில்க் பிஸ்கட்"),
        "oil": make_product("Palm Oil", "120.00", U.LITRE, min_q="0.5", step="0.5", name_ta="பாமாயில்"),
        "sugar": make_product("Sugar", "45.50", U.KG, min_q="0.25", step="0.25", name_ta="சர்க்கரை", aliases=["seeni"]),
        "noodles": make_product("Instant Noodles", "14.00", U.PACKET, min_q="6", step="6"),
        "gone": make_product("Out Of Stock Item", "5.00", U.PIECE, available=False),
    }


def make_users():
    call_command("setup_roles", verbosity=0)
    owner = User.objects.create_user("owner", password="pw-owner-12345", is_staff=True)
    owner.groups.add(Group.objects.get(name="Owner"))
    staff = User.objects.create_user("staff", password="pw-staff-12345", is_staff=True)
    staff.groups.add(Group.objects.get(name="Staff"))
    customer = User.objects.create_user("cust", password="pw-cust-12345")
    return owner, staff, customer


def order_payload(items, **over):
    data = {
        "items": items, "fulfilment": "PICKUP", "payment_method": "CASH_PICKUP",
        "customer_name": "Ravi Kumar", "customer_phone": "9876543210", "delivery_address": "", "notes": "",
        "idempotency_key": "test-key-0123456789abcdef",
    }
    data.update(over)
    return data
