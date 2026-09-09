"""
The hypothesis scanner, and the arithmetic it exists to defend against.

"Generate 100 hypotheses, backtest them all, keep the survivors" produces false
discoveries by construction, not by carelessness. Most of this file tests the
correction rather than the scan.
"""

import pytest

from fiorino.research.hypotheses import HYPOTHESES, SELECTIONS, Hypothesis
from fiorino.research.scan import ScanResult, benjamini_hochberg, scan


def _result(name, p, control=False):
    return ScanResult(hypothesis=name, selection="HOME", n_in=100, n_out=100,
                      bias_in=0.0, bias_out=0.0, delta=0.01, se=0.01, z=1.0,
                      p_value=p, positive_control=control)


class TestBenjaminiHochberg:
    def test_nothing_survives_when_every_null_is_true(self):
        """Twenty p-values drawn uniformly — which is what testing twenty true
        nulls looks like. One will be below 0.05 on average; none should be a
        discovery."""
        uniform = [_result(f"h{i}", (i + 1) / 21) for i in range(20)]
        benjamini_hochberg(uniform, q=0.10)
        assert not any(r.discovery for r in uniform)
        assert min(r.p_value for r in uniform) < 0.05, (
            "the fixture must contain a nominally significant p-value, or this "
            "test proves nothing"
        )

    def test_a_strong_effect_survives(self):
        strong = [_result("real", 0.0001)] + [
            _result(f"h{i}", (i + 1) / 21) for i in range(20)
        ]
        benjamini_hochberg(strong, q=0.10)
        assert [r.hypothesis for r in strong if r.discovery] == ["real"]

    def test_q_values_are_monotone_in_p(self):
        results = [_result(f"h{i}", p) for i, p in
                   enumerate([0.001, 0.01, 0.02, 0.2, 0.5, 0.9])]
        benjamini_hochberg(results)
        ordered = sorted(results, key=lambda r: r.p_value)
        qs = [r.q_value for r in ordered]
        assert qs == sorted(qs)

    def test_a_q_value_is_never_below_its_p_value(self):
        results = [_result(f"h{i}", p) for i, p in enumerate([0.001, 0.04, 0.3])]
        benjamini_hochberg(results)
        assert all(r.q_value >= r.p_value - 1e-12 for r in results)

    def test_controls_count_toward_the_family(self):
        """Excluding them would loosen the threshold for everything else."""
        with_controls = [_result("c", 0.5, control=True)] + [
            _result(f"h{i}", 0.02) for i in range(4)
        ]
        without = [_result(f"h{i}", 0.02) for i in range(4)]
        benjamini_hochberg(with_controls, q=0.10)
        benjamini_hochberg(without, q=0.10)
        q_with = next(r.q_value for r in with_controls if r.hypothesis == "h0")
        q_without = next(r.q_value for r in without if r.hypothesis == "h0")
        assert q_with > q_without

    def test_an_empty_family_is_not_an_error(self):
        assert benjamini_hochberg([], q=0.10) == []


@pytest.fixture
def synthetic(tmp_path):
    """A table where one situation is genuinely biased and the rest are not."""
    from fiorino.data.db.connection import connect

    con = connect()
    con.execute("""CREATE TABLE labelled (
        outcome VARCHAR, p_home DOUBLE, p_draw DOUBLE, p_away DOUBLE,
        raw_home DOUBLE, raw_draw DOUBLE, raw_away DOUBLE, flag BOOLEAN)""")
    rows = []
    # Outside the flag: the market is exactly right — HOME wins 45% of the time
    # and is priced at 0.45.
    for i in range(600):
        outcome = "HOME" if i % 20 < 9 else ("DRAW" if i % 20 < 14 else "AWAY")
        rows.append([outcome, 0.45, 0.25, 0.30, 0.47, 0.27, 0.32, False])
    # Inside the flag: HOME actually wins 65% while still priced at 0.45.
    for i in range(300):
        outcome = "HOME" if i % 20 < 13 else ("DRAW" if i % 20 < 17 else "AWAY")
        rows.append([outcome, 0.45, 0.25, 0.30, 0.47, 0.27, 0.32, True])
    con.executemany("INSERT INTO labelled VALUES (?,?,?,?,?,?,?,?)", rows)
    yield con
    con.close()


class TestScanFindsWhatIsThere:
    def test_a_planted_bias_is_detected(self, synthetic):
        """If the scanner cannot find a 20-point mispricing it cannot be
        trusted to report that smaller ones are absent."""
        planted = (Hypothesis("planted", "20-point HOME bias", "flag"),)
        results = benjamini_hochberg(scan(synthetic, hypotheses=planted, draws=300))
        home = next(r for r in results if r.selection == "HOME")
        assert home.delta == pytest.approx(0.20, abs=0.03)
        assert home.discovery

    def test_an_unbiased_split_is_not_detected(self, synthetic):
        """The same data, split on nothing. Must come back empty."""
        noise = (Hypothesis("noise", "arbitrary split", "rowid % 3 = 0"),)
        results = benjamini_hochberg(scan(synthetic, hypotheses=noise, draws=300))
        assert not any(r.discovery for r in results)

    def test_a_tiny_subset_is_skipped_rather_than_reported(self, synthetic):
        tiny = (Hypothesis("tiny", "almost nothing", "rowid < 5"),)
        assert scan(synthetic, hypotheses=tiny, draws=100) == []

    def test_the_scan_is_reproducible(self, synthetic):
        planted = (Hypothesis("planted", "x", "flag"),)
        first = scan(synthetic, hypotheses=planted, draws=200)
        second = scan(synthetic, hypotheses=planted, draws=200)
        assert [r.z for r in first] == [r.z for r in second]


class TestTheHypothesisFamily:
    def test_every_hypothesis_has_a_stated_rationale(self):
        """A predicate without a reason is a fishing expedition with a name."""
        for h in HYPOTHESES:
            assert len(h.rationale) > 40, h.name

    def test_names_are_unique(self):
        names = [h.name for h in HYPOTHESES]
        assert len(names) == len(set(names))

    def test_the_family_contains_positive_controls(self):
        assert sum(1 for h in HYPOTHESES if h.positive_control) >= 3

    def test_the_longshot_control_reads_raw_prices(self):
        """Shin de-vigging is designed to remove the favourite-longshot bias,
        so a control for it on fair probabilities would test the de-vig rather
        than the market."""
        control = next(h for h in HYPOTHESES if h.name == "control_longshot_raw")
        assert control.prob_source == "raw"

    def test_the_longshot_control_is_evaluated_per_selection(self):
        """The bug a positive control caught. A match-level predicate like
        'raw_home < 0.12 OR raw_away < 0.12' picks matches where one side is a
        longshot AND the other a heavy favourite, so testing HOME inside it
        averages the two and the bias cancels."""
        control = next(h for h in HYPOTHESES if h.name == "control_longshot_raw")
        assert control.selection_level
        assert "{prob}" in control.predicate

    def test_a_selection_level_predicate_splits_differently_per_selection(self):
        """Proves the two modes are not the same thing wearing two names."""
        from fiorino.data.db.connection import connect
        from fiorino.research.scan import _fetch

        con = connect()
        con.execute("""CREATE TABLE t AS SELECT * FROM (VALUES
            ('HOME', 0.80, 0.12, 0.08, 0.83, 0.14, 0.10))
            AS v(outcome, p_home, p_draw, p_away, raw_home, raw_draw, raw_away)""")
        home = _fetch(con, "t", "{prob} < 0.12", "raw", "HOME")
        away = _fetch(con, "t", "{prob} < 0.12", "raw", "AWAY")
        assert home[0][4] is False and away[0][4] is True
        con.close()

    def test_rest_hypotheses_come_in_symmetric_pairs(self):
        """A bias appearing on only one side of a symmetric pair is usually
        noise, and cannot be seen as such unless both sides are tested."""
        names = {h.name for h in HYPOTHESES}
        for a, b in (("home_short_rest", "away_short_rest"),
                     ("home_rest_advantage", "away_rest_advantage"),
                     ("home_congested", "away_congested")):
            assert a in names and b in names

    def test_selections_are_the_three_outcomes(self):
        assert SELECTIONS == ("HOME", "DRAW", "AWAY")
