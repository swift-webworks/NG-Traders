"""
Confidence-based product matching against catalogue names and aliases.

Pure Python: it receives plain `entries` = [(product_id, [name strings]), ...]
so it can be unit-tested without a database.

Scoring (per product, best of its names):
    1.00        identical (after gentle normalisation + plural folding)
    0.80-0.88   all words of a name appear in the spoken words, or the other way round
    <= 0.88     fuzzy spelling similarity (never reaches the "confident" level)

A product is returned as `matched` only when the best score is >= CONFIDENT
AND clearly ahead of the runner-up. Everything else becomes `ambiguous`
(show choices) or `unknown`. A guess is never added silently.
"""
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Tuple

from catalogue.textnorm import loose_key

CONFIDENT = 0.92
MARGIN = 0.08
CANDIDATE_MIN = 0.55
MAX_CANDIDATES = 4


@dataclass
class MatchResult:
    status: str                      # "matched" | "ambiguous" | "unknown"
    candidates: List[Tuple[int, float]]  # [(product_id, score)] best first


def _trigrams(s):
    s = f" {s} "
    return {s[i:i + 3] for i in range(len(s) - 2)}


def build_entries(raw_entries):
    """raw_entries: iterable of (product_id, [names]) -> searchable list."""
    built = []
    for pid, names in raw_entries:
        for name in names:
            key = loose_key(name)
            if key:
                built.append((pid, key, frozenset(key.split()), _trigrams(key)))
    return built


def _score(q, qtok, k, ktok):
    if q == k:
        return 1.0
    if ktok <= qtok:  # the catalogue name is fully contained in what was said
        return 0.80 + 0.08 * len(ktok) / len(qtok)
    if qtok <= ktok:  # what was said is only part of the catalogue name
        return 0.75 + 0.10 * len(qtok) / len(ktok)
    whole = SequenceMatcher(None, q, k).ratio()
    # word-by-word similarity helps with small spelling differences in multi-word names
    best = []
    for t in qtok:
        best.append(max((SequenceMatcher(None, t, u).ratio() for u in ktok), default=0))
    per_word = sum(best) / len(best) if best else 0
    return min(0.88, max(whole, per_word * 0.9))


def match_product(text, entries) -> MatchResult:
    q = loose_key(text)
    if not q or not entries:
        return MatchResult("unknown", [])
    qtok = frozenset(q.split())
    qtri = _trigrams(q)

    # cheap shortlist so large catalogues stay fast
    shortlist = []
    for pid, key, ktok, ktri in entries:
        overlap = len(qtri & ktri)
        if overlap or (qtok & ktok):
            shortlist.append((overlap / max(len(qtri), 1), pid, key, ktok))
    shortlist.sort(key=lambda x: -x[0])

    best = {}
    for _, pid, key, ktok in shortlist[:80]:
        s = _score(q, qtok, key, ktok)
        if s > best.get(pid, 0):
            best[pid] = s
    ranked = sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))
    ranked = [(pid, round(s, 3)) for pid, s in ranked if s >= CANDIDATE_MIN]
    if not ranked:
        return MatchResult("unknown", [])
    top_id, top = ranked[0]
    runner = ranked[1][1] if len(ranked) > 1 else 0.0
    if top >= CONFIDENT and top - runner >= MARGIN:
        return MatchResult("matched", ranked[:1])
    return MatchResult("ambiguous", ranked[:MAX_CANDIDATES])
