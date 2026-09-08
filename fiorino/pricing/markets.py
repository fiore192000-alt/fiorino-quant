"""
Project a score grid onto the market vocabulary.

Emits rows that join to `odds_observations` on (market_type, line, selection)
with no translation layer, each carrying all five settlement probabilities.

Which markets to price is a choice, not a given: pricing every quarter line
from -3 to +3 produces thousands of rows per fixture, almost all of them for
lines no book offers. The default ladder covers what Football-Data publishes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from fiorino.core.markets import (
    OutcomeStructure,
    Side,
    asian_handicap_outcomes,
    one_x_two_outcomes,
    totals_outcomes,
)

__all__ = ["PricedSelection", "price_grid", "DEFAULT_HANDICAPS", "DEFAULT_TOTALS"]

#: Home-perspective handicap lines (rule R3). Quarter lines included because
#: they are the ones the two-state formula gets wrong.
DEFAULT_HANDICAPS: tuple[float, ...] = (
    -2.0, -1.75, -1.5, -1.25, -1.0, -0.75, -0.5, -0.25,
    0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0,
)

DEFAULT_TOTALS: tuple[float, ...] = (1.5, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.5)


@dataclass(frozen=True)
class PricedSelection:
    market_type: str
    line: float
    selection: str
    outcome: OutcomeStructure

    def as_row(self) -> dict:
        return {
            "market_type": self.market_type,
            "line": self.line,
            "selection": self.selection,
            "prob_win": self.outcome.win,
            "prob_half_win": self.outcome.half_win,
            "prob_push": self.outcome.push,
            "prob_half_lose": self.outcome.half_lose,
            "prob_lose": self.outcome.lose,
        }


def price_grid(
    grid: Sequence[Sequence[float]],
    *,
    handicaps: Iterable[float] = DEFAULT_HANDICAPS,
    totals: Iterable[float] = DEFAULT_TOTALS,
    include_btts: bool = True,
) -> list[PricedSelection]:
    """Every market this grid supports, priced coherently.

    Coherent by construction: all of it comes from the same matrix, so 1X2 and
    Over/Under cannot disagree.
    """
    priced: list[PricedSelection] = []

    for selection in ("HOME", "DRAW", "AWAY"):
        priced.append(PricedSelection("ONE_X_TWO", 0.0, selection,
                                      one_x_two_outcomes(grid, selection)))

    for line in handicaps:
        for side in (Side.HOME, Side.AWAY):
            priced.append(PricedSelection("ASIAN_HANDICAP", line, side.value,
                                          asian_handicap_outcomes(grid, side, line)))

    for line in totals:
        for side in (Side.OVER, Side.UNDER):
            priced.append(PricedSelection("TOTALS", line, side.value,
                                          totals_outcomes(grid, side, line)))

    if include_btts:
        both = sum(
            grid[h][a] for h in range(1, len(grid)) for a in range(1, len(grid[0]))
        )
        priced.append(PricedSelection("BTTS", 0.0, "YES",
                                      OutcomeStructure(win=both, lose=1.0 - both)))
        priced.append(PricedSelection("BTTS", 0.0, "NO",
                                      OutcomeStructure(win=1.0 - both, lose=both)))
    return priced
