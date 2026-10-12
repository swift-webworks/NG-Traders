"""Voice interpretation against a real (test) catalogue, incl. the HTTP endpoints."""
import json
from decimal import Decimal as D

from django.test import TestCase, override_settings

from orders.tests.helpers import make_catalogue, make_product
from voice import service


def by_status(result):
    return [i["status"] for i in result["items"]]


@override_settings(RATE_LIMITS_ENABLED=False)
class InterpretTests(TestCase):
    def setUp(self):
        self.c = make_catalogue()

    def test_two_lux_soaps(self):
        r = service.interpret("Two Lux soaps")
        (it,) = r["items"]
        self.assertEqual((it["status"], it["quantity"], it["product"]["id"]), ("ok", "2", self.c["soap"].pk))

    def test_three_milk_biscuits(self):
        (it,) = service.interpret("three milk biscuits")["items"]
        self.assertEqual((it["status"], it["quantity"], it["product"]["id"]), ("ok", "3", self.c["biscuit"].pk))

    def test_half_litre_palm_oil(self):
        (it,) = service.interpret("Half litre palm oil")["items"]
        self.assertEqual((it["status"], it["quantity"]), ("ok", "0.5"))

    def test_palm_oil_two_litres(self):
        (it,) = service.interpret("Palm oil, two litres")["items"]
        self.assertEqual((it["status"], it["quantity"]), ("ok", "2"))

    def test_conflict_is_never_guessed(self):
        (it,) = service.interpret("Half litre palm oil, two litres.")["items"]
        self.assertEqual(it["status"], "conflict")
        self.assertIsNone(it["quantity"])
        self.assertEqual(sorted(o["quantity"] for o in it["options"]), ["0.5", "2"])

    def test_tamil_order(self):
        (it,) = service.interpret("ரெண்டு லக்ஸ் சோப்பு")["items"]
        self.assertEqual((it["status"], it["quantity"], it["product"]["id"]), ("ok", "2", self.c["soap"].pk))

    def test_tamil_half_litre_oil(self):
        (it,) = service.interpret("அரை லிட்டர் பாமாயில்")["items"]
        self.assertEqual((it["status"], it["quantity"], it["product"]["id"]), ("ok", "0.5", self.c["oil"].pk))

    def test_ml_converted_to_litres(self):
        (it,) = service.interpret("500 ml palm oil")["items"]
        self.assertEqual((it["status"], it["quantity"]), ("ok", "0.5"))

    def test_grams_converted_to_kg(self):
        (it,) = service.interpret("500 grams sugar")["items"]
        self.assertEqual((it["status"], it["quantity"]), ("ok", "0.5"))

    def test_alias_match(self):
        (it,) = service.interpret("1 kg seeni")["items"]
        self.assertEqual((it["status"], it["product"]["id"]), ("ok", self.c["sugar"].pk))

    def test_multiple_products_independent(self):
        r = service.interpret("2 lux soap, 3 milk biscuits and half litre palm oil, two litres")
        self.assertEqual(by_status(r), ["ok", "ok", "conflict"])

    def test_missing_quantity_asks(self):
        (it,) = service.interpret("lux soap")["items"]
        self.assertEqual(it["status"], "needs_quantity")
        self.assertIsNone(it["quantity"])

    def test_measured_product_without_unit_asks(self):
        (it,) = service.interpret("2 palm oil")["items"]
        self.assertEqual(it["status"], "needs_unit")
        self.assertIsNone(it["quantity"])

    def test_measure_not_converted_to_count(self):
        (it,) = service.interpret("2 kg lux soap")["items"]
        self.assertEqual(it["status"], "unit_mismatch")
        self.assertIsNone(it["quantity"])

    def test_wrong_dimension_rejected(self):
        (it,) = service.interpret("2 litres sugar")["items"]
        self.assertEqual(it["status"], "unit_mismatch")

    def test_min_quantity_and_step_rules(self):
        (it,) = service.interpret("3 instant noodles")["items"]
        self.assertEqual(it["status"], "invalid_rules")
        self.assertEqual(it["suggested_quantity"], "6")
        (ok,) = service.interpret("12 instant noodles")["items"]
        self.assertEqual((ok["status"], ok["quantity"]), ("ok", "12"))
        (bad,) = service.interpret("0.3 kg sugar")["items"]
        self.assertEqual(bad["status"], "invalid_rules")

    def test_unavailable_product(self):
        (it,) = service.interpret("2 out of stock item")["items"]
        self.assertEqual(it["status"], "unavailable")

    def test_unknown_product(self):
        (it,) = service.interpret("2 diamond rings")["items"]
        self.assertEqual(it["status"], "unknown_product")

    def test_empty_catalogue(self):
        from catalogue.models import Product
        Product.objects.all().delete()
        (it,) = service.interpret("2 lux soap")["items"]
        self.assertEqual(it["status"], "unknown_product")

    def test_ambiguous_similar_products(self):
        make_product("Lux Soap Rose", "42.00", name_ta="லக்ஸ் ரோஸ்")
        (it,) = service.interpret("2 lux")["items"]
        self.assertEqual(it["status"], "ambiguous_product")
        self.assertGreaterEqual(len(it["candidates"]), 2)

    def test_new_alias_is_picked_up_without_restart(self):
        self.assertEqual(service.interpret("2 sabun")["items"][0]["status"], "unknown_product")
        from catalogue.models import ProductAlias
        ProductAlias.objects.create(product=self.c["soap"], text="sabun")
        self.assertEqual(service.interpret("2 sabun")["items"][0]["status"], "ok")

    def test_price_is_a_string_from_the_database(self):
        (it,) = service.interpret("1 lux soap")["items"]
        self.assertEqual(it["product"]["price"], "40.00")


@override_settings(RATE_LIMITS_ENABLED=False)
class EndpointTests(TestCase):
    def setUp(self):
        self.c = make_catalogue()

    def post(self, url, data):
        return self.client.post(url, json.dumps(data), content_type="application/json")

    def test_parse_endpoint(self):
        r = self.post("/api/parse/", {"text": "2 lux soap"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["items"][0]["status"], "ok")

    def test_parse_rejects_empty_and_bad_json(self):
        self.assertEqual(self.post("/api/parse/", {"text": "  "}).status_code, 400)
        self.assertEqual(self.client.post("/api/parse/", "not json", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.get("/api/parse/").status_code, 405)

    def test_resolve_revalidates_typed_quantity(self):
        r = self.post("/api/resolve/", {"product_id": self.c["noodles"].pk, "quantity": "4"})
        self.assertEqual(r.json()["item"]["status"], "invalid_rules")
        r = self.post("/api/resolve/", {"product_id": self.c["noodles"].pk, "quantity": "6"})
        self.assertEqual(r.json()["item"]["status"], "ok")

    def test_resolve_unavailable_cannot_be_forced(self):
        r = self.post("/api/resolve/", {"product_id": self.c["gone"].pk, "quantity": "1"})
        self.assertEqual(r.json()["item"]["status"], "unavailable")

    def test_resolve_unknown_id(self):
        self.assertEqual(self.post("/api/resolve/", {"product_id": 99999}).status_code, 404)

    def test_search(self):
        r = self.client.get("/api/products/search/", {"q": "lux"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["products"])

    @override_settings(RATE_LIMITS_ENABLED=True)
    def test_rate_limit(self):
        from django.core.cache import cache
        cache.clear()
        codes = [self.post("/api/parse/", {"text": "2 lux soap"}).status_code for _ in range(45)]
        self.assertIn(429, codes)
        cache.clear()
