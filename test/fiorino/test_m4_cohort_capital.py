"""
M4 specification — cohort sizing and the capital constraint.

These tests pin down the behaviour the backtest engine must have BEFORE the
engine exists. They test the rule, not the machinery.

The bug being legislated against: three matches kicking off at 15:00, each
sized at 50% of "current" bankroll, settled sequentially so that each stake
compounds on results not yet knowable.

    FORBIDDEN   100 -> 50 -> 75 -> 112.50
    REQUIRED    every stake sized against ONE equity snapshot -> 50, 50, 50
                then constrained to fit available capital
"""

from decimal import Decimal

import pytest

from fiorino.core.capital import (
    CENT,
    CapitalDecision,
    OversizePolicy,
    apply_capital_constraint,
)

BANKROLL = Decimal("100")
KICKOFF = "2025-03-01T15:00:00Z"
FORBIDDEN_SEQUENCE = (Decimal("50"), Decimal("75"), Decimal("112.50"))


def size_cohort(equity: Decimal, fractions: list[Decimal]) -> list[Decimal]:
    """Size every bet in a cohort against the SAME equity snapshot.

    This is the one-line specification of a cohort. Any implementation that
    threads a mutating bankroll through this loop is wrong.
    """
    return [(equity * f).quantize(CENT) for f in fractions]


class TestCohortSizing:
    """Three simultaneous matches must be sized against one bankroll."""

    def test_three_matches_at_same_kickoff_request_equal_stakes(self):
        stakes = size_cohort(BANKROLL, [Decimal("0.5")] * 3)
        assert stakes == [Decimal("50.00")] * 3

    def test_sequential_compounding_sequence_is_never_produced(self):
        """The exact regression: 50 / 75 / 112.50 must be unreachable."""
        stakes = tuple(size_cohort(BANKROLL, [Decimal("0.5")] * 3))
        assert stakes != FORBIDDEN_SEQUENCE
        assert stakes[1] == stakes[0], "second bet saw the first bet's result"
        assert stakes[2] == stakes[0], "third bet compounded on earlier results"

    def test_no_stake_exceeds_the_starting_bankroll(self):
        for stake in size_cohort(BANKROLL, [Decimal("0.5")] * 3):
            assert stake <= BANKROLL

    @pytest.mark.parametrize("n_matches", [1, 2, 3, 5, 10])
    def test_stakes_are_identical_regardless_of_cohort_size(self, n_matches):
        stakes = size_cohort(BANKROLL, [Decimal("0.25")] * n_matches)
        assert len(set(stakes)) == 1
        assert stakes[0] == Decimal("25.00")


class TestCapitalConstraint:
    """An oversized cohort is resolved by an explicit, declared rule."""

    REQUESTED = [Decimal("50")] * 3  # 150 requested against 100 available

    def test_requested_total_exceeds_available(self):
        assert sum(self.REQUESTED) > BANKROLL

    def test_reject_places_nothing(self):
        d = apply_capital_constraint(self.REQUESTED, BANKROLL, OversizePolicy.REJECT)
        assert d.rejected and d.was_constrained
        assert d.total == Decimal("0")

    def test_pro_rata_scales_every_stake_by_the_same_factor(self):
        d = apply_capital_constraint(
            self.REQUESTED, BANKROLL, OversizePolicy.SCALE_PRO_RATA
        )
        assert d.was_constrained and not d.rejected
        assert d.stakes == (Decimal("33.33"),) * 3
        assert d.total <= BANKROLL

    def test_truncate_by_rank_fills_the_best_bets_first(self):
        d = apply_capital_constraint(
            self.REQUESTED,
            BANKROLL,
            OversizePolicy.TRUNCATE_BY_RANK,
            rank=[0.02, 0.09, 0.05],
        )
        assert d.stakes[1] == Decimal("50.00")  # best edge, filled
        assert d.stakes[2] == Decimal("50.00")  # second best, filled
        assert d.stakes[0] == Decimal("0.00")   # worst edge, no capital left
        assert d.total <= BANKROLL

    @pytest.mark.parametrize("policy", list(OversizePolicy))
    def test_capital_invariant_holds_under_every_policy(self, policy):
        """The one invariant that must never break."""
        rank = [1.0, 2.0, 3.0] if policy is OversizePolicy.TRUNCATE_BY_RANK else None
        d = apply_capital_constraint(self.REQUESTED, BANKROLL, policy, rank=rank)
        assert d.total <= d.available
        assert all(s >= 0 for s in d.stakes)

    @pytest.mark.parametrize("policy", list(OversizePolicy))
    def test_a_cohort_that_fits_is_left_untouched(self, policy):
        requested = [Decimal("20"), Decimal("30"), Decimal("10")]
        rank = [3.0, 2.0, 1.0] if policy is OversizePolicy.TRUNCATE_BY_RANK else None
        d = apply_capital_constraint(requested, BANKROLL, policy, rank=rank)
        assert not d.was_constrained and not d.rejected
        assert d.stakes == (Decimal("20.00"), Decimal("30.00"), Decimal("10.00"))

    def test_open_exposure_reduces_available_capital(self):
        """Capital committed to an earlier kickoff is not available again."""
        equity, open_exposure = Decimal("100"), Decimal("40")
        available = equity - open_exposure
        d = apply_capital_constraint(
            [Decimal("30"), Decimal("30")], available, OversizePolicy.SCALE_PRO_RATA
        )
        assert d.total <= Decimal("60")

    def test_zero_available_capital_places_nothing(self):
        d = apply_capital_constraint(
            self.REQUESTED, Decimal("0"), OversizePolicy.SCALE_PRO_RATA
        )
        assert d.total == Decimal("0")

    def test_rounding_never_breaches_available_capital(self):
        """Pro-rata on an awkward divisor must round down, never up."""
        d = apply_capital_constraint(
            [Decimal("10")] * 7, Decimal("33.33"), OversizePolicy.SCALE_PRO_RATA
        )
        assert d.total <= Decimal("33.33")

    def test_negative_stake_is_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            apply_capital_constraint([Decimal("-1")], BANKROLL)

    def test_truncate_by_rank_requires_a_rank(self):
        with pytest.raises(ValueError, match="rank"):
            apply_capital_constraint(
                self.REQUESTED, BANKROLL, OversizePolicy.TRUNCATE_BY_RANK
            )


class TestDecisionReporting:
    """The decision must be auditable after the fact."""

    def test_decision_records_what_was_asked_for(self):
        d = apply_capital_constraint([Decimal("50")] * 3, BANKROLL)
        assert isinstance(d, CapitalDecision)
        assert d.requested_total == Decimal("150")
        assert d.available == BANKROLL
        assert d.policy is OversizePolicy.SCALE_PRO_RATA

    def test_utilisation_reports_capital_actually_deployed(self):
        d = apply_capital_constraint([Decimal("50")] * 3, BANKROLL)
        assert Decimal("0.99") <= d.utilisation <= Decimal("1.0")
