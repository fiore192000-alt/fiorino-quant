"""
From expected goals to a coherent score grid.

One grid per fixture, and every market priced off it. Because all prices
descend from the same matrix they are consistent by construction: the model
cannot price 1X2 and Over/Under in mutually contradictory ways.
"""

from __future__ import annotations

import math

__all__ = ["score_grid", "MAX_GOALS", "grid_from_lambdas"]

#: Goals 0..MAX_GOALS inclusive, so the matrix is (MAX_GOALS + 1) square.
#:
#: penaltyblog is inconsistent here and it is a genuine trap: `model.predict
#: (max_goals=15)` returns a 15x15 grid covering goals 0..14, while
#: `create_dixon_coles_grid(max_goals=15)` returns 16x16 covering 0..15. The
#: convention is normalised in this one place so nothing downstream has to
#: know which it is holding.
MAX_GOALS = 15


def _poisson_pmf(k: int, mu: float) -> float:
    return math.exp(-mu) * mu**k / math.factorial(k)


def score_grid(lambda_home: float, lambda_away: float, rho: float = 0.0,
               max_goals: int = MAX_GOALS) -> list[list[float]]:
    """P(home = i, away = j) for i, j in 0..max_goals, normalised to sum to 1.

    ``rho`` applies the Dixon-Coles low-score correction. It is bounded by the
    lambdas — outside those bounds the adjustment drives a cell negative — so
    it is clamped rather than allowed to produce a grid that is not a
    distribution.
    """
    if lambda_home <= 0 or lambda_away <= 0:
        raise ValueError(f"expected goals must be positive, got {lambda_home}, {lambda_away}")

    home = [_poisson_pmf(i, lambda_home) for i in range(max_goals + 1)]
    away = [_poisson_pmf(j, lambda_away) for j in range(max_goals + 1)]
    grid = [[h * a for a in away] for h in home]

    if rho:
        rho = _clamp_rho(rho, lambda_home, lambda_away)
        grid[0][0] *= 1.0 - rho * lambda_home * lambda_away
        grid[1][0] *= 1.0 + rho * lambda_away
        grid[0][1] *= 1.0 + rho * lambda_home
        grid[1][1] *= 1.0 - rho

    total = sum(sum(row) for row in grid)
    if total <= 0:
        raise ValueError("score grid sums to zero")
    # Truncation at max_goals loses a sliver of tail mass; renormalising keeps
    # the grid a distribution, which every market derivation assumes.
    return [[cell / total for cell in row] for row in grid]


def _clamp_rho(rho: float, lambda_home: float, lambda_away: float) -> float:
    """Keep rho inside the range where the correction stays a distribution."""
    lower = max(-1.0 / lambda_home, -1.0 / lambda_away)
    upper = min(1.0, 1.0 / (lambda_home * lambda_away))
    return min(max(rho, lower), upper)


def grid_from_lambdas(pair, rho: float = 0.0, max_goals: int = MAX_GOALS):
    """Convenience over a :class:`LambdaPair`."""
    return score_grid(pair.home, pair.away, rho=rho, max_goals=max_goals)
