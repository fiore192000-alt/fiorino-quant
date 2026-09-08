"""
Team-name normalisation.

Turns what a source emitted into a comparable key. Deliberately conservative:
over-normalising merges distinct clubs, and a merged club is far harder to
notice than an unmatched one — the pipeline shouts about unmatched names, but a
wrong merge just quietly corrupts every join that follows.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["normalize_team_name", "tokenize", "AFFIXES", "strip_diacritics"]

#: Club-type affixes safe to drop. Every entry is a legal-form or club-type
#: marker that sources add and remove freely, never a distinguishing word.
#:
#: Deliberately NOT here: "real", "sporting", "athletic", "atletico",
#: "deportivo", "olympique", "borussia", "inter", "dynamo". Each of those
#: distinguishes real clubs from one another.
AFFIXES = frozenset(
    {
        "fc", "afc", "cfc", "cf", "sc", "ac", "ss", "ssc", "us", "usc", "as",
        "rc", "sd", "cd", "ud", "rcd", "sv", "tsv", "tsg", "vfb", "vfl", "bsc",
        "bv", "fsv", "sk", "fk", "nk", "hc", "cp", "club", "calcio", "kv", "rkc",
    }
)

_APOSTROPHE = re.compile(r"['\u2019\u02bc]")
_PUNCT = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS = re.compile(r"\s+")

#: Letters NFKD does not decompose but European sources use freely. Without
#: these, "Brøndby" and "Brondby" are different clubs, and Turkish dotless i
#: breaks the case-insensitivity invariant outright: "ı".upper() is "I", whose
#: casefold is "i", while "ı".casefold() stays "ı".
_TRANSLITERATE = str.maketrans(
    {"ø": "o", "đ": "d", "ð": "d", "ł": "l", "ı": "i", "þ": "th",
     "æ": "ae", "œ": "oe", "ß": "ss"}
)


def strip_diacritics(text: str) -> str:
    """NFKD decompose and drop combining marks: München -> Munchen."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def tokenize(raw: str) -> list[str]:
    """De-accent, casefold, transliterate, de-punctuate and split."""
    if raw is None:
        raise ValueError("team name must not be None")
    text = strip_diacritics(str(raw)).casefold().translate(_TRANSLITERATE)
    text = text.replace("&", " and ")
    # Apostrophes are DELETED, not spaced: "Nott'm" is one token, and
    # splitting it into "nott" and "m" wrecks fuzzy scoring against
    # "Nottingham". All other punctuation becomes a separator.
    text = _APOSTROPHE.sub("", text)
    text = _PUNCT.sub(" ", text)
    return [t for t in _WS.sub(" ", text).strip().split(" ") if t]


def normalize_team_name(raw: str) -> str:
    """Normalised comparison key for a team name.

    Numeric tokens are KEPT. Dropping them looks tidy and is a trap: "1860
    München" would collapse to "munchen" and collide with Bayern München, and
    "Schalke 04" and "TSG 1899 Hoffenheim" have the same problem. Numbers stay
    in the key and carry low weight in fuzzy scoring instead.
    """
    tokens = tokenize(raw)
    if not tokens:
        raise ValueError(f"team name normalises to nothing: {raw!r}")

    kept = [t for t in tokens if t not in AFFIXES]
    # A name made only of affixes keeps them: better an odd key than an empty
    # one that matches everything.
    if not kept:
        kept = tokens
    return " ".join(kept)
