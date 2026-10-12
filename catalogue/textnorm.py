"""
Careful text normalisation for matching (pure Python, no Django).

We deliberately keep this gentle:
  * Unicode NFC, case-folding, removal of zero-width characters
  * Tamil digits -> ASCII digits
  * punctuation -> space (Tamil letters, vowel signs and the pulli are kept)
We do NOT transliterate, drop Tamil suffixes or rewrite words here, because that
could change what a product name means. A second, looser key (`loose_key`) is
used only as an additional comparison key.
"""
import re
import unicodedata

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍﻿"), None)
_TAMIL_DIGITS = {ord(c): str(i) for i, c in enumerate("௦௧௨௩௪௫௬௭௮௯")}
_FRACTIONS = {"½": " 0.5 ", "¼": " 0.25 ", "¾": " 0.75 "}


def pre_normalize(text):
    """NFC, casefold, strip zero-width chars, Tamil digits -> ASCII, unicode fractions -> decimals."""
    text = unicodedata.normalize("NFC", text or "")
    text = text.translate(_ZERO_WIDTH).translate(_TAMIL_DIGITS)
    for sym, rep in _FRACTIONS.items():
        text = text.replace(sym, rep)
    return text.casefold()


def normalize_text(text):
    """Lowercase words separated by single spaces. Decimal points between digits survive."""
    text = pre_normalize(text)
    out = []
    n = len(text)
    for i, ch in enumerate(text):
        cat = unicodedata.category(ch)
        if cat[0] in ("L", "M", "N"):
            out.append(ch)
        elif ch == "." and 0 < i < n - 1 and text[i - 1].isdigit() and text[i + 1].isdigit():
            out.append(ch)
        elif ch == "/" and 0 < i < n - 1 and text[i - 1].isdigit() and text[i + 1].isdigit():
            out.append(ch)
        else:
            out.append(" ")
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _loose_token(tok):
    # English plural: soaps -> soap, biscuits -> biscuit (not for very short words)
    if tok.isascii() and tok.isalpha() and len(tok) > 3:
        if tok.endswith("ies") and len(tok) > 4:
            return tok[:-3] + "y"
        if tok.endswith("s") and not tok.endswith("ss"):
            return tok[:-1]
    # Tamil plural suffix கள்
    if tok.endswith("கள்") and len(tok) > 5:
        return tok[:-3]
    return tok


def loose_key(text):
    """Comparison-only key: normalised text with simple plural folding."""
    return " ".join(_loose_token(t) for t in normalize_text(text).split())


def tokens(text):
    return normalize_text(text).split()
