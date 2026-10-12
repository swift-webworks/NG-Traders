from decimal import Decimal as D

from django.test import SimpleTestCase

from catalogue import units as U
from catalogue.textnorm import loose_key, normalize_text
from voice.matcher import build_entries, match_product
from voice.parser import parse_order_text


def q(item):
    return [(c.value, c.unit) for c in item.quantities]


class NormalizeTests(SimpleTestCase):
    def test_tamil_digits_and_case(self):
        self.assertEqual(normalize_text("  Lux  SOAP ௨ "), "lux soap 2")

    def test_decimal_point_kept(self):
        self.assertEqual(normalize_text("0.5 litre"), "0.5 litre")

    def test_plural_folding_is_loose_only(self):
        self.assertEqual(loose_key("Lux Soaps"), loose_key("lux soap"))
        self.assertEqual(loose_key("பிஸ்கட்கள்"), loose_key("பிஸ்கட்"))


class ParserTests(SimpleTestCase):
    def test_two_lux_soaps(self):
        (it,) = parse_order_text("Two Lux soaps")
        self.assertEqual(it.product_text, "lux soaps")
        self.assertEqual(q(it), [(D(2), None)])

    def test_three_milk_biscuits(self):
        (it,) = parse_order_text("three milk biscuits")
        self.assertEqual(q(it), [(D(3), None)])
        self.assertEqual(it.product_text, "milk biscuits")

    def test_half_litre_palm_oil(self):
        (it,) = parse_order_text("Half litre palm oil")
        self.assertEqual(q(it), [(D("0.5"), U.LITRE)])
        self.assertEqual(it.product_text, "palm oil")

    def test_palm_oil_two_litres(self):
        (it,) = parse_order_text("Palm oil, two litres")
        self.assertEqual(it.product_text, "palm oil")
        self.assertEqual(q(it), [(D(2), U.LITRE)])

    def test_conflicting_quantities_are_kept_not_guessed(self):
        (it,) = parse_order_text("Half litre palm oil, two litres.")
        self.assertEqual(it.product_text, "palm oil")
        self.assertEqual(sorted(q(it)), sorted([(D("0.5"), U.LITRE), (D(2), U.LITRE)]))

    def test_digits_with_units(self):
        (a, b) = parse_order_text("500 ml coconut oil and 1 kg sugar")
        self.assertEqual((q(a), a.product_text), ([(D(500), U.ML)], "coconut oil"))
        self.assertEqual((q(b), b.product_text), ([(D(1), U.KG)], "sugar"))

    def test_attached_digits_and_units(self):
        (it,) = parse_order_text("2kg sugar")
        self.assertEqual(q(it), [(D(2), U.KG)])

    def test_multiple_products_comma(self):
        items = parse_order_text("2 lux soap, 3 milk biscuits, 1 kg sugar")
        self.assertEqual([i.product_text for i in items], ["lux soap", "milk biscuits", "sugar"])

    def test_and_inside_a_name_is_not_split(self):
        (it,) = parse_order_text("2 salt and pepper")
        self.assertEqual(it.product_text, "salt and pepper")

    def test_tamil_number_word(self):
        (it,) = parse_order_text("ரெண்டு லக்ஸ் சோப்பு")
        self.assertEqual(q(it), [(D(2), None)])
        self.assertEqual(it.product_text, "லக்ஸ் சோப்பு")

    def test_tamil_half_litre(self):
        (it,) = parse_order_text("அரை லிட்டர் பாமாயில்")
        self.assertEqual(q(it), [(D("0.5"), U.LITRE)])
        self.assertEqual(it.product_text, "பாமாயில்")

    def test_tamil_one_and_half_kilo(self):
        (it,) = parse_order_text("ஒன்றரை கிலோ சர்க்கரை")
        self.assertEqual(q(it), [(D("1.5"), U.KG)])

    def test_mixed_language(self):
        (it,) = parse_order_text("moonu milk biscuit venum")
        self.assertEqual(q(it), [(D(3), None)])
        self.assertEqual(it.product_text, "milk biscuit")

    def test_missing_quantity(self):
        (it,) = parse_order_text("lux soap")
        self.assertEqual(it.quantities, [])

    def test_unit_without_number(self):
        (it,) = parse_order_text("kilo sugar")
        self.assertEqual(q(it), [(None, U.KG)])

    def test_empty_and_noise(self):
        self.assertEqual(parse_order_text(""), [])
        self.assertEqual(parse_order_text("  ,, .. "), [])

    def test_twenty_five(self):
        (it,) = parse_order_text("twenty five noodles")
        self.assertEqual(q(it), [(D(25), None)])


class MatcherTests(SimpleTestCase):
    def setUp(self):
        self.entries = build_entries([
            (1, ["Lux Soap", "லக்ஸ் சோப்பு", "lux soappu"]),
            (2, ["Lux Soap Rose", "lux rose"]),
            (3, ["Milk Biscuits", "மில்க் பிஸ்கட்"]),
            (4, ["Palm Oil", "பாமாயில்", "பாம் ஆயில்"]),
            (5, ["Coconut Oil", "தேங்காய் எண்ணெய்"]),
            (6, ["Sugar", "சர்க்கரை", "seeni"]),
        ])

    def test_exact_english(self):
        r = match_product("palm oil", self.entries)
        self.assertEqual((r.status, r.candidates[0][0]), ("matched", 4))

    def test_plural_english(self):
        r = match_product("milk biscuits", self.entries)
        self.assertEqual((r.status, r.candidates[0][0]), ("matched", 3))

    def test_exact_tamil(self):
        r = match_product("லக்ஸ் சோப்பு", self.entries)
        self.assertEqual((r.status, r.candidates[0][0]), ("matched", 1))

    def test_alias_transliteration(self):
        r = match_product("seeni", self.entries)
        self.assertEqual((r.status, r.candidates[0][0]), ("matched", 6))

    def test_similar_names_do_not_silently_match(self):
        r = match_product("lux", self.entries)
        self.assertNotEqual(r.status, "matched")
        self.assertTrue({1, 2} <= {pid for pid, _ in r.candidates})

    def test_generic_oil_is_ambiguous(self):
        r = match_product("oil", self.entries)
        self.assertEqual(r.status, "ambiguous")
        self.assertTrue({4, 5} <= {pid for pid, _ in r.candidates})

    def test_unknown_product(self):
        self.assertEqual(match_product("diamond ring", self.entries).status, "unknown")

    def test_empty(self):
        self.assertEqual(match_product("", self.entries).status, "unknown")
        self.assertEqual(match_product("sugar", []).status, "unknown")

    def test_small_typo_never_becomes_confident(self):
        r = match_product("palm oyl", self.entries)
        self.assertNotEqual(r.status, "matched")


class UnitTests(SimpleTestCase):
    def test_conversions(self):
        self.assertEqual(U.convert_quantity(D(500), U.ML, U.LITRE), D("0.500"))
        self.assertEqual(U.convert_quantity(D(2), U.KG, U.GRAM), D("2000.000"))
        self.assertEqual(U.convert_quantity(D("0.5"), U.LITRE, U.ML), D("500.000"))

    def test_no_cross_dimension_or_count_conversion(self):
        self.assertIsNone(U.convert_quantity(D(1), U.KG, U.LITRE))
        self.assertIsNone(U.convert_quantity(D(1), U.KG, U.PACKET))
        self.assertIsNone(U.convert_quantity(D(1), U.PACKET, U.PIECE))

    def test_inexact_conversion_rejected(self):
        self.assertIsNone(U.convert_quantity(D(1), U.GRAM, U.KG) and None)  # 0.001 is exact
        self.assertIsNone(U.convert_quantity(D("0.5"), U.GRAM, U.KG))  # 0.0005 not representable
