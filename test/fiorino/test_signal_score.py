"""
Signal quality is not edge size.

The shape of the score is the argument: anything that averages a gate with a
grade will eventually recommend a bet on a two-hour-old price because the edge
looked big.
"""

from datetime import timedelta

import pytest

from fiorino.decision import GATES, GRADED_WEIGHTS, score_signal

STRONG = dict(edge=0.03, historical_clv=0.02, n_settled=2000, replications=2,
              adversarial_passed=10)


class TestGatesDominate:
    @pytest.mark.parametrize("kwargs,gate", [
        (dict(pit_violations=1), "pit_confidence"),
        (dict(data_age=timedelta(hours=2)), "freshness"),
        (dict(executable=False), "execution"),
    ])
    def test_a_failed_gate_zeroes_an_otherwise_perfect_signal(self, kwargs, gate):
        score = score_signal(**{**STRONG, **kwargs})
        assert score.value == 0.0
        assert score.failed_gate == gate

    def test_the_reason_is_reported_not_just_the_zero(self):
        """A score of zero is not informative. The reason for it is."""
        score = score_signal(**STRONG, data_age=timedelta(hours=2))
        assert score.weakest == "freshness"

    def test_every_gate_is_binary(self):
        score = score_signal(**STRONG)
        assert set(score.gates) == set(GATES)
        assert all(v in (0.0, 1.0) for v in score.gates.values())


class TestSizeDoesNotBuyBackEvidence:
    def test_a_huge_edge_on_a_tiny_sample_loses_to_a_small_replicated_one(self):
        """The property the whole module exists for."""
        huge = score_signal(edge=0.30, historical_clv=0.05, n_settled=9,
                            replications=0)
        modest = score_signal(edge=0.02, historical_clv=0.015, n_settled=6000,
                              replications=2, adversarial_passed=10)
        assert modest.value > huge.value

    def test_edge_saturates(self):
        """Past a plausible ceiling a bigger number means a bigger model error
        more often than a bigger edge: M5 found 1,037 selections claiming over
        5% from a model that loses to the close everywhere."""
        at = score_signal(edge=0.05, **{k: v for k, v in STRONG.items() if k != "edge"})
        far = score_signal(edge=2.00, **{k: v for k, v in STRONG.items() if k != "edge"})
        assert at.value == pytest.approx(far.value)

    def test_clv_saturates_too(self):
        a = score_signal(**{**STRONG, "historical_clv": 0.03})
        b = score_signal(**{**STRONG, "historical_clv": 0.50})
        assert a.value == pytest.approx(b.value)

    def test_negative_clv_scores_zero_on_that_component(self):
        score = score_signal(**{**STRONG, "historical_clv": -0.05})
        assert score.graded["clv"] == 0.0


class TestWeighting:
    def test_clv_outweighs_edge(self):
        """M4 measured the CLV verdict correct 30/30 and the yield verdict
        23/30, and edge is closer in kind to yield."""
        assert GRADED_WEIGHTS["clv"] > GRADED_WEIGHTS["edge"]

    def test_replication_outweighs_edge(self):
        assert GRADED_WEIGHTS["replication"] > GRADED_WEIGHTS["edge"]

    def test_the_weights_are_a_proper_mixture(self):
        assert sum(GRADED_WEIGHTS.values()) == pytest.approx(1.0)

    def test_an_empty_signal_scores_zero(self):
        assert score_signal().value == pytest.approx(0.0, abs=0.06)

    def test_the_score_stays_within_bounds(self):
        for kwargs in ({}, STRONG, {**STRONG, "edge": 99.0},
                       {**STRONG, "n_settled": 10**9}):
            assert 0.0 <= score_signal(**kwargs).value <= 1.0


class TestExplanation:
    def test_components_are_listed_worst_first(self):
        rows = score_signal(edge=0.05, historical_clv=0.0, n_settled=2000,
                            replications=2).explain()
        values = [r[1] for r in rows]
        assert values == sorted(values)

    def test_gates_and_grades_are_distinguishable(self):
        kinds = {r[2] for r in score_signal(**STRONG).explain()}
        assert kinds == {"gate", "graded"}
