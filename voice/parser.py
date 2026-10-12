"""
Order-sentence parser: free text -> list of (quantities, product words).

Pure Python, no database. It does NOT decide which product is meant (that is
`matcher.py`) and does NOT decide whether a quantity is valid for a product
(that is `service.py` + catalogue rules). It only separates:

    "half litre palm oil, two litres"
        -> item 1: product words "palm oil", quantities [0.5 litre, 2 litre]   (a conflict!)

Rules:
  * Items are separated by commas / new lines / full stops, and by words like "and"
    ONLY when the part before already contains a quantity ("salt and pepper" stays whole).
  * A part with a quantity but no product words ("two litres") is attached to the
    previous item as an extra quantity, so conflicts are detected rather than guessed.
  * A spoken measure is never turned into a count here.
"""
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional

from catalogue.textnorm import normalize_text, pre_normalize

from .numbers import CONNECTORS, STOP_WORDS, is_numeric_token, parse_number, unit_at, UNIT_WORDS

_SEGMENT_SPLIT = re.compile(r"[,;\n।!?]+|(?<!\d)\.(?!\d)")
_DIGIT_LETTER = re.compile(r"(?<=\d)(?=[^\W\d_])|(?<=[^\W\d_])(?=\d)")


@dataclass(frozen=True)
class QuantityCandidate:
    value: Optional[Decimal]  # None when only a unit was heard ("kilo sugar")
    unit: Optional[str]       # canonical unit code or None
    raw: str = ""


@dataclass
class ParsedItem:
    raw: str
    product_text: str
    quantities: List[QuantityCandidate] = field(default_factory=list)


def _tokenize(segment):
    text = normalize_text(segment)
    text = _DIGIT_LETTER.sub(" ", text)
    return text.split()


def _extract(tokens):
    """Pull quantity phrases out of tokens. Returns (quantities, remaining_tokens)."""
    quantities, rest = [], []
    i = 0
    while i < len(tokens):
        num = parse_number(tokens, i)
        if num:
            value, used = num
            unit = unit_at(tokens, i + used)
            raw = " ".join(tokens[i:i + used + (1 if unit else 0)])
            quantities.append(QuantityCandidate(value, unit, raw))
            i += used + (1 if unit else 0)
            continue
        unit = unit_at(tokens, i)
        if unit and not is_numeric_token(tokens[i]):
            # unit with no number ("kilo sugar"): remember the unit, quantity unknown
            quantities.append(QuantityCandidate(None, unit, tokens[i]))
            i += 1
            continue
        rest.append(tokens[i])
        i += 1
    return quantities, rest


def _has_quantity(tokens):
    return any(q.value is not None for q in _extract(tokens)[0])


def _split_on_connectors(tokens):
    """
    Split at "and"/"then"... only when BOTH sides carry their own quantity
    ("500 ml oil and 1 kg sugar"). "2 salt and pepper" stays one phrase, so an
    unclear sentence is shown to the customer instead of being guessed.
    """
    chunks, current = [], []
    for i, tok in enumerate(tokens):
        if tok in CONNECTORS and current and _has_quantity(current) and _has_quantity(tokens[i + 1:]):
            chunks.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        chunks.append(current)
    return chunks


def _trim_edges(tokens):
    toks = list(tokens)
    while toks and (toks[0] in STOP_WORDS or toks[0] in CONNECTORS):
        toks.pop(0)
    while toks and (toks[-1] in STOP_WORDS or toks[-1] in CONNECTORS):
        toks.pop()
    return toks


def parse_order_text(text):
    """Return a list of ParsedItem for the spoken/typed order text."""
    items: List[ParsedItem] = []
    pre = pre_normalize(text)
    for segment in _SEGMENT_SPLIT.split(pre):
        if not segment.strip():
            continue
        for chunk in _split_on_connectors(_tokenize(segment)):
            quantities, rest = _extract(chunk)
            product_tokens = _trim_edges(rest)
            raw = " ".join(chunk)
            if not product_tokens:
                if quantities and items:
                    # dangling quantity ("... , two litres") belongs to the previous item
                    prev = items[-1]
                    for q in quantities:
                        if q not in prev.quantities:
                            prev.quantities.append(q)
                    prev.raw += ", " + raw
                continue
            uniq = []
            for q in quantities:
                if q not in uniq:
                    uniq.append(q)
            items.append(ParsedItem(raw=raw, product_text=" ".join(product_tokens), quantities=uniq))
    return items
