"""
Create the two standard groups (idempotent - safe to run again after upgrades).

    Owner : everything - catalogue, prices, aliases, import, orders, payments, shop settings
    Staff : view and update orders only (cannot change prices or verify payments)

Create users with `python manage.py createsuperuser` (the shop owner) or in Django Admin,
tick "Staff status" and add them to a group.
"""
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


def perms(*codenames):
    return list(Permission.objects.filter(codename__in=codenames))


class Command(BaseCommand):
    help = "Create/refresh the Owner and Staff permission groups."

    def handle(self, *args, **opts):
        owner, _ = Group.objects.get_or_create(name="Owner")
        owner_codes = [
            "manage_orders", "verify_payments", "view_order",
            "add_category", "change_category", "view_category",
            "add_product", "change_product", "view_product",
            "add_productalias", "change_productalias", "delete_productalias", "view_productalias",
            "view_pricechange", "view_importbatch",
            "change_shopsettings", "view_shopsettings",
        ]
        owner.permissions.set(perms(*owner_codes))
        staff, _ = Group.objects.get_or_create(name="Staff")
        staff.permissions.set(perms("manage_orders", "view_order", "view_product"))
        self.stdout.write(self.style.SUCCESS("Groups 'Owner' and 'Staff' are ready."))
