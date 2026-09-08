"""
M3 specification — Closing Line Value arithmetic.

CLV is measured against the REFERENCE book's de-vigged closing price for the
identical (market_type, line, selection). These tests pin the arithmetic and
the sign conventions before the M3 module wires it to the database.
"""

import math

import pytest

from fiorino.clv.formulas import beat_close, clv_ev, clv_log, clv_price


class TestClvPrice:
    def test_a_better_price_than_the_close_is_positive(self):
        assert clv_price(2.75, 2.40) == pytest.approx(0.145833, abs=1e-6)

    def test_a_worse_price_than_the_close_is_negative(self):
        assert clv_price(2.10, 2.40) < 0

    def test_taking_the_closing_price_is_exactly_zero(self):
        assert clv_price(2.40, 2.40) == pytest.approx(0.0)


class TestClvEv:
    """The headline number: expected ROI if the close is the truth."""

    def test_matches_the_worked_example(self):
        # took 2.75; sharp closed 2.40 in a 3.02% overround market
        assert clv_ev(0.4044, 2.75) == pytest.approx(0.11210, abs=1e-4)

    def test_is_zero_when_the_price_equals_the_fair_price(self):
        assert clv_ev(0.5, 2.0) == pytest.approx(0.0)

    def test_is_negative_below_the_fair_price(self):
        assert clv_ev(0.40, 2.40) < 0

    def test_is_on_the_same_scale_as_yield(self):
        """A +11% CLV must be directly comparable to a +11% yield."""
        assert clv_ev(0.4044, 2.75) == pytest.approx(0.4044 * 2.75 - 1)


class TestClvLog:
    def test_shares_the_sign_of_clv_ev(self):
        for p, price in [(0.4044, 2.75), (0.40, 2.40), (0.5, 2.0)]:
            assert math.copysign(1, clv_log(p, price)) == math.copysign(
                1, clv_ev(p, price)
            ) or clv_ev(p, price) == pytest.approx(0.0)

    def test_is_additive_across_bets(self):
        """Two bets in sequence compose by addition, unlike the ratio form."""
        a, b = clv_log(0.45, 2.40), clv_log(0.40, 2.70)
        combined = math.log((0.45 * 2.40) * (0.40 * 2.70))
        assert a + b == pytest.approx(combined)

    def test_is_smaller_than_clv_ev_for_positive_value(self):
        """ln(1+x) < x — this is why the log form avoids the ratio bias."""
        assert clv_log(0.4044, 2.75) < clv_ev(0.4044, 2.75)


class TestBeatClose:
    def test_true_when_the_struck_price_is_better(self):
        assert beat_close(2.75, 2.40)

    def test_false_at_or_below_the_close(self):
        assert not beat_close(2.40, 2.40)
        assert not beat_close(2.10, 2.40)


class TestSignAgreement:
    """A bet that beat the close on price must not show negative EV CLV."""

    @pytest.mark.parametrize(
        "fair_prob,closing_price,price_taken",
        [(0.4044, 2.40, 2.75), (0.5000, 1.95, 2.10), (0.2500, 3.80, 4.20)],
    )
    def test_beating_the_close_implies_positive_ev(
        self, fair_prob, closing_price, price_taken
    ):
        assert beat_close(price_taken, closing_price)
        assert clv_price(price_taken, closing_price) > 0
        # holds whenever the closing market carries a non-negative overround
        assert clv_ev(fair_prob, price_taken) > clv_ev(fair_prob, closing_price)


class TestValidation:
    def test_price_at_or_below_one_is_rejected(self):
        with pytest.raises(ValueError, match="price_taken"):
            clv_ev(0.5, 1.0)

    def test_closing_price_at_or_below_one_is_rejected(self):
        with pytest.raises(ValueError, match="closing_price"):
            clv_price(2.0, 1.0)

    @pytest.mark.parametrize("p", [0.0, 1.0, -0.1, 1.5])
    def test_probability_outside_the_open_unit_interval_is_rejected(self, p):
        with pytest.raises(ValueError, match="closing_fair_prob"):
            clv_ev(p, 2.0)
