"""
Strategy protocol, and the naive baselines M4 is validated with.

M4 builds the engine, not the edge. A strategy here proposes candidates and
nothing else: it never sees the bankroll, never chooses a stake. Sizing needs a
portfolio-level view the strategy cannot have, and letting it size is how a
backtest ends up with a strategy that quietly bets more when it is winning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

__all__ = [
    "Candidate",
    "Strategy",
    "TakeSelection",
    "TakeFavourite",
    "TakeValueVsClose",
    "ModelEdge",
]


@dataclass(frozen=True)
class Candidate:
    """A bet a strategy wants, before anyone decides how much."""

    match_id: str
    bookmaker_id: str
    market_type: str
    line: float
    selection: str
    price: float
    price_precision: str
    #: The strategy's probability, when it has one. None for price-only rules.
    model_prob: float | None = None
    #: Ranking key for the truncate-by-rank policy. Edge, usually.
    rank: float = 0.0


class Strategy(Protocol):
    """Reads only through the point-in-time view. Never sees the bankroll."""

    name: str

    def generate(self, view, match_ids: Sequence[str]) -> list[Candidate]:
        ...


class _PriceStrategy:
    """Shared plumbing: pull the priced selections for a set of matches."""

    market_type = "ONE_X_TWO"
    precision = "PREMATCH"

    def _priced(self, view, match_ids):
        if not match_ids:
            return []
        placeholders = ", ".join("?" for _ in match_ids)
        return view.con.execute(
            f"""SELECT match_id, bookmaker_id, market_type, line, selection, price_decimal
                FROM odds_observations
                WHERE capture_precision = ? AND market_type = ?
                  AND match_id IN ({placeholders})
                ORDER BY match_id, selection""",
            [self.precision, self.market_type, *match_ids],
        ).fetchall()


class TakeSelection(_PriceStrategy):
    """Back one side everywhere. The crudest possible baseline."""

    def __init__(self, selection: str = "HOME", precision: str = "PREMATCH"):
        self.selection = selection.upper()
        self.precision = precision
        self.name = f"take_{self.selection.lower()}"

    def generate(self, view, match_ids) -> list[Candidate]:
        return [
            Candidate(m, b, mk, ln, sel, price, self.precision)
            for m, b, mk, ln, sel, price in self._priced(view, match_ids)
            if sel == self.selection
        ]


class TakeFavourite(_PriceStrategy):
    """Back the shortest price in each market."""

    name = "take_favourite"

    def __init__(self, precision: str = "PREMATCH"):
        self.precision = precision

    def generate(self, view, match_ids) -> list[Candidate]:
        best: dict[str, tuple] = {}
        for row in self._priced(view, match_ids):
            match_id, price = row[0], row[5]
            if match_id not in best or price < best[match_id][5]:
                best[match_id] = row
        return [
            Candidate(m, b, mk, ln, sel, price, self.precision)
            for m, b, mk, ln, sel, price in best.values()
        ]


class TakeValueVsClose(_PriceStrategy):
    """Back a pre-match price that beat the eventual close by a margin.

    NOT a strategy — it is deliberately clairvoyant, since the close is not
    knowable when the bet is struck. It exists to prove the engine can turn
    positive CLV into a positive equity curve: if a strategy KNOWN to have edge
    does not make money here, the engine is broken. Any run using it is
    labelled so it can never be mistaken for a result.
    """

    name = "oracle_beats_close"
    is_oracle = True

    def __init__(self, min_edge: float = 0.05):
        self.min_edge = min_edge

    def generate(self, view, match_ids) -> list[Candidate]:
        if not match_ids:
            return []
        placeholders = ", ".join("?" for _ in match_ids)
        rows = view.con.execute(
            f"""SELECT o.match_id, o.bookmaker_id, o.market_type, o.line, o.selection,
                       o.price_decimal, r.closing_fair_prob
                FROM odds_observations o
                JOIN reference_market r
                  ON  r.match_id = o.match_id AND r.market_type = o.market_type
                  AND r.line = o.line AND r.selection = o.selection
                WHERE o.capture_precision = 'PREMATCH'
                  AND o.match_id IN ({placeholders})
                  AND r.closing_fair_prob * o.price_decimal - 1 > ?
                ORDER BY o.match_id, o.selection""",
            [*match_ids, self.min_edge],
        ).fetchall()
        return [
            Candidate(m, b, mk, ln, sel, price, "PREMATCH",
                      model_prob=fair, rank=fair * price - 1)
            for m, b, mk, ln, sel, price, fair in rows
        ]


class ModelEdge(_PriceStrategy):
    """Back every selection where the model says the price is generous.

    The first strategy in the project with an actual opinion. It reads
    `predictions` — written by a walk-forward fit that saw only settled
    results — and bets when

        model EV = p_win*(price-1) + p_half_win*(price-1)/2
                 - p_half_lose*0.5 - p_lose  >  threshold

    with push contributing zero, which is what makes integer handicap and
    totals lines priceable at all.

    Predictions priced from a league prior are excluded by default: they are
    honest but weak, and betting them means betting hardest where the model
    knows least.
    """

    name = "model_edge"

    def __init__(self, min_edge: float = 0.05, markets=("ONE_X_TWO",),
                 precision: str = "PREMATCH", allow_prior: bool = False):
        self.min_edge = min_edge
        self.markets = tuple(markets)
        self.precision = precision
        self.allow_prior = allow_prior

    def generate(self, view, match_ids) -> list[Candidate]:
        if not match_ids:
            return []
        match_ph = ", ".join("?" for _ in match_ids)
        market_ph = ", ".join("?" for _ in self.markets)
        # Overlapping horizons mean one fixture is priced by several fits: the
        # walk refits weekly but prices eight days ahead, so consecutive runs
        # both cover the overlap. Take the FRESHEST fit whose boundary precedes
        # this decision — that is both the correct semantics and the reason a
        # naive join produced duplicate candidates and a primary-key collision.
        rows = view.con.execute(
            f"""WITH eligible AS (
                    SELECT v.*, r.trained_through,
                           row_number() OVER (
                               PARTITION BY v.match_id, v.bookmaker_id, v.market_type,
                                            v.line, v.selection
                               ORDER BY r.trained_through DESC, v.model_run_id
                           ) AS freshness
                    FROM v_model_vs_market v
                    JOIN model_runs r ON r.model_run_id = v.model_run_id
                    WHERE v.capture_precision = ?
                      AND v.market_type IN ({market_ph})
                      AND v.match_id IN ({match_ph})
                      AND (? OR NOT v.used_prior)
                      -- Rule R1 where it matters most: only a fit whose
                      -- boundary precedes this decision may inform this bet.
                      AND r.trained_through <= ?
                )
                SELECT match_id, bookmaker_id, market_type, line, selection,
                       offered_price, prob_win, edge_ev
                FROM eligible
                WHERE freshness = 1 AND edge_ev > ?
                ORDER BY match_id, selection""",
            [self.precision, *self.markets, *match_ids,
             self.allow_prior, view.as_of, self.min_edge],
        ).fetchall()
        return [
            Candidate(m, b, mk, ln, sel, price, self.precision,
                      model_prob=prob, rank=edge)
            for m, b, mk, ln, sel, price, prob, edge in rows
        ]
