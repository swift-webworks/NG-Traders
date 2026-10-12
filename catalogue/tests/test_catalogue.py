import io
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from catalogue import importer
from catalogue.models import Category, PriceChange, Product, ProductAlias
from orders.tests.helpers import make_catalogue, make_product, make_users


class ProductModelTests(TestCase):
    def setUp(self):
        self.c = make_catalogue()

    def test_db_rejects_bad_numbers(self):
        cat = Category.objects.first()
        for bad in (dict(price=D("0")), dict(price=D("-1")), dict(min_quantity=D("0")), dict(quantity_step=D("0"))):
            fields = dict(category=cat, name_en="Bad", price=D("1"), unit="PIECE")
            fields.update(bad)
            with self.assertRaises(IntegrityError), transaction.atomic():
                Product.objects.create(**fields)

    def test_duplicate_name_and_pack_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_product("lux soap", "1")  # same name, different case, same (empty) pack
        make_product("Lux Soap", "1", pack="200 g")  # different pack is fine

    def test_min_must_be_multiple_of_step(self):
        p = Product(category=Category.objects.first(), name_en="X", price=D("1"), unit="KG",
                    min_quantity=D("0.3"), quantity_step=D("0.25"))
        with self.assertRaises(ValidationError):
            p.full_clean()

    def test_counted_units_need_whole_steps(self):
        p = Product(category=Category.objects.first(), name_en="Y", price=D("1"), unit="PIECE",
                    min_quantity=D("1"), quantity_step=D("0.5"))
        with self.assertRaises(ValidationError):
            p.full_clean()

    def test_price_change_is_audited(self):
        owner, _, _ = make_users()
        p = Product.objects.get(pk=self.c["soap"].pk)
        p._changed_by = owner
        p.price = D("55.00"); p.save()
        log = PriceChange.objects.get()
        self.assertEqual((log.old_price, log.new_price, log.changed_by), (D("40.00"), D("55.00"), owner))
        p.name_ta = "x"; p.save()  # no price change -> no new log
        self.assertEqual(PriceChange.objects.count(), 1)

    def test_orderable_requires_available_and_active_category(self):
        self.assertTrue(self.c["soap"].is_orderable)
        self.assertFalse(self.c["gone"].is_orderable)
        cat = self.c["soap"].category; cat.is_active = False; cat.save()
        self.assertFalse(Product.objects.get(pk=self.c["soap"].pk).is_orderable)


class AliasTests(TestCase):
    def setUp(self):
        self.c = make_catalogue()

    def test_alias_unique_across_products(self):
        a = ProductAlias(product=self.c["biscuit"], text="Lux Soappu")  # already an alias of Lux Soap
        with self.assertRaises(ValidationError):
            a.full_clean()

    def test_alias_cannot_equal_another_products_name(self):
        a = ProductAlias(product=self.c["biscuit"], text="palm oils")
        with self.assertRaises(ValidationError):
            a.full_clean()

    def test_alias_ok(self):
        a = ProductAlias(product=self.c["biscuit"], text="biscot")
        a.full_clean(); a.save()
        self.assertEqual(a.normalized, "biscot")


CSV_OK = """code,name,tamil_name,category,price,unit,pack,min_quantity,step,available,aliases
C1,Tea Powder,தேயிலை,Groceries,250.50,kg,,0.25,0.25,yes,chai|டீ தூள்
C2,Soap Bar,,Soaps,35,piece,,1,1,,
C3,Glucose Biscuit,,Biscuits,10,pkt,,6,6,no,
"""


class ImportTests(TestCase):
    def preview(self, text, name="p.csv"):
        rows, cols = importer.read_table(io.BytesIO(text.encode("utf-8")), name)
        return importer.build_preview(rows, cols)

    def test_preview_does_not_write(self):
        clean, summary = self.preview(CSV_OK)
        self.assertEqual(summary["counts"], {"create": 3, "update": 0, "unchanged": 0, "error": 0})
        self.assertEqual(Product.objects.count(), 0)

    def test_apply_creates_products_categories_aliases(self):
        clean, _ = self.preview(CSV_OK)
        report = importer.apply_rows(clean)
        self.assertEqual(report["created"], 3)
        tea = Product.objects.get(external_code="C1")
        self.assertEqual((tea.price, tea.unit, tea.quantity_step, tea.name_ta), (D("250.50"), "KG", D("0.25"), "தேயிலை"))
        self.assertEqual(set(tea.aliases.values_list("text", flat=True)), {"chai", "டீ தூள்"})
        self.assertFalse(Product.objects.get(external_code="C3").is_available)
        self.assertEqual(Category.objects.count(), 3)

    def test_reimport_updates_and_audits_price(self):
        importer.apply_rows(self.preview(CSV_OK)[0])
        changed = CSV_OK.replace("250.50", "260.00")
        clean, summary = self.preview(changed)
        self.assertEqual((summary["counts"]["update"], summary["price_changes"]), (1, 1))
        user = User.objects.create_user("o")
        importer.apply_rows(clean, user)
        self.assertEqual(Product.objects.get(external_code="C1").price, D("260.00"))
        self.assertEqual(PriceChange.objects.get().changed_by, user)
        self.assertEqual(Product.objects.count(), 3)  # no duplicates

    def test_errors_are_reported_and_skipped(self):
        bad = """name,price,unit
Good,10,kg
,10,kg
NoPrice,,kg
BadPrice,abc,kg
Negative,-5,kg
BadUnit,5,bunch
NoUnit,5,
Good,12,kg
ThreeDec,1.234,kg
"""
        clean, summary = self.preview(bad)
        self.assertEqual(summary["counts"]["create"], 1)
        self.assertEqual(summary["counts"]["error"], 8)
        report = importer.apply_rows(clean)
        self.assertEqual((report["created"], report["skipped_errors"]), (1, 8))
        self.assertEqual(Product.objects.count(), 1)

    def test_duplicate_codes_in_file(self):
        clean, summary = self.preview("code,name,price,unit\nA,One,1,kg\nA,Two,2,kg\n")
        self.assertEqual(summary["counts"]["error"], 1)

    def test_rollback_on_unexpected_failure(self):
        from unittest import mock
        clean, _ = self.preview(CSV_OK)
        real = Product.save
        calls = {"n": 0}

        def boom(self_, *a, **k):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("disk full")
            return real(self_, *a, **k)
        with mock.patch.object(Product, "save", boom):
            with self.assertRaises(RuntimeError):
                importer.apply_rows(clean)
        self.assertEqual((Product.objects.count(), Category.objects.count()), (0, 0))

    def test_file_level_errors(self):
        for data, name in ((b"", "e.csv"), (b"foo,bar\n1,2\n", "x.csv"), (b"name,price\n", "h.csv"),
                           (b"name,price,unit\nA,1,kg\n", "bad.exe")):
            with self.assertRaises(importer.ImportFileError):
                importer.read_table(io.BytesIO(data), name)

    def test_excel_import(self):
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active
        ws.append(["Item", "Rate", "UOM", "Group"]); ws.append(["Rice", 55, "kg", "Groceries"])
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        rows, cols = importer.read_table(buf, "p.xlsx")
        clean, summary = importer.build_preview(rows, cols)
        self.assertEqual(summary["counts"]["create"], 1)

    def test_management_command_preview_then_apply(self):
        import os, tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as fh:
            fh.write(CSV_OK); path = fh.name
        try:
            out = io.StringIO()
            call_command("import_products", path, stdout=out)
            self.assertEqual(Product.objects.count(), 0)
            call_command("import_products", path, "--apply", stdout=out)
            self.assertEqual(Product.objects.count(), 3)
        finally:
            os.unlink(path)

    def test_web_import_requires_confirmation(self):
        owner, _, _ = make_users()
        self.client.force_login(owner)
        from django.core.files.uploadedfile import SimpleUploadedFile
        r = self.client.post("/owner/import/", {"file": SimpleUploadedFile("p.csv", CSV_OK.encode())})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Product.objects.count(), 0)
        r = self.client.post(r["Location"], {"action": "apply"})
        self.assertEqual(Product.objects.count(), 3)
        self.client.post(r["Location"], {"action": "apply"})  # second apply is refused
        self.assertEqual(Product.objects.count(), 3)


class SeedAndRolesTests(TestCase):
    def test_seed_demo_and_remove(self):
        call_command("seed_demo", "--force", verbosity=0)
        self.assertEqual(Product.objects.filter(external_code__startswith="DEMO-").count(), 10)
        call_command("seed_demo", "--remove", "--force", verbosity=0)
        self.assertEqual(Product.objects.count(), 0)

    def test_seed_refuses_in_production(self):
        from django.core.management.base import CommandError
        from django.test import override_settings
        with override_settings(DEBUG=False):
            with self.assertRaises(CommandError):
                call_command("seed_demo", verbosity=0)

    def test_demo_data_works_with_voice(self):
        call_command("seed_demo", "--force", verbosity=0)
        from voice import service
        r = service.interpret("ரெண்டு லக்ஸ் சோப்பு, half litre palm oil, 1 kilo seeni")
        self.assertEqual([i["status"] for i in r["items"]], ["ok", "ok", "ok"])
