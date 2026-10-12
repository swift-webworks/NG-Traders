"""
Selling units and safe unit conversion.

Pure Python (no Django imports) so the voice parser and the models can share it.

Key idea: quantity, unit, pack size and product identity are separate concepts.
We only ever convert between units of the SAME measurable dimension
(kg <-> g, litre <-> ml). We never turn a measurement into a piece count.
"""
from decimal import Decimal

PIECE = "PIECE"
PACKET = "PACKET"
BOTTLE = "BOTTLE"
PACK = "PACK"
KG = "KG"
GRAM = "GRAM"
LITRE = "LITRE"
ML = "ML"

COUNT, MASS, VOLUME = "count", "mass", "volume"

# factor = how many base units (gram / millilitre) one of this unit is
UNIT_INFO = {
    PIECE: {"dimension": COUNT, "factor": None, "en": "piece", "en_plural": "pieces", "ta": "எண்ணம்"},
    PACKET: {"dimension": COUNT, "factor": None, "en": "packet", "en_plural": "packets", "ta": "பாக்கெட்"},
    BOTTLE: {"dimension": COUNT, "factor": None, "en": "bottle", "en_plural": "bottles", "ta": "பாட்டில்"},
    PACK: {"dimension": COUNT, "factor": None, "en": "pack", "en_plural": "packs", "ta": "பேக்"},
    KG: {"dimension": MASS, "factor": Decimal(1000), "en": "kg", "en_plural": "kg", "ta": "கிலோ"},
    GRAM: {"dimension": MASS, "factor": Decimal(1), "en": "g", "en_plural": "g", "ta": "கிராம்"},
    LITRE: {"dimension": VOLUME, "factor": Decimal(1000), "en": "litre", "en_plural": "litres", "ta": "லிட்டர்"},
    ML: {"dimension": VOLUME, "factor": Decimal(1), "en": "ml", "en_plural": "ml", "ta": "மி.லி"},
}

UNIT_CHOICES = [(code, f"{info['en']} / {info['ta']}") for code, info in UNIT_INFO.items()]

_THREE_DP = Decimal("0.001")


def dimension(unit):
    return UNIT_INFO[unit]["dimension"]


def is_measure(unit):
    """True for kg/g/litre/ml (sold by measurement), False for counted units."""
    return UNIT_INFO[unit]["dimension"] in (MASS, VOLUME)


def unit_label(unit, quantity=None, lang="en"):
    info = UNIT_INFO[unit]
    if lang == "ta":
        return info["ta"]
    if quantity is not None and quantity != 1:
        return info["en_plural"]
    return info["en"]


def convert_quantity(value, from_unit, to_unit):
    """
    Convert within one dimension. Returns Decimal (3 dp) or None when the
    conversion is not valid or not exactly representable with 3 decimals.
    """
    if from_unit == to_unit:
        return Decimal(value).quantize(_THREE_DP)
    a, b = UNIT_INFO[from_unit], UNIT_INFO[to_unit]
    if a["dimension"] != b["dimension"] or a["factor"] is None:
        return None
    exact = Decimal(value) * a["factor"] / b["factor"]
    rounded = exact.quantize(_THREE_DP)
    if rounded != exact:
        return None
    return rounded


def fmt_qty(value):
    """Decimal -> tidy string: 2.000 -> '2', 0.500 -> '0.5'."""
    d = Decimal(value).normalize()
    return format(d, "f")
