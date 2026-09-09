"""
What the market itself thinks, before any model is involved.

WHY THIS COMES BEFORE THE MODEL
-------------------------------
M5 and M6 established that this project's model loses to the market in ten
datasets out of ten and adds no incremental information in any of them. So
"edge = my probability minus the market's" is the number that already proved to
be an illusion: it declared value in a third of all selections while the CLV of
those bets was negative thirty times out of thirty.

There is a different comparison that needs no model at all. With several books
priced on the same match, each one's de-vigged opinion can be compared against
the CONSENSUS of the others. A price that pays more than what the rest of the
market thinks the outcome is worth is value measured against the only estimator
in this project that has ever beaten anything: the market.

That is not a promise of profit. It is a measurement whose CLV has never been
tested here, and until it has, it produces a candidate and never a bet.

ONE THING THAT CANNOT BE MEASURED PER MATCH
-------------------------------------------
"How efficient is the market for this match" has no answer. Efficiency is a
property of a market estimated over many matches: it is the relationship
between prices and realised frequencies, and one match realises once. Anything
printed per match under that name would be a different quantity wearing its
label.

What IS measurable per match, and is reported instead:

    margin        what the book charges. A cost, not a mistake.
    dispersion    how much the books disagree, in probability points.
    best vs consensus   whether one price stands away from the rest.

Disagreement is not inefficiency either — but it is where inefficiency would
have to show up, and unlike efficiency it is observable one match at a time.
"""

from __future__ import annotations

import statistics as st
from dataclasses import dataclass

from fiorino.odds.devig import devig

__all__ = ["BookView", "Consensus", "build_consensus", "SELECTIONS"]

SELECTIONS = ("HOME", "DRAW", "AWAY")

#: Aggregate columns are not bookmakers. MARKET_MAX is the best price across
#: books and MARKET_AVG their mean: including either in a consensus would let
#: the aggregate vote alongside the books it is made of, which double-counts
#: them and then compares the result against itself.
AGGREGATES = {"MARKET_MAX", "MARKET_AVG"}


@dataclass(frozen=True)
class BookView:
    """One bookmaker's de-vigged opinion."""

    bookmaker: str
    prices: tuple[float, float, float]
    fair: tuple[float, float, float]
    overround: float


@dataclass
class Consensus:
    """The market's own opinion, and how firmly it holds it."""

    match_key: str
    books: list[BookView]
    #: Median de-vigged probability per selection. Median, not mean: one book
    #: with a stale or fat-fingered line should not drag the consensus.
    fair: tuple[float, float, float]
    #: Spread between the highest and lowest de-vigged probability per
    #: selection, in probability points. This is "how much do books disagree".
    dispersion: tuple[float, float, float]
    mean_overround: float
    #: Best decimal price available per selection, and who offers it.
    best_price: tuple[float, float, float]
    best_book: tuple[str, str, str]
    refused: list[str]

    @property
    def n_books(self) -> int:
        return len(self.books)

    def edge_vs_consensus(self, index: int) -> float:
        """Expected value of the best price under the consensus probability.

        `p * price - 1`. Positive means the best available price pays more than
        the rest of the market thinks the outcome is worth. It is NOT a model
        edge and carries no claim about the true probability: it says the books
        disagree and names which side of the disagreement pays.
        """
        return self.fair[index] * self.best_price[index] - 1.0


def build_consensus(match_key: str, quotes) -> Consensus | None:
    """De-vig every real bookmaker on one match and combine them.

    A book whose market the de-vig refuses is counted and excluded, never
    normalised: two thirds of a market normalised produces a confident number
    that nothing downstream could tell from a real one.
    """
    views, refused = [], []
    best_price = [0.0, 0.0, 0.0]
    best_book = ["", "", ""]

    for quote in quotes:
        if quote.bookmaker in AGGREGATES:
            continue
        prices = (quote.home, quote.draw, quote.away)
        try:
            result = devig(list(SELECTIONS), list(prices), "SHIN")
        except ValueError:
            refused.append(quote.bookmaker)
            continue
        views.append(BookView(quote.bookmaker, prices,
                              tuple(result.fair_probs), result.overround))
        for i, price in enumerate(prices):
            if price > best_price[i]:
                best_price[i], best_book[i] = price, quote.bookmaker

    # One book is not a consensus. Reporting a "market opinion" from a single
    # opinion is the same error as a one-match efficiency estimate.
    if len(views) < 2:
        return None

    fair, dispersion = [], []
    for i in range(3):
        column = [v.fair[i] for v in views]
        fair.append(st.median(column))
        dispersion.append(max(column) - min(column))

    return Consensus(
        match_key=match_key, books=views,
        fair=tuple(fair), dispersion=tuple(dispersion),
        mean_overround=st.mean(v.overround for v in views),
        best_price=tuple(best_price), best_book=tuple(best_book),
        refused=refused,
    )
