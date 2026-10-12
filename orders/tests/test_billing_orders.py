import json
from decimal import Decimal as D
from unittest import mock

from django.db import IntegrityError
from django.test import TestCase, override_settings

from orders import services
from orders.billing import build_bill, money
from orders.models import Order, OrderItem, PaymentRecord, ShopSettings
from orders.tests.helpers import make_catalogue, make_product, make_users, order_payload


class BillingTests(TestCase):
    def setUp(self):
        self.c = make_catalogue()

    def items(self, **qty):
        return [{"product_id": self.c[k].pk, "quantity": v} for k, v in qty.items()]

    def test_line_and_totals(self):
        b = build_bill(self.items(soap="2", sugar="1.5", oil="0.5"))
        self.assertTrue(b.ok)
        totals = {l.product.name_en: l.line_total for l in b.lines}
        self.assertEqual(totals, {"Lux Soap": D("80.00"), "Sugar": D("68.25"), "Palm Oil": D("60.00")})
        self.assertEqual(b.subtotal, D("208.25"))
        self.assertEqual(b.total, D("208.25"))

    def test_rounding_half_up_with_decimals(self):
        p = make_product("Odd Item", "33.33", "KG", min_q="0.001", step="0.001")
        b = build_bill([{"product_id": p.pk, "quantity": "0.015"}])  # 0.49995 -> 0.50
        self.assertEqual(b.lines[0].line_total, D("0.50"))
        self.assertEqual(money("0.005"), D("0.01"))

    def test_no_float_error(self):
        p = make_product("Penny", "0.10", "PIECE")
        b = build_bill([{"product_id": p.pk, "quantity": "3"}])
        self.assertEqual(b.total, D("0.30"))

    def test_delivery_fee_applies_only_to_delivery(self):
        shop = ShopSettings.load(); shop.delivery_fee = D("30.00"); shop.save()
        self.assertEqual(build_bill(self.items(soap="1"), "PICKUP").total, D("40.00"))
        self.assertEqual(build_bill(self.items(soap="1"), "DELIVERY").total, D("70.00"))

    def test_default_delivery_fee_is_zero(self):
        self.assertEqual(build_bill(self.items(soap="1"), "DELIVERY").delivery_charge, D("0.00"))

    def test_selling_rules_enforced(self):
        self.assertFalse(build_bill(self.items(noodles="4")).ok)
        self.assertTrue(build_bill(self.items(noodles="6")).ok)
        self.assertFalse(build_bill(self.items(sugar="0.1")).ok)
        self.assertFalse(build_bill(self.items(soap="1.5")).ok)
        self.assertFalse(build_bill(self.items(soap="0")).ok)
        self.assertFalse(build_bill(self.items(soap="-2")).ok)
        self.assertFalse(build_bill(self.items(soap="100000")).ok)

    def test_unavailable_blocks_bill(self):
        b = build_bill(self.items(gone="1"))
        self.assertFalse(b.ok)
        self.assertTrue(b.lines[0].errors)

    def test_bad_input_shapes(self):
        for bad in (None, "x", [], [{}], [{"product_id": "a", "quantity": 1}], [{"product_id": 1, "quantity": "nan"}]):
            self.assertFalse(build_bill(bad).ok, bad)

    def test_unknown_product(self):
        self.assertFalse(build_bill([{"product_id": 987654, "quantity": "1"}]).ok)

    def test_duplicate_lines_are_merged(self):
        b = build_bill([{"product_id": self.c["soap"].pk, "quantity": "1"}, {"product_id": self.c["soap"].pk, "quantity": "2"}])
        self.assertEqual((len(b.lines), b.lines[0].quantity), (1, D("3")))

    def test_price_change_is_picked_up_server_side(self):
        before = build_bill(self.items(soap="2"))
        self.c["soap"].price = D("45.00"); self.c["soap"].save()
        after = build_bill(self.items(soap="2"))
        self.assertEqual((before.total, after.total), (D("80.00"), D("90.00")))

    def test_browser_cannot_supply_price(self):
        b = build_bill([{"product_id": self.c["soap"].pk, "quantity": "1", "price": "1.00", "unit_price": "0.01", "total": "0"}])
        self.assertEqual(b.total, D("40.00"))


class OrderCreationTests(TestCase):
    def setUp(self):
        self.c = make_catalogue()
        self.items = [{"product_id": self.c["soap"].pk, "quantity": "2"}, {"product_id": self.c["oil"].pk, "quantity": "0.5"}]

    def test_successful_order(self):
        order, created, err = services.create_order(order_payload(self.items))
        self.assertIsNone(err); self.assertTrue(created)
        self.assertRegex(order.order_number, r"^NG-\d{6}-[A-Z2-9]{5}$")
        self.assertEqual((order.subtotal, order.total, order.status, order.payment_status),
                         (D("140.00"), D("140.00"), "PENDING", "PENDING"))
        self.assertEqual(order.items.count(), 2)
        self.assertEqual(order.status_logs.count(), 1)

    def test_client_total_is_ignored(self):
        order, _, _ = services.create_order(order_payload(self.items, total="1.00", subtotal="1"))
        self.assertEqual(order.total, D("140.00"))

    def test_duplicate_submission_returns_same_order(self):
        o1, c1, _ = services.create_order(order_payload(self.items))
        o2, c2, _ = services.create_order(order_payload(self.items))
        self.assertEqual((o1.pk, c1, c2), (o2.pk, True, False))
        self.assertEqual(Order.objects.count(), 1)

    def test_race_on_idempotency_key(self):
        """A parallel request wins the insert first: we must return its order, not fail."""
        winner, _, _ = services.create_order(order_payload(self.items))
        real_filter = Order.objects.filter
        calls = {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1 and k.get("idempotency_key"):  # first lookup says "not seen yet"
                return Order.objects.none()
            return real_filter(*a, **k)
        with mock.patch.object(Order.objects, "filter", side_effect=flaky):
            order, created, err = services.create_order(order_payload(self.items))
        self.assertIsNone(err); self.assertFalse(created); self.assertEqual(order.pk, winner.pk)
        self.assertEqual(Order.objects.count(), 1)

    def test_failed_save_leaves_nothing_behind(self):
        with mock.patch("orders.services.OrderItem.objects.bulk_create", side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                services.create_order(order_payload(self.items))
        self.assertEqual((Order.objects.count(), OrderItem.objects.count()), (0, 0))

    def test_validation_errors(self):
        cases = {
            "customer_name": dict(customer_name=" "),
            "customer_phone": dict(customer_phone="12345"),
            "delivery_address": dict(fulfilment="DELIVERY", payment_method="UPI", delivery_address="short"),
            "payment_method": dict(payment_method="BITCOIN"),
        }
        for field, over in cases.items():
            _, _, err = services.create_order(order_payload(self.items, **over))
            self.assertIn(field, err["fields"], field)
        self.assertEqual(Order.objects.count(), 0)

    def test_bad_idempotency_key(self):
        for key in ("", "short", "bad key with spaces!!!!!!!!"):
            _, _, err = services.create_order(order_payload(self.items, idempotency_key=key))
            self.assertTrue(err["general"])

    def test_upi_and_cod_off_by_default(self):
        _, _, err = services.create_order(order_payload(self.items, payment_method="UPI"))
        self.assertIn("payment_method", err["fields"])
        _, _, err = services.create_order(order_payload(self.items, fulfilment="DELIVERY", payment_method="COD",
                                                        delivery_address="12 Main Street, Chennai"))
        self.assertIn("payment_method", err["fields"])

    def test_upi_when_owner_enables(self):
        s = ShopSettings.load(); s.enable_upi = True; s.upi_id = "shop@upi"; s.save()
        order, _, err = services.create_order(order_payload(self.items, payment_method="UPI"))
        self.assertIsNone(err); self.assertEqual(order.payment_status, "PENDING")

    def test_delivery_order_with_fee(self):
        s = ShopSettings.load(); s.delivery_fee = D("25.00"); s.enable_cash_on_delivery = True; s.save()
        order, _, err = services.create_order(order_payload(
            self.items, fulfilment="DELIVERY", payment_method="COD", delivery_address="12 Main Street, Chennai"))
        self.assertIsNone(err)
        self.assertEqual((order.subtotal, order.delivery_charge, order.total), (D("140.00"), D("25.00"), D("165.00")))

    def test_pickup_discards_address(self):
        order, _, _ = services.create_order(order_payload(self.items, delivery_address="should vanish"))
        self.assertEqual(order.delivery_address, "")

    def test_invalid_bill_rejected_and_not_saved(self):
        bad = [{"product_id": self.c["noodles"].pk, "quantity": "4"}]
        _, _, err = services.create_order(order_payload(bad))
        self.assertTrue(err["bill"]); self.assertEqual(Order.objects.count(), 0)

    def test_unavailable_item_rejected(self):
        _, _, err = services.create_order(order_payload([{"product_id": self.c["gone"].pk, "quantity": "1"}]))
        self.assertIsNotNone(err); self.assertEqual(Order.objects.count(), 0)

    def test_historical_bill_survives_price_and_name_changes(self):
        order, _, _ = services.create_order(order_payload(self.items))
        soap = self.c["soap"]; soap.price = D("99.00"); soap.name_en = "Renamed"; soap.save()
        order.refresh_from_db()
        line = order.items.get(position=1)
        self.assertEqual((line.name_en, line.unit_price, line.line_total, order.total),
                         ("Lux Soap", D("40.00"), D("80.00"), D("140.00")))

    def test_deleting_product_keeps_history(self):
        order, _, _ = services.create_order(order_payload(self.items))
        self.c["oil"].delete()
        self.assertEqual(order.items.count(), 2)

    def test_phone_normalisation(self):
        for raw in ("+91 98765 43210", "09876543210", "98765-43210"):
            self.assertEqual(services.normalize_phone(raw), "9876543210")
        for raw in ("", "5876543210", "98765", None):
            self.assertIsNone(services.normalize_phone(raw))


@override_settings(RATE_LIMITS_ENABLED=False)
class OrderApiTests(TestCase):
    def setUp(self):
        self.c = make_catalogue()
        self.items = [{"product_id": self.c["soap"].pk, "quantity": "2"}]

    def post(self, url, data):
        return self.client.post(url, json.dumps(data), content_type="application/json")

    def test_bill_endpoint_recalculates(self):
        r = self.post("/api/bill/", {"items": [{"product_id": self.c["soap"].pk, "quantity": "2", "price": "1"}]})
        self.assertEqual(r.json()["total"], "80.00")

    def test_order_endpoint_and_double_tap(self):
        data = order_payload(self.items)
        r1 = self.post("/api/order/", data); r2 = self.post("/api/order/", data)
        self.assertEqual((r1.status_code, r2.status_code), (201, 200))
        self.assertEqual(r1.json()["order_number"], r2.json()["order_number"])
        self.assertTrue(r2.json()["duplicate"])
        self.assertEqual(Order.objects.count(), 1)

    def test_server_error_gives_clear_message_and_saves_nothing(self):
        with mock.patch("orders.api.services.create_order", side_effect=RuntimeError("boom")):
            r = self.post("/api/order/", order_payload(self.items))
        self.assertEqual(r.status_code, 500)
        self.assertIn("not ordered", r.json()["error"]["en"].lower().replace("nothing was ordered", "not ordered"))
        self.assertEqual(Order.objects.count(), 0)

    def test_csrf_enforced_on_api(self):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        r = c.post("/api/order/", json.dumps(order_payload(self.items)), content_type="application/json")
        self.assertEqual(r.status_code, 403)

    def test_home_page_config_is_real_json_object(self):
        """Regression: config must reach the page as an object, not a double-encoded string."""
        import re
        html = self.client.get("/").content.decode()
        raw = re.search(r'<script id="shop-config" type="application/json">(.*?)</script>', html, re.S).group(1)
        cfg = json.loads(raw)
        self.assertIsInstance(cfg, dict)
        self.assertTrue(cfg["delivery_enabled"])
        self.assertEqual(cfg["payment_methods"]["PICKUP"], ["CASH_PICKUP"])
        self.assertEqual(cfg["payment_methods"]["DELIVERY"], [])  # COD and UPI are off until the owner confirms

    def test_home_page_renders(self):
        r = self.client.get("/")
        self.assertContains(r, "mic-btn"); self.assertContains(r, "NG")
        self.assertContains(r, "8610527033")


class CustomerAccessTests(TestCase):
    def setUp(self):
        self.c = make_catalogue()
        self.o1, _, _ = services.create_order(order_payload([{"product_id": self.c["soap"].pk, "quantity": "1"}]))
        self.o2, _, _ = services.create_order(order_payload(
            [{"product_id": self.c["soap"].pk, "quantity": "3"}], idempotency_key="second-key-0123456789abcd",
            customer_name="Other Person", customer_phone="9123456780"))

    def test_token_page_works_and_masks_phone(self):
        r = self.client.get(f"/order/{self.o1.public_token}/")
        self.assertContains(r, self.o1.order_number)
        self.assertNotContains(r, "9876543210")
        self.assertContains(r, "3210")

    def test_claim_paid_form_works_with_csrf_and_page_has_no_conflicting_referrer_meta(self):
        """Regression: a no-referrer meta made browsers send 'Origin: null' and Django rejected the form."""
        from django.test import Client
        s = ShopSettings.load(); s.enable_upi = True; s.upi_id = "shop@upi"; s.save()
        o, _, _ = services.create_order(order_payload(
            [{"product_id": self.c["soap"].pk, "quantity": "1"}], idempotency_key="upi-key-0123456789abcdef",
            payment_method="UPI"))
        c = Client(enforce_csrf_checks=True)
        page = c.get(f"/order/{o.public_token}/")
        self.assertNotContains(page, 'name="referrer"')
        self.assertEqual(page["Referrer-Policy"], "same-origin")
        token = page.cookies["csrftoken"].value
        r = c.post(f"/order/{o.public_token}/paid/", {"reference": "UTR1", "csrfmiddlewaretoken": token})
        self.assertEqual(r.status_code, 302)
        o.refresh_from_db(); self.assertEqual(o.payment_status, "AWAITING_VERIFICATION")

    def test_order_number_alone_gives_no_access(self):
        self.assertEqual(self.client.get(f"/order/{self.o1.order_number}/").status_code, 404)
        self.assertEqual(self.client.get("/order/not-a-token/").status_code, 404)
        self.assertEqual(self.client.get(f"/order/{self.o1.pk}/").status_code, 404)

    def test_cannot_see_other_customers_order(self):
        r = self.client.get(f"/order/{self.o1.public_token}/")
        self.assertNotContains(r, "Other Person"); self.assertNotContains(r, self.o2.order_number)

    @override_settings(RATE_LIMITS_ENABLED=False)
    def test_lookup_needs_matching_phone(self):
        r = self.client.post("/orders/find/", {"order_number": self.o1.order_number, "phone": "9123456780"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "could not find")
        r = self.client.post("/orders/find/", {"order_number": self.o1.order_number.lower(), "phone": "98765 43210"})
        self.assertRedirects(r, f"/order/{self.o1.public_token}/", fetch_redirect_response=False)

    def test_tokens_are_unguessable_and_unique(self):
        self.assertGreaterEqual(len(self.o1.public_token), 30)
        self.assertNotEqual(self.o1.public_token, self.o2.public_token)

    def test_status_json_needs_token(self):
        self.assertEqual(self.client.get(f"/api/order/{self.o1.public_token}/status/").status_code, 200)
        self.assertEqual(self.client.get(f"/api/order/{self.o1.order_number}/status/").status_code, 404)


class StatusAndPaymentTests(TestCase):
    def setUp(self):
        self.c = make_catalogue()
        self.owner, self.staff, self.cust = make_users()
        s = ShopSettings.load(); s.enable_upi = True; s.upi_id = "shop@upi"; s.enable_cash_on_delivery = True
        s.delivery_fee = D("20.00"); s.save()
        self.items = [{"product_id": self.c["soap"].pk, "quantity": "2"}]

    def new(self, **over):
        key = over.pop("idempotency_key", None) or f"key-{Order.objects.count():016d}"
        o, _, err = services.create_order(order_payload(self.items, idempotency_key=key, **over))
        assert not err, err
        return o

    def test_pickup_status_flow(self):
        o = self.new()
        for status in ("ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
            services.change_status(o.pk, status, self.owner)
        services.collect_cash(o.pk, self.owner)
        o = services.change_status(o.pk, "COMPLETED", self.owner)
        self.assertEqual((o.status, o.payment_status), ("COMPLETED", "PAID"))

    def test_delivery_flow_uses_out_for_delivery(self):
        o = self.new(fulfilment="DELIVERY", payment_method="COD", delivery_address="12 Main Street, Chennai")
        services.change_status(o.pk, "ACCEPTED", self.owner); services.change_status(o.pk, "PREPARING", self.owner)
        with self.assertRaises(services.TransitionError):
            services.change_status(o.pk, "READY_FOR_PICKUP", self.owner)
        services.change_status(o.pk, "OUT_FOR_DELIVERY", self.owner)

    def test_invalid_transitions(self):
        o = self.new()
        for bad in ("PREPARING", "COMPLETED", "READY_FOR_PICKUP", "PENDING", "NONSENSE"):
            with self.assertRaises(services.TransitionError):
                services.change_status(o.pk, bad, self.owner)

    def test_reject_needs_reason_and_is_final(self):
        o = self.new()
        with self.assertRaises(services.TransitionError):
            services.change_status(o.pk, "REJECTED", self.owner, "")
        services.change_status(o.pk, "REJECTED", self.owner, "Out of stock")
        with self.assertRaises(services.TransitionError):
            services.change_status(o.pk, "ACCEPTED", self.owner)

    def test_cannot_complete_unpaid_order(self):
        o = self.new()
        for s in ("ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
            services.change_status(o.pk, s, self.owner)
        with self.assertRaises(services.TransitionError):
            services.change_status(o.pk, "COMPLETED", self.owner)

    def test_upi_claim_is_not_paid(self):
        o = self.new(payment_method="UPI")
        o = services.customer_claims_payment(o.pk, "UTR12345")
        self.assertEqual(o.payment_status, "AWAITING_VERIFICATION")
        self.assertNotEqual(o.payment_status, "PAID")

    def test_owner_verifies_upi(self):
        o = self.new(payment_method="UPI")
        services.customer_claims_payment(o.pk, "UTR12345")
        o = services.verify_upi_payment(o.pk, self.owner)
        self.assertEqual(o.payment_status, "PAID")
        rec = PaymentRecord.objects.filter(order=o, action="VERIFIED_UPI").get()
        self.assertEqual((rec.recorded_by, rec.amount, rec.reference), (self.owner, o.total, "UTR12345"))
        with self.assertRaises(services.TransitionError):  # cannot verify twice
            services.verify_upi_payment(o.pk, self.owner)

    def test_reject_payment_then_reverify_possible(self):
        o = self.new(payment_method="UPI")
        with self.assertRaises(services.TransitionError):
            services.reject_payment(o.pk, self.owner, "")
        o = services.reject_payment(o.pk, self.owner, "No money received")
        self.assertEqual(o.payment_status, "FAILED")
        self.assertEqual(services.verify_upi_payment(o.pk, self.owner).payment_status, "PAID")

    def test_cash_rules(self):
        cash = self.new()
        upi = self.new(payment_method="UPI")
        with self.assertRaises(services.TransitionError):
            services.collect_cash(upi.pk, self.owner)
        with self.assertRaises(services.TransitionError):
            services.verify_upi_payment(cash.pk, self.owner)
        self.assertEqual(services.collect_cash(cash.pk, self.owner).payment_status, "PAID")
        with self.assertRaises(services.TransitionError):
            services.collect_cash(cash.pk, self.owner)

    def test_no_payment_on_rejected_order(self):
        o = self.new(payment_method="UPI")
        services.change_status(o.pk, "REJECTED", self.owner, "Closed")
        with self.assertRaises(services.TransitionError):
            services.verify_upi_payment(o.pk, self.owner)
        with self.assertRaises(services.TransitionError):
            services.customer_claims_payment(o.pk)

    def test_refund_flow_is_manual_and_only_after_paid_rejection(self):
        o = self.new(payment_method="UPI")
        with self.assertRaises(services.TransitionError):
            services.confirm_refund(o.pk, self.owner)
        services.verify_upi_payment(o.pk, self.owner)
        services.change_status(o.pk, "ACCEPTED", self.owner)
        o = services.change_status(o.pk, "CANCELLED", self.owner, "Customer asked")
        self.assertTrue(o.refund_due); self.assertEqual(o.payment_status, "PAID")  # NOT auto-refunded
        o = services.confirm_refund(o.pk, self.owner, "REF1")
        self.assertEqual(o.payment_status, "REFUNDED")

    def test_printing_does_not_change_state(self):
        o = self.new()
        self.client.force_login(self.owner)
        r = self.client.get(f"/owner/orders/{o.pk}/print/")
        self.assertContains(r, o.order_number); self.assertContains(r, "@page")
        self.assertContains(r, "not</strong> been received")
        o.refresh_from_db()
        self.assertEqual((o.status, o.payment_status), ("PENDING", "PENDING"))

    def test_print_shows_correct_totals(self):
        o = self.new(fulfilment="DELIVERY", payment_method="COD", delivery_address="12 Main Street, Chennai")
        self.client.force_login(self.owner)
        r = self.client.get(f"/owner/orders/{o.pk}/print/")
        for text in ("80.00", "20.00", "100.00", "Lux Soap", "8610527033", "6369603873"):
            self.assertContains(r, text)


class OwnerPermissionTests(TestCase):
    def setUp(self):
        self.c = make_catalogue()
        self.owner, self.staff, self.cust = make_users()
        self.order, _, _ = services.create_order(order_payload([{"product_id": self.c["soap"].pk, "quantity": "1"}]))

    def test_anonymous_redirected_to_login(self):
        for url in ("/owner/", f"/owner/orders/{self.order.pk}/", f"/owner/orders/{self.order.pk}/print/",
                    "/owner/api/summary/", "/owner/import/"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url); self.assertIn("/owner/login/", r["Location"])

    def test_customer_account_forbidden(self):
        self.client.force_login(self.cust)
        for url in ("/owner/", f"/owner/orders/{self.order.pk}/", "/owner/api/summary/", "/admin/"):
            self.assertIn(self.client.get(url).status_code, (302, 403), url)
        self.assertEqual(self.client.get("/owner/").status_code, 403)

    def test_staff_can_manage_orders_but_not_verify_payments(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get("/owner/").status_code, 200)
        r = self.client.post(f"/owner/orders/{self.order.pk}/", {"action": "cash"})
        self.assertEqual(r.status_code, 403)
        self.order.refresh_from_db(); self.assertEqual(self.order.payment_status, "PENDING")
        r = self.client.post(f"/owner/orders/{self.order.pk}/", {"action": "status", "status": "ACCEPTED"})
        self.assertEqual(r.status_code, 302)
        self.order.refresh_from_db(); self.assertEqual(self.order.status, "ACCEPTED")

    def test_staff_cannot_import_or_edit_prices(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get("/owner/import/").status_code, 403)
        soap = self.c["soap"]
        url = f"/admin/catalogue/product/{soap.pk}/change/"
        self.assertEqual(self.client.get(url).status_code, 200)  # read-only view is allowed
        data = {"category": soap.category_id, "name_en": soap.name_en, "name_ta": "", "price": "1.00",
                "unit": soap.unit, "min_quantity": "1", "quantity_step": "1", "pack_description": "",
                "is_available": "on", "aliases-TOTAL_FORMS": "0", "aliases-INITIAL_FORMS": "0"}
        self.assertEqual(self.client.post(url, data).status_code, 403)
        soap.refresh_from_db(); self.assertEqual(soap.price, D("40.00"))

    def test_owner_full_flow_via_web(self):
        self.client.force_login(self.owner)
        self.assertContains(self.client.get("/owner/"), self.order.order_number)
        self.client.post(f"/owner/orders/{self.order.pk}/", {"action": "status", "status": "ACCEPTED"})
        self.client.post(f"/owner/orders/{self.order.pk}/", {"action": "cash"})
        self.order.refresh_from_db()
        self.assertEqual((self.order.status, self.order.payment_status), ("ACCEPTED", "PAID"))
        self.assertEqual(self.client.get("/owner/api/summary/").json()["latest_id"], self.order.pk)

    def test_csrf_enforced_on_owner_actions(self):
        from django.test import Client
        c = Client(enforce_csrf_checks=True); c.force_login(self.owner)
        r = c.post(f"/owner/orders/{self.order.pk}/", {"action": "status", "status": "ACCEPTED"})
        self.assertEqual(r.status_code, 403)

    def test_orders_are_view_only_in_django_admin(self):
        from django.contrib import admin
        from django.test import RequestFactory
        ma = admin.site._registry[Order]
        req = RequestFactory().get("/"); req.user = self.owner
        self.assertFalse(ma.has_change_permission(req)); self.assertFalse(ma.has_delete_permission(req))
        self.assertFalse(ma.has_add_permission(req))

    def test_login_works(self):
        r = self.client.post("/owner/login/", {"username": "owner", "password": "wrong"})
        self.assertContains(r, "Wrong username or password")
        r = self.client.post("/owner/login/", {"username": "owner", "password": "pw-owner-12345"})
        self.assertRedirects(r, "/owner/", fetch_redirect_response=False)
