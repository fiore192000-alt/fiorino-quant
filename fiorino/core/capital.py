"""
Capital constraint for a cohort of simultaneous bets.

This module exists to make one failure mode impossible.

A cohort is a set of bets that are decided together and settle together —
three 15:00 kickoffs, say. If they are sized sequentially, each one compounds
on the results of matches that have not been played yet:

    bankroll 100, stake 50% each   ->   50, 75, 112.50     WRONG
    bankroll 100, stake 50% each   ->   50, 50, 50         requested
                                        then constrained to fit capital

Every stake in a cohort is sized against ONE equity snapshot. The requested
total may then exceed available capital, which is a separate question with an
explicit, configurable answer: reject the cohort, scale it down pro-rata, or
fill by rank until capital runs out. What is never acceptable is letting the
total exceed available capital, or letting a later bet see an earlier result.

Pure specification: no IO, no database, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from enum import Enum
from typing import Sequence

__all__ = [
    "OversizePolicy",
    "CapitalDecision",
    "apply_capital_constraint",
    "CENT",
]

CENT = Decimal("0.01")


class OversizePolicy(str, Enum):
    """What to do when a cohort asks for more capital than it has."""

    #: Place nothing. Safest, and correct when the strategy's edge estimate
    #: depends on taking the whole basket.
    REJECT = "reject"
    #: Scale every stake by the same factor. Preserves relative sizing, which
    #: is what Kelly actually optimises. The sane default.
    SCALE_PRO_RATA = "scale_pro_rata"
    #: Fill in descending rank (usually edge) until capital is exhausted; the
    #: marginal bet is partially filled. Concentrates into the best bets.
    TRUNCATE_BY_RANK = "truncate_by_rank"


@dataclass(frozen=True)
class CapitalDecision:
    """The outcome of applying a capital constraint to a cohort.

    ``stakes`` always satisfies ``sum(stakes) <= available``. That invariant
    is the whole point of the module and is asserted before returning.
    """

    stakes: tuple[Decimal, ...]
    requested: tuple[Decimal, ...]
    available: Decimal
    policy: OversizePolicy
    was_constrained: bool
    rejected: bool

    @property
    def total(self) -> Decimal:
        return sum(self.stakes, Decimal("0"))

    @property
    def requested_total(self) -> Decimal:
        return sum(self.requested, Decimal("0"))

    @property
    def utilisation(self) -> Decimal:
        """Fraction of available capital actually deployed."""
        if self.available <= 0:
            return Decimal("0")
        return self.total / self.available


def apply_capital_constraint(
    requested: Sequence[Decimal],
    available: Decimal,
    policy: OversizePolicy = OversizePolicy.SCALE_PRO_RATA,
    rank: Sequence[float] | None = None,
) -> CapitalDecision:
    """Fit a cohort's requested stakes into the capital actually available.

    Parameters
    ----------
    requested
        Stakes as sized by the allocator, every one of them against the same
        equity snapshot. Order is preserved in the result.
    available
        Capital the cohort may deploy: ``equity * max_exposure - open_exposure``.
    policy
        How to resolve an oversized cohort.
    rank
        Only for ``TRUNCATE_BY_RANK``. Higher fills first; usually the edge.

    Raises
    ------
    ValueError
        On negative stakes, negative capital, or a missing/mismatched rank.
    """
    req = tuple(Decimal(str(s)) for s in requested)
    avail = Decimal(str(available))

    if any(s < 0 for s in req):
        raise ValueError("requested stakes must be non-negative")
    if avail < 0:
        raise ValueError("available capital must be non-negative")

    total = sum(req, Decimal("0"))

    if total <= avail:
        return CapitalDecision(
            stakes=tuple(s.quantize(CENT, rounding=ROUND_DOWN) for s in req),
            requested=req,
            available=avail,
            policy=policy,
            was_constrained=False,
            rejected=False,
        )

    if policy is OversizePolicy.REJECT:
        stakes = tuple(Decimal("0.00") for _ in req)
        rejected = True

    elif policy is OversizePolicy.SCALE_PRO_RATA:
        factor = avail / total if total > 0 else Decimal("0")
        # ROUND_DOWN so accumulated rounding can never breach `available`.
        stakes = tuple((s * factor).quantize(CENT, rounding=ROUND_DOWN) for s in req)
        rejected = False

    elif policy is OversizePolicy.TRUNCATE_BY_RANK:
        if rank is None or len(rank) != len(req):
            raise ValueError("TRUNCATE_BY_RANK requires a rank of the same length")
        remaining = avail
        out = [Decimal("0.00")] * len(req)
        for i in sorted(range(len(req)), key=lambda j: rank[j], reverse=True):
            if remaining <= 0:
                break
            fill = min(req[i], remaining).quantize(CENT, rounding=ROUND_DOWN)
            out[i] = fill
            remaining -= fill
        stakes = tuple(out)
        rejected = all(s == 0 for s in stakes)

    else:  # pragma: no cover - Enum is exhaustive
        raise ValueError(f"unknown policy: {policy}")

    placed = sum(stakes, Decimal("0"))
    assert placed <= avail, f"capital invariant violated: {placed} > {avail}"

    return CapitalDecision(
        stakes=stakes,
        requested=req,
        available=avail,
        policy=policy,
        was_constrained=True,
        rejected=rejected,
    )
