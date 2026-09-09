"""
The no-bet engine.

The screen is what a person acts on, so the rule that keeps it honest belongs
in tested code rather than in a template. Most of this file is about the
ceiling.
"""

from datetime import timedelta

import pytest

from fiorino.decision import LEVELS, SignalLevel, classify, promoted_strategies
from fiorino.decision.signal import MIN_SETTLED, PROMOTED, STALE_AFTER


class TestTheCeiling:
    def test_no_strategy_is_promoted_today(self):
        """The current state of the evidence, asserted so that changing it is
        a deliberate act with a test to update."""
        assert promoted_strategies() == {}

    def test_nothing_can_exceed_watch_while_nothing_is_promoted(self):
        """Even a perfect input. The ceiling is construction, not convention."""
        decision = classify(edge=0.99, n_settled=100_000,
                            historical_clv=0.25, clv_t_stat=40.0,
                            strategy="anything")
        assert decision.level == SignalLevel.WATCH
        # CANDIDATE and not QUALIFIED: an unpromoted strategy name buys
        # nothing, which is the second half of the same rule.
        assert decision.uncapped_level == SignalLevel.CANDIDATE
        assert decision.capped_by

    def test_the_cap_is_reported_not_hidden(self):
        decision = classify(edge=0.10, n_settled=500, historical_clv=0.02)
        assert "NOT_PROMOTED" in {r.code for r in decision.reasons}
        assert "CANDIDATE" in decision.explain()

    def test_promoting_a_strategy_lifts_the_ceiling(self, monkeypatch):
        """Proves the ceiling is a mechanism and not a hardcoded return."""
        monkeypatch.setitem(PROMOTED, "demo", {"gates": "all"})
        decision = classify(edge=0.10, strategy="demo", n_settled=500,
                            historical_clv=0.02, clv_t_stat=3.0)
        assert decision.level == SignalLevel.QUALIFIED

    def test_there_is_no_bet_level(self):
        """A fifth level exists in the roadmap and must not exist in code:
        adding it is a decision that needs a promotion record."""
        assert "BET" not in LEVELS
        assert not hasattr(SignalLevel, "BET")


class TestDisqualifiers:
    def test_a_pit_violation_stops_everything(self):
        decision = classify(edge=0.5, pit_violations=3, n_settled=999,
                            historical_clv=0.5)
        assert decision.level == SignalLevel.NO_SIGNAL
        assert decision.reasons[0].code == "PIT_VIOLATION"

    def test_stale_data_is_reported_as_stale_not_as_an_edge(self):
        """Order matters: a reader who stops at the first line must not be
        told there is an edge when the price is two hours old."""
        decision = classify(edge=0.5, data_age=STALE_AFTER + timedelta(minutes=1),
                            n_settled=999, historical_clv=0.5)
        assert decision.level == SignalLevel.NO_SIGNAL
        assert decision.reasons[0].code == "STALE_DATA"

    def test_fresh_data_passes(self):
        decision = classify(edge=0.05, data_age=timedelta(minutes=2),
                            n_settled=500, historical_clv=0.02)
        assert decision.level == SignalLevel.WATCH

    def test_no_prediction_is_no_signal(self):
        assert classify(edge=None).level == SignalLevel.NO_SIGNAL

    def test_an_edge_below_threshold_is_no_signal(self):
        assert classify(edge=0.01, min_edge=0.02).level == SignalLevel.NO_SIGNAL


class TestEvidenceGrading:
    def test_a_negative_clv_history_is_rejection_not_uncertainty(self):
        """M6 found model_edge negative in 30 cases out of 30. Showing those as
        WATCH would fill the screen with things already disproved."""
        decision = classify(edge=0.20, n_settled=676,
                            historical_clv=-0.0336, clv_t_stat=-12.3)
        assert decision.level == SignalLevel.NO_SIGNAL
        assert "NEGATIVE_CLV" in {r.code for r in decision.reasons}

    def test_a_thin_sample_is_watch_not_candidate(self):
        decision = classify(edge=0.10, n_settled=MIN_SETTLED - 1,
                            historical_clv=0.05)
        assert decision.level == SignalLevel.WATCH
        assert "THIN_SAMPLE" in {r.code for r in decision.reasons}

    def test_no_clv_history_is_watch(self):
        decision = classify(edge=0.10, n_settled=500, historical_clv=None)
        assert decision.level == SignalLevel.WATCH
        assert "NO_CLV_HISTORY" in {r.code for r in decision.reasons}

    def test_a_league_prior_prediction_never_reaches_candidate(self):
        """Betting hardest where the model knows least is the failure mode M5
        named. It must not be reachable from the screen either."""
        decision = classify(edge=0.30, n_settled=5000, historical_clv=0.10,
                            used_prior=True)
        assert decision.uncapped_level == SignalLevel.WATCH
        assert "LEAGUE_PRIOR" in {r.code for r in decision.reasons}

    def test_positive_clv_reaches_candidate_before_the_cap(self):
        decision = classify(edge=0.10, n_settled=500, historical_clv=0.02,
                            clv_t_stat=3.0)
        assert decision.uncapped_level == SignalLevel.CANDIDATE


class TestTheBlackBox:
    def test_every_decision_carries_its_reasons(self):
        for kwargs in ({"edge": None},
                       {"edge": 0.001},
                       {"edge": 0.2, "pit_violations": 1},
                       {"edge": 0.2, "n_settled": 500, "historical_clv": 0.02}):
            assert classify(**kwargs).reasons

    def test_reasons_name_a_measurement_and_a_threshold(self):
        """'The model likes it' is not a reason."""
        decision = classify(edge=0.0123, min_edge=0.02)
        detail = decision.reasons[0].detail
        assert "0.0123" in detail and "0.0200" in detail

    def test_blocking_reasons_are_separable(self):
        decision = classify(edge=0.10, n_settled=500, historical_clv=0.02)
        assert any(r.supports for r in decision.reasons)
        assert decision.blocking

    def test_explain_mentions_both_sides(self):
        text = classify(edge=0.10, n_settled=500, historical_clv=0.02).explain()
        assert "+" in text and "-" in text
