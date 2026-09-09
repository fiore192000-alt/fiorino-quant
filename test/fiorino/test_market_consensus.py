"""
The consensus layer, and the four ways it could invent a market.

This is the first component in the project that produces a number a person
might act on without a model behind it, so the tests are about the ways that
number could be confident and wrong.
"""

import pytest

from fiorino.data.ingest.odds_feed.recorder import Quote
from fiorino.market.consensus import AGGREGATES, build_consensus


def q(book, home=2.10, draw=3.40, away=3.60, match="E0|12/09/2026|A|B"):
    return Quote(match_key=match, bookmaker=book, home=home, draw=draw, away=away)


class TestAConsensusNeedsMoreThanOneOpinion:
    def test_a_single_book_is_not_a_consensus(self):
        assert build_consensus("m", [q("BET365")]) is None

    def test_two_books_are_enough_to_disagree(self):
        assert build_consensus("m", [q("BET365"), q("BWIN")]) is not None

    def test_aggregates_do_not_vote(self):
        """MARKET_MAX is the best of the books and MARKET_AVG their mean.
        Letting either vote lets the books it is made of vote twice, and then
        compares the result against itself."""
        built = build_consensus("m", [q("MARKET_MAX"), q("MARKET_AVG")])
        assert built is None
        assert AGGREGATES == {"MARKET_MAX", "MARKET_AVG"}

    def test_an_aggregate_is_excluded_but_the_books_are_kept(self):
        built = build_consensus("m", [q("BET365"), q("BWIN"), q("MARKET_MAX", home=9.0)])
        assert built.n_books == 2


class TestTheConsensusIsRobust:
    def test_it_uses_the_median_so_one_stale_line_cannot_drag_it(self):
        """A fat-fingered or stale price is exactly the kind of row that would
        otherwise create the appearance of an edge against everyone else."""
        sane = [q(f"BOOK{i}", home=2.10) for i in range(4)]
        rogue = [q("STALE", home=6.00, draw=3.40, away=3.60)]
        built = build_consensus("m", sane + rogue)
        reference = build_consensus("m", sane)
        assert abs(built.fair[0] - reference.fair[0]) < 0.03

    def test_dispersion_reports_disagreement(self):
        tight = build_consensus("m", [q("A", home=2.10), q("B", home=2.11)])
        # The other legs move with it: a single generous leg on an otherwise
        # unchanged market sums below one, and the de-vig refuses it as an
        # arbitrage rather than reporting a wide disagreement.
        wide = build_consensus("m", [q("A", home=2.10),
                                     q("B", home=3.00, draw=3.00, away=2.60)])
        assert wide.dispersion[0] > tight.dispersion[0]

    def test_a_refused_market_is_counted_not_normalised(self):
        """An implied sum below one is an arbitrage or a corrupt row. Dropping
        it silently hides a data-quality fact; normalising it produces a
        confident number nothing could tell from a real one."""
        built = build_consensus("m", [q("A"), q("B"), q("BROKEN", 50.0, 50.0, 50.0)])
        assert "BROKEN" in built.refused
        assert built.n_books == 2


class TestTheEdgeIsAgainstTheMarketNotAModel:
    def test_an_identical_market_shows_no_edge_beyond_the_margin(self):
        built = build_consensus("m", [q(f"B{i}") for i in range(6)])
        # Every book identical: the best price is the common price, so the
        # only gap left is the vig itself, which is negative EV by definition.
        assert built.edge_vs_consensus(0) < 0

    def test_a_book_paying_above_the_others_shows_a_positive_edge(self):
        books = [q(f"B{i}", home=2.00, draw=3.30, away=3.30) for i in range(5)]
        books.append(q("GENEROUS", home=2.60, draw=3.10, away=3.10))
        built = build_consensus("m", books)
        assert built.edge_vs_consensus(0) > 0
        assert built.best_book[0] == "GENEROUS"

    def test_the_best_price_is_tracked_per_selection(self):
        built = build_consensus("m", [q("A", home=2.5, draw=3.0, away=3.0),
                                      q("B", home=2.0, draw=3.9, away=3.0)])
        assert built.best_book[0] == "A"
        assert built.best_book[1] == "B"


class TestTheRefusalGuardIsStrictOnPurpose:
    def test_one_generous_leg_on_an_unchanged_market_is_refused(self):
        """Found while writing these tests, and worth keeping: a book paying
        2.60 on the home side while leaving 3.40/3.60 on the others implies a
        sum below one. That is an arbitrage or a corrupt row, not a generous
        price, and it is refused rather than becoming the best price.

        The distinction matters because that refused row is precisely the shape
        of the thing that would otherwise be reported as a large edge."""
        built = build_consensus("m", [q("A"), q("B"),
                                      q("TOO_GOOD", home=2.60, draw=3.40, away=3.60)])
        assert "TOO_GOOD" in built.refused
        assert built.best_book[0] != "TOO_GOOD"


class TestTheWinnersCurseIsNeutralised:
    """The bug this layer shipped with, and the guard that keeps it out.

    Taking the best price across N books and comparing it to the median of all
    N graded five matches out of eighteen as class A. Measured on the real
    dispersion those matches showed — 0.024 probability points across seven
    books, zero inefficiency by construction — the best-of-seven price clears
    +4% half the time. The grades were the dispersion, restated.
    """

    def identical_books(self, n=7):
        """Books that agree exactly. Any edge here is an artefact."""
        return [q(f"B{i}", home=2.00, draw=3.30, away=3.30) for i in range(n)]

    def test_a_named_book_in_an_agreeing_market_shows_no_excess(self):
        built = build_consensus("m", self.identical_books())
        edge = built.edge_leave_one_out("B0", 0)
        assert edge < built.null_edge(0) + 1e-9

    def test_a_book_is_never_compared_against_itself(self):
        """Self-inclusion shrinks every edge toward zero and hides the real
        ones; it is the opposite bias to the winner's curse and just as wrong."""
        books = self.identical_books(5) + [q("ODD", home=2.30, draw=3.15, away=3.15)]
        built = build_consensus("m", books)
        others = [v for v in built.books if v.bookmaker != "ODD"]
        assert len(others) == 5
        assert built.edge_leave_one_out("ODD", 0) is not None

    def test_leave_one_out_needs_at_least_two_others(self):
        built = build_consensus("m", [q("A"), q("B")])
        assert built.edge_leave_one_out("A", 0) is None

    def test_the_null_band_grows_with_disagreement(self):
        """It is computed from each match's own dispersion, which is the whole
        point: a fixed threshold cannot know how much the books disagreed."""
        tight = build_consensus("m", [q(f"B{i}", home=2.00, draw=3.30, away=3.30)
                                      for i in range(6)])
        wide = build_consensus("m", [q("A", home=2.00, draw=3.30, away=3.30),
                                     q("B", home=2.20, draw=3.20, away=3.20),
                                     q("C", home=1.85, draw=3.45, away=3.45),
                                     q("D", home=2.35, draw=3.10, away=3.10),
                                     q("E", home=1.95, draw=3.35, away=3.35),
                                     q("F", home=2.10, draw=3.25, away=3.25)])
        assert wide.null_edge(0) > tight.null_edge(0)

    def test_the_null_band_is_deterministic(self):
        """A threshold that moved between runs would make a grade unfalsifiable."""
        built = build_consensus("m", self.identical_books())
        assert built.null_edge(0) == built.null_edge(0)
