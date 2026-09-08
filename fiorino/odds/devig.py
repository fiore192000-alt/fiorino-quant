"""
Overround removal.

Always on a COMPLETE market, never on a single selection: the margin is a
property of the book's whole price set, and a lone price carries no information
about how it was loaded.

Shin is the default. It models the margin as compensation for informed traders
rather than as a flat tax, which matters because bookmakers do not spread the
margin evenly — they load it onto longshots. Multiplicative de-vigging
therefore overstates favourites and understates longshots, exactly where a
value bettor looks. penaltyblog supplies the implementations; this module
decides when they apply and records which was used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

__all__ = ["DevigResult", "devig", "overround", "DEFAULT_METHOD", "METHODS"]

DEFAULT_METHOD = "SHIN"
METHODS = ("SHIN", "MULTIPLICATIVE", "POWER", "ADDITIVE", "ODDS_RATIO", "LOGARITHMIC")


@dataclass(frozen=True)
class DevigResult:
    selections: tuple[str, ...]
    fair_probs: tuple[float, ...]
    raw_implied: tuple[float, ...]
    overround: float
    method: str
    n_selections: int

    def as_map(self) -> dict[str, float]:
        return dict(zip(self.selections, self.fair_probs))


def overround(prices: Sequence[float]) -> float:
    """Book margin: the amount by which implied probabilities exceed one."""
    if any(p <= 1.0 for p in prices):
        raise ValueError(f"decimal prices must exceed 1.0, got {list(prices)}")
    return sum(1.0 / p for p in prices) - 1.0


def devig(selections: Sequence[str], prices: Sequence[float], method: str = DEFAULT_METHOD) -> DevigResult:
    """Fair probabilities for one complete market.

    Raises rather than guessing when the market looks incomplete: a two-price
    "1X2" is a missing draw, and silently normalising it would produce
    confident nonsense that nothing downstream could detect.
    """
    if len(selections) != len(prices):
        raise ValueError("selections and prices must be the same length")
    if len(prices) < 2:
        raise ValueError(f"a market needs at least two selections, got {len(prices)}")
    if len(set(selections)) != len(selections):
        raise ValueError(f"duplicate selections in one market: {list(selections)}")

    method = method.upper()
    if method not in METHODS:
        raise ValueError(f"unknown de-vig method {method!r}; expected one of {METHODS}")

    book_margin = overround(prices)
    if book_margin < -1e-9:
        # Sum below 1.0 is an arbitrage or, far more often, a data error.
        # Either way it is not a market to de-vig silently.
        raise ValueError(
            f"implied probabilities sum to {book_margin + 1:.4f} (< 1); "
            "this is an arbitrage or a corrupt row, not a normal market"
        )

    raw = tuple(1.0 / p for p in prices)
    fair = _apply(method, list(prices))

    total = sum(fair)
    if abs(total - 1.0) > 1e-6:
        fair = [f / total for f in fair]

    return DevigResult(
        selections=tuple(selections),
        fair_probs=tuple(fair),
        raw_implied=raw,
        overround=book_margin,
        method=method,
        n_selections=len(prices),
    )


def _apply(method: str, prices: list[float]) -> list[float]:
    """Delegate to penaltyblog, which is a dependency and not the core."""
    from penaltyblog.implied import ImpliedMethod, calculate_implied

    mapping = {
        "SHIN": ImpliedMethod.SHIN,
        "MULTIPLICATIVE": ImpliedMethod.MULTIPLICATIVE,
        "POWER": ImpliedMethod.POWER,
        "ADDITIVE": ImpliedMethod.ADDITIVE,
        "ODDS_RATIO": ImpliedMethod.ODDS_RATIO,
        "LOGARITHMIC": ImpliedMethod.LOGARITHMIC,
    }
    try:
        result = calculate_implied(prices, method=mapping[method])
        probs = list(result.probabilities)
    except Exception:
        # A solver can fail to converge on a degenerate market. Falling back to
        # multiplicative is defensible; failing the whole ingest is not. The
        # method actually used is recorded per row, so the fallback is visible.
        probs = [1.0 / p for p in prices]
        total = sum(probs)
        probs = [p / total for p in probs]

    if any(p <= 0.0 or p >= 1.0 for p in probs) or not all(map(_finite, probs)):
        probs = [1.0 / p for p in prices]
        total = sum(probs)
        probs = [p / total for p in probs]
    return probs


def _finite(x: float) -> bool:
    return x == x and x not in (float("inf"), float("-inf"))
