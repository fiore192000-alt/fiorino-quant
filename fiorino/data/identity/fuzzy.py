"""
Fuzzy name similarity — proposals only.

Nothing in this module writes to `team_aliases`. It scores candidates and
hands them to the resolver, which files them as PROPOSED. No threshold, however
high, produces an automatic acceptance: the threshold decides only whether a
proposal is worth a human's attention.

Implemented in pure Python rather than pulling in rapidfuzz: the scoring must
be reproducible across environments, and a dependency bump silently changing
similarity scores would silently change which teams get merged.
"""

from __future__ import annotations

from dataclasses import dataclass

from .normalize import normalize_team_name, tokenize

__all__ = ["jaro_winkler", "token_set_ratio", "similarity", "Candidate", "rank_candidates"]


def jaro(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0

    window = max(len(a), len(b)) // 2 - 1
    window = max(window, 0)
    a_flags = [False] * len(a)
    b_flags = [False] * len(b)

    matches = 0
    for i, ch in enumerate(a):
        lo = max(0, i - window)
        hi = min(i + window + 1, len(b))
        for j in range(lo, hi):
            if not b_flags[j] and b[j] == ch:
                a_flags[i] = b_flags[j] = True
                matches += 1
                break
    if matches == 0:
        return 0.0

    transpositions = 0
    k = 0
    for i, matched in enumerate(a_flags):
        if not matched:
            continue
        while not b_flags[k]:
            k += 1
        if a[i] != b[k]:
            transpositions += 1
        k += 1
    transpositions //= 2

    m = float(matches)
    return (m / len(a) + m / len(b) + (m - transpositions) / m) / 3.0


def jaro_winkler(a: str, b: str, prefix_weight: float = 0.1) -> float:
    """Jaro with a bonus for a shared prefix, capped at four characters."""
    score = jaro(a, b)
    prefix = 0
    for ca, cb in zip(a[:4], b[:4]):
        if ca != cb:
            break
        prefix += 1
    return score + prefix * prefix_weight * (1.0 - score)


def token_set_ratio(a: str, b: str) -> float:
    """Jaccard over token sets, with numeric tokens down-weighted.

    Handles reordering and extra words ("Wolverhampton Wanderers" vs "Wolves
    Wanderers Wolverhampton") which character similarity handles badly.
    """
    ta, tb = set(tokenize(a)), set(tokenize(b))
    if not ta or not tb:
        return 0.0

    def weight(token: str) -> float:
        return 0.3 if token.isdigit() else 1.0

    shared = sum(weight(t) for t in ta & tb)
    total = sum(weight(t) for t in ta | tb)
    return shared / total if total else 0.0


def similarity(a: str, b: str) -> tuple[float, str]:
    """Best of the two measures, with the method that produced it."""
    na, nb = normalize_team_name(a), normalize_team_name(b)
    jw = jaro_winkler(na, nb)
    ts = token_set_ratio(a, b)
    return (jw, "JARO_WINKLER") if jw >= ts else (ts, "TOKEN_SET")


@dataclass(frozen=True)
class Candidate:
    team_id: str
    canonical_name: str
    score: float
    method: str


def rank_candidates(
    raw_name: str,
    candidates: list[tuple[str, str]],
    *,
    min_score: float = 0.80,
    limit: int = 5,
) -> list[Candidate]:
    """Score ``(team_id, canonical_name)`` pairs against ``raw_name``.

    Callers must restrict ``candidates`` to the same country before calling:
    similarity alone cannot tell Arsenal (England) from Arsenal (Argentina).
    """
    scored = []
    for team_id, name in candidates:
        score, method = similarity(raw_name, name)
        if score >= min_score:
            scored.append(Candidate(team_id, name, score, method))
    scored.sort(key=lambda c: (-c.score, c.canonical_name))
    return scored[:limit]
