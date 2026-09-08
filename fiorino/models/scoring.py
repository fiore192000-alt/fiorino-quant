"""
Proper scoring rules, and the paired bootstrap that says whether a difference
between two of them means anything.

Three rules, because they disagree in useful ways:

* **Brier** is a squared error. It is insensitive to how badly a confident
  forecast fails, which is exactly the failure mode a bettor cares about.
* **Log-loss** is unbounded below. One confident miss dominates, which is what
  a bankroll experiences.
* **RPS** is the only one that knows HOME/DRAW/AWAY is *ordered*: predicting a
  home win when the away side wins should cost more than predicting a draw.
  Football forecasting reports it for that reason.

The Brier convention here matches M5 — mean over selection rows, not over
matches — so the numbers in the two validation reports can be read side by
side. Per match it would be exactly three times larger.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable, Sequence

__all__ = ["Scores", "score_forecasts", "paired_bootstrap", "ORDERED_1X2", "EPS"]

#: Ordering matters for RPS and nowhere else. Home, draw, away is the natural
#: ordering of the result axis.
ORDERED_1X2 = ("HOME", "DRAW", "AWAY")

#: Probabilities are clipped this far from the boundary. A de-vigged price can
#: legitimately reach 0.98; log-loss at an exact 0 is infinite and would let a
#: single row decide a whole comparison.
EPS = 1e-9


@dataclass(frozen=True)
class Scores:
    n: int
    brier: float          # mean over selection rows, M5 convention
    logloss: float        # mean over MATCHES of -ln p(realised outcome)
    logloss_selection: float   # M5 convention, kept for reconciliation
    rps: float


def _clip(p: float) -> float:
    return min(max(p, EPS), 1.0 - EPS)


def score_forecasts(forecasts: Sequence[Sequence[float]],
                    outcomes: Sequence[int]) -> Scores:
    """Score a set of 3-outcome forecasts.

    ``forecasts[i]`` is (p_home, p_draw, p_away) and ``outcomes[i]`` is the
    index of what happened. Rows are normalised first: a pooled forecast is
    proportional, not normalised, and scoring an unnormalised vector silently
    rewards whichever arm happens to sum low.
    """
    if len(forecasts) != len(outcomes):
        raise ValueError("forecasts and outcomes differ in length")
    if not forecasts:
        raise ValueError("nothing to score")

    n = len(forecasts)
    brier_sum = logloss_sum = logloss_sel_sum = rps_sum = 0.0
    for probs, outcome in zip(forecasts, outcomes):
        if len(probs) != 3:
            raise ValueError(f"expected 3 probabilities, got {len(probs)}")
        total = sum(probs)
        if total <= 0:
            raise ValueError("forecast sums to zero")
        p = [_clip(x / total) for x in probs]

        realised = [1.0 if k == outcome else 0.0 for k in range(3)]
        brier_sum += sum((p[k] - realised[k]) ** 2 for k in range(3))
        logloss_sum += -math.log(p[outcome])
        logloss_sel_sum += sum(
            -math.log(p[k] if realised[k] else 1.0 - p[k]) for k in range(3)
        )
        # RPS over the cumulative distribution, r - 1 = 2 terms.
        cum_p = cum_e = 0.0
        acc = 0.0
        for k in range(2):
            cum_p += p[k]
            cum_e += realised[k]
            acc += (cum_p - cum_e) ** 2
        rps_sum += acc / 2.0

    return Scores(
        n=n,
        brier=brier_sum / (3 * n),
        logloss=logloss_sum / n,
        logloss_selection=logloss_sel_sum / (3 * n),
        rps=rps_sum / n,
    )


def paired_bootstrap(
    left: Sequence[Sequence[float]],
    right: Sequence[Sequence[float]],
    outcomes: Sequence[int],
    metric: Callable[[Scores], float],
    *,
    draws: int = 2000,
    seed: int = 20260908,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """CI for ``metric(right) - metric(left)`` on the SAME matches.

    Paired, and resampling matches rather than rows, because the two arms
    forecast the same fixtures and the three selections of one fixture are one
    observation, not three. Treating them as independent would shrink the
    interval by roughly sqrt(3) and manufacture significance.

    Returns (point estimate, low, high). A negative difference means ``right``
    scores lower, which for all three rules means better.
    """
    if not (len(left) == len(right) == len(outcomes)):
        raise ValueError("arms and outcomes differ in length")
    point = metric(score_forecasts(right, outcomes)) - metric(score_forecasts(left, outcomes))

    rng = random.Random(seed)
    n = len(outcomes)
    diffs = []
    for _ in range(draws):
        idx = [rng.randrange(n) for _ in range(n)]
        l = [left[i] for i in idx]
        r = [right[i] for i in idx]
        o = [outcomes[i] for i in idx]
        diffs.append(metric(score_forecasts(r, o)) - metric(score_forecasts(l, o)))
    diffs.sort()
    lo = diffs[int(alpha / 2 * draws)]
    hi = diffs[min(int((1 - alpha / 2) * draws), draws - 1)]
    return point, lo, hi
