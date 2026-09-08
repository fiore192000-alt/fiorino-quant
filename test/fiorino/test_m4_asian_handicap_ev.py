"""
M4/M5 specification — Asian handicap settlement structure and EV.

The rule these tests enforce: the outcome structure stays explicit. Nothing in
the system may collapse a market to a single ``prob_win``.

Line types covered:
  * whole line   (-1.0, 0.0)   can PUSH
  * half line    (-0.5, +0.5)  two states only
  * quarter line (-0.25, +0.75) can HALF_WIN or HALF_LOSE

The concrete error being legislated against: with p_win=0.42, p_push=0.08,
p_lose=0.50 at price 2.60 the true edge is +17.2%, while the two-state formula
reports +9.2% — understated by exactly p_push. Under a 10% threshold the bet
is wrongly rejected.
"""

import math

import pytest

from fiorino.core.markets import (
    Outcome,
    OutcomeStructure,
    Side,
    asian_handicap_outcomes,
    is_quarter_line,
    one_x_two_outcomes,
    return_multiplier,
    totals_outcomes,
)

# home wins by 2 | home wins by 1 | draw | away wins by 1 | away wins by 2
SPREAD = {(3, 1): 0.20, (2, 1): 0.25, (1, 1): 0.20, (1, 2): 0.20, (1, 3): 0.15}


class TestReturnMultiplier:
    """Gross return per unit staked, stake included."""

    @pytest.mark.parametrize(
        "outcome,price,expected",
        [
            (Outcome.WIN, 2.00, 2.00),
            (Outcome.HALF_WIN, 2.00, 1.50),   # 1 + (2.00-1)/2
            (Outcome.PUSH, 2.00, 1.00),       # stake returned
            (Outcome.HALF_LOSE, 2.00, 0.50),  # half the stake back
            (Outcome.LOSE, 2.00, 0.00),
            (Outcome.HALF_WIN, 3.40, 2.20),   # 1 + (3.40-1)/2
        ],
    )
    def test_multipliers(self, outcome, price, expected):
        assert return_multiplier(outcome, price) == pytest.approx(expected)

    def test_price_must_exceed_one(self):
        with pytest.raises(ValueError, match="exceed 1.0"):
            return_multiplier(Outcome.WIN, 1.0)


class TestLineClassification:
    @pytest.mark.parametrize("line", [-0.25, 0.25, -0.75, 1.75, 2.25])
    def test_quarter_lines_detected(self, line):
        assert is_quarter_line(line)

    @pytest.mark.parametrize("line", [-1.0, -0.5, 0.0, 0.5, 1.0, 2.5])
    def test_whole_and_half_lines_are_not_quarters(self, line):
        assert not is_quarter_line(line)


class TestWholeLine:
    """Integer lines push when the handicap exactly cancels the margin."""

    def test_level_ball_pushes_on_a_draw(self, exact_grid):
        s = asian_handicap_outcomes(exact_grid(SPREAD), Side.HOME, 0.0)
        assert s.win == pytest.approx(0.45)   # home by 1 or 2
        assert s.push == pytest.approx(0.20)  # the draw
        assert s.lose == pytest.approx(0.35)
        assert s.half_win == 0.0 and s.half_lose == 0.0

    def test_minus_one_pushes_when_home_wins_by_exactly_one(self, exact_grid):
        s = asian_handicap_outcomes(exact_grid(SPREAD), Side.HOME, -1.0)
        assert s.win == pytest.approx(0.20)   # home by 2
        assert s.push == pytest.approx(0.25)  # home by exactly 1
        assert s.lose == pytest.approx(0.55)

    def test_whole_line_flags_push_risk(self, exact_grid):
        s = asian_handicap_outcomes(exact_grid(SPREAD), Side.HOME, 0.0)
        assert s.has_push_risk


class TestHalfLine:
    """Half lines cannot push: a genuine two-state bet."""

    def test_minus_half_is_a_home_win_bet(self, exact_grid):
        s = asian_handicap_outcomes(exact_grid(SPREAD), Side.HOME, -0.5)
        assert s.win == pytest.approx(0.45)
        assert s.lose == pytest.approx(0.55)
        assert s.push == 0.0
        assert not s.has_push_risk

    def test_plus_half_is_a_double_chance_bet(self, exact_grid):
        s = asian_handicap_outcomes(exact_grid(SPREAD), Side.HOME, 0.5)
        assert s.win == pytest.approx(0.65)  # home win or draw
        assert s.lose == pytest.approx(0.35)


class TestQuarterLine:
    """Quarter lines split the stake over two adjacent half-lines."""

    def test_minus_quarter_half_loses_on_a_draw(self, exact_grid):
        """-0.25 = half at 0.0 (push) + half at -0.5 (lose) -> HALF_LOSE."""
        s = asian_handicap_outcomes(exact_grid(SPREAD), Side.HOME, -0.25)
        assert s.win == pytest.approx(0.45)
        assert s.half_lose == pytest.approx(0.20)  # the draw
        assert s.lose == pytest.approx(0.35)
        assert s.half_win == 0.0 and s.push == 0.0

    def test_plus_quarter_half_wins_on_a_draw(self, exact_grid):
        """+0.25 = half at 0.0 (push) + half at +0.5 (win) -> HALF_WIN."""
        s = asian_handicap_outcomes(exact_grid(SPREAD), Side.HOME, 0.25)
        assert s.win == pytest.approx(0.45)
        assert s.half_win == pytest.approx(0.20)
        assert s.lose == pytest.approx(0.35)
        assert s.push == 0.0 and s.half_lose == 0.0

    def test_minus_three_quarter_half_wins_on_a_one_goal_win(self, exact_grid):
        """-0.75 = half at -0.5 (win) + half at -1.0 (push) -> HALF_WIN."""
        s = asian_handicap_outcomes(exact_grid(SPREAD), Side.HOME, -0.75)
        assert s.win == pytest.approx(0.20)       # home by 2
        assert s.half_win == pytest.approx(0.25)  # home by exactly 1
        assert s.lose == pytest.approx(0.55)

    def test_quarter_lines_never_produce_a_full_push(self, exact_grid, poisson_grid):
        for line in (-0.25, 0.25, -0.75, 0.75, 1.25):
            for grid in (exact_grid(SPREAD), poisson_grid(1.5, 1.2)):
                s = asian_handicap_outcomes(grid, Side.HOME, line)
                assert s.push == 0.0, f"quarter line {line} produced a full push"


class TestHomeAwaySymmetry:
    """Rule R3: lines are always stored from the home team's perspective."""

    def test_away_plus_half_is_stored_as_home_minus_half(self, exact_grid):
        grid = exact_grid(SPREAD)
        away = asian_handicap_outcomes(grid, Side.AWAY, -0.5)
        assert away.win == pytest.approx(0.55)  # away win or draw
        assert away.lose == pytest.approx(0.45)

    @pytest.mark.parametrize("line", [-1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 1.0])
    def test_the_two_sides_of_a_line_are_complementary(self, exact_grid, line):
        """Home win mass must equal away lose mass, and vice versa."""
        grid = exact_grid(SPREAD)
        h = asian_handicap_outcomes(grid, Side.HOME, line)
        a = asian_handicap_outcomes(grid, Side.AWAY, line)
        assert h.win == pytest.approx(a.lose)
        assert h.lose == pytest.approx(a.win)
        assert h.push == pytest.approx(a.push)
        assert h.half_win == pytest.approx(a.half_lose)
        assert h.half_lose == pytest.approx(a.half_win)


class TestExpectedValue:
    """The p_push correction — the reason this module exists."""

    #: Integer AH line at 2.60. The exact case from the architecture doc.
    STRUCT = OutcomeStructure(win=0.42, push=0.08, lose=0.50)
    PRICE = 2.60

    def test_correct_ev_accounts_for_the_returned_stake(self):
        assert self.STRUCT.expected_value(self.PRICE) == pytest.approx(0.172)

    def test_two_state_formula_understates_the_edge_by_exactly_p_push(self):
        naive = self.STRUCT.win * (self.PRICE - 1) - (1 - self.STRUCT.win)
        correct = self.STRUCT.expected_value(self.PRICE)
        assert naive == pytest.approx(0.092)
        assert correct - naive == pytest.approx(self.STRUCT.push)

    def test_a_ten_percent_threshold_flips_the_decision(self):
        """The failure this suite exists to prevent."""
        threshold = 0.10
        naive = self.STRUCT.win * (self.PRICE - 1) - (1 - self.STRUCT.win)
        assert naive < threshold, "naive EV would reject"
        assert self.STRUCT.expected_value(self.PRICE) > threshold, "correct EV accepts"

    def test_ev_matches_the_closed_form_for_three_states(self):
        s, price = self.STRUCT, self.PRICE
        assert s.expected_value(price) == pytest.approx(s.win * price + s.push - 1)

    def test_ev_is_zero_at_the_fair_price(self):
        s = OutcomeStructure(win=0.5, lose=0.5)
        assert s.expected_value(2.0) == pytest.approx(0.0)

    def test_push_probability_raises_ev_at_a_fixed_price(self):
        """Moving mass from LOSE to PUSH must strictly improve the bet."""
        low = OutcomeStructure(win=0.42, push=0.00, lose=0.58)
        high = OutcomeStructure(win=0.42, push=0.16, lose=0.42)
        assert high.expected_value(2.6) > low.expected_value(2.6)

    def test_quarter_line_ev_sits_between_its_two_component_lines(self, exact_grid):
        grid, price = exact_grid(SPREAD), 2.10
        ev_0 = asian_handicap_outcomes(grid, Side.HOME, 0.0).expected_value(price)
        ev_q = asian_handicap_outcomes(grid, Side.HOME, -0.25).expected_value(price)
        ev_h = asian_handicap_outcomes(grid, Side.HOME, -0.5).expected_value(price)
        assert min(ev_0, ev_h) <= ev_q <= max(ev_0, ev_h)


class TestKellyWithPush:
    """Stake sizing across three and five outcome states."""

    def test_closed_form_matches_direct_optimisation(self):
        s = OutcomeStructure(win=0.50, push=0.10, lose=0.40)
        price = 2.20
        f = s.kelly_fraction(price)
        # numerically confirm it is the growth-optimal point
        g = s.expected_log_growth(price, f)
        for delta in (-0.01, -0.001, 0.001, 0.01):
            assert s.expected_log_growth(price, f + delta) <= g + 1e-12
        assert f == pytest.approx(0.18519, abs=1e-5)

    def test_reduces_to_standard_kelly_without_push(self):
        s = OutcomeStructure(win=0.55, lose=0.45)
        price, b = 2.0, 1.0
        assert s.kelly_fraction(price) == pytest.approx((0.55 * b - 0.45) / b)

    def test_quarter_line_needs_the_numeric_solve(self):
        """Five states give a materially different answer to three."""
        five = OutcomeStructure(
            win=0.30, half_win=0.14, push=0.0, half_lose=0.16, lose=0.40
        )
        price = 2.60
        f5 = five.kelly_fraction(price)
        b = price - 1
        f3 = (five.win * b - five.lose) / (b * (five.win + five.lose))
        assert f5 == pytest.approx(0.09061, abs=1e-4)
        assert not math.isclose(f5, f3, rel_tol=1e-3)
        g = five.expected_log_growth(price, f5)
        for delta in (-0.005, 0.005):
            assert five.expected_log_growth(price, f5 + delta) <= g + 1e-12

    def test_no_stake_on_a_negative_edge(self):
        s = OutcomeStructure(win=0.30, push=0.05, lose=0.65)
        assert s.expected_value(2.0) < 0
        assert s.kelly_fraction(2.0) == 0.0

    def test_fraction_scales_the_stake(self):
        s = OutcomeStructure(win=0.55, lose=0.45)
        assert s.kelly_fraction(2.0, fraction=0.25) == pytest.approx(
            s.kelly_fraction(2.0) * 0.25
        )

    def test_stake_never_exceeds_the_bankroll(self, poisson_grid):
        s = OutcomeStructure(win=0.99, lose=0.01)
        assert 0.0 <= s.kelly_fraction(50.0) <= 1.0


class TestOutcomeStructureValidation:
    def test_probabilities_must_sum_to_one(self):
        with pytest.raises(ValueError, match="sum to 1.0"):
            OutcomeStructure(win=0.5, lose=0.3)

    def test_negative_probability_is_rejected(self):
        with pytest.raises(ValueError, match="out of range"):
            OutcomeStructure(win=1.2, lose=-0.2)

    @pytest.mark.parametrize("line", [-1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 1.0])
    def test_derived_structures_are_always_valid(self, poisson_grid, line):
        s = asian_handicap_outcomes(poisson_grid(1.6, 1.1), Side.HOME, line)
        assert sum(s.as_dict().values()) == pytest.approx(1.0)


class TestTotals:
    """Over/under carries the same five-state structure as the handicap."""

    def test_integer_total_can_push(self, exact_grid):
        # totals: 4, 3, 2, 3, 4
        s = totals_outcomes(exact_grid(SPREAD), Side.OVER, 3.0)
        assert s.win == pytest.approx(0.35)   # totals of 4
        assert s.push == pytest.approx(0.45)  # totals of exactly 3
        assert s.lose == pytest.approx(0.20)

    def test_half_total_cannot_push(self, exact_grid):
        s = totals_outcomes(exact_grid(SPREAD), Side.OVER, 2.5)
        assert s.push == 0.0
        assert s.win == pytest.approx(0.80)

    def test_quarter_total_half_loses(self, exact_grid):
        s = totals_outcomes(exact_grid(SPREAD), Side.UNDER, 2.75)
        assert s.half_win == pytest.approx(0.0)
        assert s.half_lose == pytest.approx(0.45)  # totals of exactly 3

    def test_over_and_under_are_complementary(self, poisson_grid):
        grid = poisson_grid(1.4, 1.3)
        for line in (2.0, 2.5, 2.75, 3.0):
            o = totals_outcomes(grid, Side.OVER, line)
            u = totals_outcomes(grid, Side.UNDER, line)
            assert o.win == pytest.approx(u.lose)
            assert o.push == pytest.approx(u.push)
            assert o.half_win == pytest.approx(u.half_lose)


class TestOneXTwo:
    """1X2 genuinely is two-state, and must not pretend otherwise."""

    def test_never_pushes(self, exact_grid):
        for sel in ("HOME", "DRAW", "AWAY"):
            s = one_x_two_outcomes(exact_grid(SPREAD), sel)
            assert not s.has_push_risk

    def test_probabilities_sum_across_the_three_selections(self, exact_grid):
        grid = exact_grid(SPREAD)
        total = sum(one_x_two_outcomes(grid, s).win for s in ("HOME", "DRAW", "AWAY"))
        assert total == pytest.approx(1.0)
