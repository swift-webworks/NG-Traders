"""
Number words (English, Tamil script, and Tamil written in English letters) and unit words.
Pure Python, no Django. Extend the dictionaries below as real customer phrases are collected
during the supervised pilot.
"""
from decimal import Decimal, InvalidOperation

from catalogue import units as U

D = Decimal

_UNITS_EN = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}

_TAMIL = {
    # Tamil script
    "ஒன்று": 1, "ஒரு": 1, "ஒண்ணு": 1, "ஒன்னு": 1,
    "இரண்டு": 2, "ரெண்டு": 2, "ரண்டு": 2, "இரு": 2,
    "மூன்று": 3, "மூணு": 3, "மூனு": 3,
    "நான்கு": 4, "நாலு": 4,
    "ஐந்து": 5, "அஞ்சு": 5,
    "ஆறு": 6, "ஏழு": 7, "எட்டு": 8,
    "ஒன்பது": 9, "ஒம்பது": 9,
    "பத்து": 10, "பதினொன்று": 11, "பன்னிரண்டு": 12, "பதினைந்து": 15,
    "இருபது": 20, "முப்பது": 30, "நாற்பது": 40, "ஐம்பது": 50, "அறுபது": 60, "நூறு": 100,
    # Tamil in English letters (common spoken/typed spellings)
    "onnu": 1, "oru": 1, "ondru": 1,
    "rendu": 2, "randu": 2, "irandu": 2,
    "moonu": 3, "munu": 3, "moondru": 3,
    "naalu": 4, "nalu": 4, "naangu": 4,
    "anju": 5, "ainthu": 5, "aindhu": 5,
    "aaru": 6, "aru": 6, "ezhu": 7, "elu": 7, "ettu": 8,
    "onbathu": 9, "ombathu": 9, "pathu": 10, "paththu": 10,
    "irubathu": 20, "muppathu": 30,
}

NUMBER_WORDS = {**{k: D(v) for k, v in _UNITS_EN.items()}, **{k: D(v) for k, v in _TAMIL.items()}}
TENS = {D(v) for v in (20, 30, 40, 50, 60, 70, 80, 90)}

# Fractions that may stand alone before a unit ("half litre", "அரை கிலோ")
FRACTION_WORDS = {
    "half": D("0.5"), "அரை": D("0.5"), "arai": D("0.5"), "ara": D("0.5"),
    "quarter": D("0.25"), "கால்": D("0.25"), "kaal": D("0.25"), "kal": D("0.25"),
    "முக்கால்": D("0.75"), "mukkal": D("0.75"), "mukkaal": D("0.75"),
}
# One-and-a-half style single words
COMPOUND_FRACTIONS = {
    "ஒன்றரை": D("1.5"), "ஒண்ணரை": D("1.5"), "ஒன்னரை": D("1.5"), "onnarai": D("1.5"), "ondrarai": D("1.5"),
    "இரண்டரை": D("2.5"), "ரெண்டரை": D("2.5"), "rendarai": D("2.5"), "irandarai": D("2.5"),
}

_UNIT_WORDS = {
    U.KG: ["kg", "kgs", "kilo", "kilos", "kilogram", "kilograms", "கிலோ", "கிலோவ", "கிலோகிராம்", "கேஜி", "kilogramme"],
    U.GRAM: ["g", "gm", "gms", "gram", "grams", "grm", "கிராம்", "கிராமு", "கிராம", "கிராம்ஸ்"],
    U.LITRE: ["l", "lt", "ltr", "ltrs", "litre", "litres", "liter", "liters", "லிட்டர்", "லிட்டரு", "லிட்டர", "லீட்டர்", "லிடர்"],
    U.ML: ["ml", "mls", "millilitre", "millilitres", "milliliter", "milliliters", "மில்லி", "மிலி", "மி.லி", "எம்எல்"],
    U.PIECE: ["piece", "pieces", "pc", "pcs", "nos", "பீஸ்", "எண்ணம்", "நம்பர்"],
    U.PACKET: ["packet", "packets", "pkt", "pkts", "பாக்கெட்", "பாக்கெட்டு", "பாக்கெட"],
    U.BOTTLE: ["bottle", "bottles", "பாட்டில்", "பாட்டிலு", "பாட்டில"],
    U.PACK: ["pack", "packs", "பேக்", "பேக்கு"],
}
UNIT_WORDS = {w: code for code, words in _UNIT_WORDS.items() for w in words}

STOP_WORDS = {
    "of", "the", "please", "pls", "give", "me", "i", "want", "need", "to", "buy", "add", "also", "and", "then",
    "kudunga", "kodunga", "venum", "venumm", "vendum", "venuma", "thaanga", "thanga", "ku", "for", "a", "an",
    "வேண்டும்", "வேணும்", "குடுங்க", "கொடுங்க", "தாங்க", "தாருங்கள்", "போடுங்க", "வேண்டும",
    "மற்றும்", "அப்புறம்", "பிறகு", "and", "ம்",
}

# Words that separate two order items when the left side already has a quantity
CONNECTORS = {"and", "then", "also", "மற்றும்", "அப்புறம்", "பிறகு", "&", "plus", "aur"}


def _to_decimal(tok):
    try:
        if "/" in tok:
            a, b = tok.split("/", 1)
            return D(a) / D(b) if D(b) != 0 else None
        d = D(tok)
        return d if d.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def is_numeric_token(tok):
    return bool(tok) and all(c.isdigit() or c in "./" for c in tok) and any(c.isdigit() for c in tok)


def unit_at(tokens, i):
    """Return unit code if tokens[i] is a unit word, else None."""
    if i < len(tokens):
        return UNIT_WORDS.get(tokens[i])
    return None


def parse_number(tokens, i):
    """
    Try to read a number starting at tokens[i].
    Returns (Decimal, tokens_consumed) or None.
    Handles digits, number words, 'half', 'one and a half', 'twenty five', 'oru arai'...
    """
    if i >= len(tokens):
        return None
    t = tokens[i]

    if t in COMPOUND_FRACTIONS:
        return COMPOUND_FRACTIONS[t], 1

    if is_numeric_token(t):
        val = _to_decimal(t)
        if val is None:
            return None
        used = 1
        # "1 and a half" / "1 and half"
        rest = tokens[i + 1:i + 4]
        if rest[:3] == ["and", "a", "half"]:
            return val + D("0.5"), 4
        if rest[:2] == ["and", "half"]:
            return val + D("0.5"), 3
        return val, used

    if t in FRACTION_WORDS:
        return FRACTION_WORDS[t], 1

    if t in ("a", "an"):
        # only a number when a unit follows: "a litre palm oil"
        return (D(1), 1) if unit_at(tokens, i + 1) else None

    if t in NUMBER_WORDS:
        val = NUMBER_WORDS[t]
        used = 1
        # twenty five
        if val in TENS and i + 1 < len(tokens) and tokens[i + 1] in _UNITS_EN and 1 <= _UNITS_EN[tokens[i + 1]] <= 9:
            val += D(_UNITS_EN[tokens[i + 1]])
            used = 2
        # "one and a half", "oru arai" (one half), "two and half"
        nxt = tokens[i + used:i + used + 3]
        if nxt[:3] == ["and", "a", "half"]:
            return val + D("0.5"), used + 3
        if nxt[:2] == ["and", "half"]:
            return val + D("0.5"), used + 2
        if nxt[:1] and nxt[0] in ("arai", "அரை") and unit_at(tokens, i + used + 1):
            return val + D("0.5"), used + 1
        return val, used
    return None
