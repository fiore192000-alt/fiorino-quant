"""
Combining a model forecast with the market's, and estimating how much to trust
each.

The pool is logarithmic, not linear:

    p_k  ∝  p_model_k ** w  *  p_market_k ** (1 - w)

For two outcomes this is exactly the logit-space blend; for three it is its
natural generalisation, and it is the right shape for this problem because
combining *odds* is multiplicative. A linear pool of two confident, disagreeing
forecasts produces a bimodal average that neither source believes; the
logarithmic pool produces something between them.

``w`` is a single number and that is deliberate. The question M6 asks is not
"how do we squeeze the most out of these two forecasts" but "does the model
contain information the market lacks". One parameter answers it with almost no
capacity to overfit, and ``w == 0`` is a clean, readable "no".

THE LEAKAGE THIS MODULE IS BUILT AROUND: ``w`` is a fitted parameter, so
fitting it on matches that have not settled by the boundary is exactly the
leak the rest of the system is designed to prevent, arriving through a door
nobody was watching. :func:`fit_weight` therefore takes an explicit boundary
and refuses rows that fall on the wrong side of it, rather than trusting the
caller to have filtered.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

__all__ = ["pool", "fit_weight", "FittedWeight", "TrainingRow", "WEIGHT_BOUNDS"]

#: A convex combination. A weight outside [0, 1] is extrapolation, not a
#: blend, and nobody would run it. The unconstrained optimum is reported
#: separately as a diagnostic, because it distinguishes "the model adds
#: nothing" (w* ≈ 0) from "the model is actively misleading" (w* < 0), which
#: the constrained fit collapses into the same value.
WEIGHT_BOUNDS = (0.0, 1.0)
DIAGNOSTIC_BOUNDS = (-1.0, 2.0)

_EPS = 1e-12


@dataclass(frozen=True)
class TrainingRow:
    """One settled match, as the weight fitter sees it."""

    match_id: str
    settled_at: datetime
    model: tuple[float, float, float]
    market: tuple[float, float, float]
    outcome: int          # index into (HOME, DRAW, AWAY)


@dataclass(frozen=True)
class FittedWeight:
    weight: float
    #: Same objective without the [0, 1] constraint. Reported, never applied.
    unconstrained: float
    n_train: int
    #: Latest settlement instant among the rows actually consumed. Carried out
    #: of the fitter so the point-in-time claim can be audited against data
    #: instead of trusted: see v_weight_leakage.
    train_max_settled_at: datetime
    train_logloss: float
    #: Log-loss of the market alone on the same rows. The pool cannot do worse
    #: than this by construction (w = 0 is in the feasible set), so the gap is
    #: the in-sample improvement — an upper bound on the honest one.
    market_logloss: float


def pool(model: Sequence[float], market: Sequence[float], weight: float) -> tuple[float, ...]:
    """Logarithmic opinion pool of two forecasts, normalised."""
    if len(model) != len(market):
        raise ValueError("forecasts have different lengths")
    combined = []
    for pm, pk in zip(model, market):
        pm = max(float(pm), _EPS)
        pk = max(float(pk), _EPS)
        combined.append(math.exp(weight * math.log(pm) + (1.0 - weight) * math.log(pk)))
    total = sum(combined)
    if total <= 0:
        raise ValueError("pooled forecast sums to zero")
    return tuple(c / total for c in combined)


def _nll(rows: Sequence[TrainingRow], weight: float) -> float:
    total = 0.0
    for row in rows:
        p = pool(row.model, row.market, weight)
        total -= math.log(max(p[row.outcome], _EPS))
    return total / len(rows)


def _minimise(rows, lo: float, hi: float, tol: float = 1e-5) -> float:
    """Golden-section search.

    The objective is the NLL of a log-pool in one variable: smooth, and convex
    in ``weight`` because it is a log-sum-exp of affine functions. A local
    search is therefore a global one, and this avoids a scipy import for a
    one-dimensional problem.
    """
    phi = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = lo, hi
    c, d = b - phi * (b - a), a + phi * (b - a)
    fc, fd = _nll(rows, c), _nll(rows, d)
    while b - a > tol:
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - phi * (b - a)
            fc = _nll(rows, c)
        else:
            a, c, fc = c, d, fd
            d = a + phi * (b - a)
            fd = _nll(rows, d)
    return (a + b) / 2.0


def fit_weight(rows: Sequence[TrainingRow], boundary: datetime, *,
               min_train: int = 40) -> FittedWeight | None:
    """Estimate ``w`` on matches settled strictly before ``boundary``.

    The filter is applied HERE and not left to the caller. A weight is the only
    parameter in M6 estimated from outcomes, so it is the only new way for the
    future to reach the past, and the check belongs where it cannot be
    forgotten. Rows at or after the boundary are dropped silently by design:
    the caller passing a wide window and letting the boundary do the cutting is
    the intended usage, not a mistake to report.

    Returns None when too little has settled, which is the normal state early
    in a season and must not be an error.
    """
    usable = [r for r in rows if r.settled_at < boundary]
    if len(usable) < min_train:
        return None

    weight = _minimise(usable, *WEIGHT_BOUNDS)
    diagnostic = _minimise(usable, *DIAGNOSTIC_BOUNDS)
    return FittedWeight(
        weight=weight,
        unconstrained=diagnostic,
        n_train=len(usable),
        train_max_settled_at=max(r.settled_at for r in usable),
        train_logloss=_nll(usable, weight),
        market_logloss=_nll(usable, 0.0),
    )
