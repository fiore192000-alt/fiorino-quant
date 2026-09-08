"""
M6 — the incremental-information experiment, and the leak it could introduce.

M6 adds exactly one parameter estimated from outcomes: the pool weight. That
makes it the only new path by which the future can reach the past, and most of
this file is about closing it.
"""

from datetime import datetime, timedelta, timezone

import pytest

from fiorino.models.ensemble import (
    DIAGNOSTIC_BOUNDS,
    FittedWeight,
    TrainingRow,
    fit_weight,
    pool,
)
from fiorino.models.scoring import Scores, paired_bootstrap, score_forecasts

UTC = timezone.utc


def _row(match_id, day, model, market, outcome):
    return TrainingRow(match_id, datetime(2020, 1, day, tzinfo=UTC), model, market, outcome)


class TestPool:
    def test_weight_zero_is_the_market(self):
        assert pool((0.7, 0.2, 0.1), (0.4, 0.3, 0.3), 0.0) == pytest.approx((0.4, 0.3, 0.3))

    def test_weight_one_is_the_model(self):
        assert pool((0.7, 0.2, 0.1), (0.4, 0.3, 0.3), 1.0) == pytest.approx((0.7, 0.2, 0.1))

    def test_the_pool_is_always_a_distribution(self):
        for w in (0.0, 0.13, 0.5, 0.87, 1.0):
            p = pool((0.55, 0.25, 0.20), (0.30, 0.35, 0.35), w)
            assert sum(p) == pytest.approx(1.0)
            assert all(x > 0 for x in p)

    def test_agreement_survives_any_weight(self):
        """Two forecasts that agree must pool to the thing they agree on."""
        same = (0.5, 0.3, 0.2)
        for w in (0.0, 0.25, 0.6, 1.0):
            assert pool(same, same, w) == pytest.approx(same)

    def test_the_pool_lies_between_its_sources(self):
        """The property a LINEAR pool of confident disagreement would break."""
        model, market = (0.80, 0.15, 0.05), (0.20, 0.30, 0.50)
        mid = pool(model, market, 0.5)
        assert market[0] < mid[0] < model[0]
        assert model[2] < mid[2] < market[2]


class TestWeightFittingIsPointInTime:
    """The test the whole milestone is allowed to exist because of."""

    def _sharply_split(self):
        """Training where the model is useless, test where it is perfect.

        Constructed so the two periods have OPPOSITE optima: a fitter that
        peeked at the test period would return a weight near 1, a correct one a
        weight near 0. Nothing subtle is needed to detect the leak — the two
        answers are at opposite ends of the interval.
        """
        train, test = [], []
        for i in range(60):
            outcome = i % 3
            # Model points confidently at the WRONG outcome; market is flat.
            wrong = (outcome + 1) % 3
            model = [0.05, 0.05, 0.05]
            model[wrong] = 0.90
            train.append(_row(f"tr{i}", 1 + i % 27, tuple(model),
                              (1 / 3, 1 / 3, 1 / 3), outcome))
        for i in range(60):
            outcome = i % 3
            # Model points confidently at the RIGHT outcome.
            model = [0.05, 0.05, 0.05]
            model[outcome] = 0.90
            test.append(_row(f"te{i}", 1 + i % 27, tuple(model),
                             (1 / 3, 1 / 3, 1 / 3), outcome))
        # Test matches settle strictly after the boundary.
        boundary = datetime(2021, 1, 1, tzinfo=UTC)
        test = [TrainingRow(r.match_id, boundary + timedelta(days=1 + i),
                            r.model, r.market, r.outcome)
                for i, r in enumerate(test)]
        return train, test, boundary

    def test_the_weight_ignores_matches_after_the_boundary(self):
        train, test, boundary = self._sharply_split()
        fitted = fit_weight(train + test, boundary)
        assert fitted is not None
        assert fitted.weight == pytest.approx(0.0, abs=0.01), (
            "the weight moved toward the test period: the fitter is peeking"
        )

    def test_the_test_period_alone_wants_the_opposite_weight(self):
        """Proves the previous test can fail — otherwise it proves nothing.

        On the test rows the optimum is at the far end of the interval. So a
        fitter that admitted them would have to move, and the boundary is the
        only thing holding the answer at zero.
        """
        _, test, boundary = self._sharply_split()
        peeking = fit_weight(test, boundary + timedelta(days=400))
        assert peeking is not None
        assert peeking.weight > 0.9

    def test_admitting_the_test_period_visibly_moves_the_answer(self):
        """And the two periods together land in between, which is what makes a
        partial leak detectable rather than merely possible."""
        train, test, boundary = self._sharply_split()
        clean = fit_weight(train + test, boundary)
        leaked = fit_weight(train + test, boundary + timedelta(days=400))
        assert clean.weight == pytest.approx(0.0, abs=0.01)
        assert leaked.weight > 0.2
        assert leaked.n_train == clean.n_train * 2

    def test_the_training_count_matches_what_was_admitted(self):
        train, test, boundary = self._sharply_split()
        fitted = fit_weight(train + test, boundary)
        assert fitted.n_train == len(train)

    def test_the_recorded_settlement_precedes_the_boundary(self):
        """The column v_weight_leakage audits."""
        train, test, boundary = self._sharply_split()
        fitted = fit_weight(train + test, boundary)
        assert fitted.train_max_settled_at < boundary

    def test_too_little_history_returns_none_rather_than_a_guess(self):
        train, _, boundary = self._sharply_split()
        assert fit_weight(train[:5], boundary) is None

    def test_a_boundary_before_everything_admits_nothing(self):
        train, _, _ = self._sharply_split()
        assert fit_weight(train, datetime(2019, 1, 1, tzinfo=UTC)) is None


class TestWeightRecoversWhatIsThere:
    def test_a_useless_model_gets_weight_zero(self):
        rows = []
        for i in range(90):
            outcome = i % 3
            rows.append(_row(f"m{i}", 1 + i % 27, (1 / 3, 1 / 3, 1 / 3),
                             (0.6 if outcome == 0 else 0.2,
                              0.6 if outcome == 1 else 0.2,
                              0.6 if outcome == 2 else 0.2), outcome))
        fitted = fit_weight(rows, datetime(2021, 1, 1, tzinfo=UTC))
        assert fitted.weight == pytest.approx(0.0, abs=0.02)

    def test_an_informative_model_gets_weight_above_zero(self):
        """The fitter has to be ABLE to find information, or a zero means
        nothing."""
        rows = []
        for i in range(90):
            outcome = i % 3
            model = [0.15, 0.15, 0.15]
            model[outcome] = 0.70
            rows.append(_row(f"m{i}", 1 + i % 27, tuple(model),
                             (1 / 3, 1 / 3, 1 / 3), outcome))
        fitted = fit_weight(rows, datetime(2021, 1, 1, tzinfo=UTC))
        assert fitted.weight > 0.9

    def test_an_anti_informative_model_is_visible_in_the_diagnostic(self):
        """Constrained to [0,1] it reads 0, same as 'adds nothing'. The
        unconstrained fit is what tells the two apart."""
        rows = []
        for i in range(90):
            outcome = i % 3
            wrong = (outcome + 1) % 3
            model = [0.15, 0.15, 0.15]
            model[wrong] = 0.70
            rows.append(_row(f"m{i}", 1 + i % 27, tuple(model),
                             (1 / 3, 1 / 3, 1 / 3), outcome))
        fitted = fit_weight(rows, datetime(2021, 1, 1, tzinfo=UTC))
        assert fitted.weight == pytest.approx(0.0, abs=0.02)
        assert fitted.unconstrained < -0.05
        assert fitted.unconstrained >= DIAGNOSTIC_BOUNDS[0]

    def test_the_in_sample_gain_is_never_negative(self):
        """w = 0 is feasible, so the pool cannot lose in sample. Which is
        exactly why an in-sample gain proves nothing."""
        rows = []
        for i in range(90):
            outcome = i % 3
            rows.append(_row(f"m{i}", 1 + i % 27, (0.4, 0.35, 0.25),
                             (1 / 3, 1 / 3, 1 / 3), outcome))
        fitted = fit_weight(rows, datetime(2021, 1, 1, tzinfo=UTC))
        assert fitted.market_logloss - fitted.train_logloss >= -1e-9


class TestScoringRules:
    def test_a_perfect_forecast_scores_zero(self):
        s = score_forecasts([(1.0, 0.0, 0.0), (0.0, 0.0, 1.0)], [0, 2])
        assert s.brier == pytest.approx(0.0, abs=1e-6)
        assert s.logloss == pytest.approx(0.0, abs=1e-6)
        assert s.rps == pytest.approx(0.0, abs=1e-6)

    def test_the_uniform_forecast_has_the_known_log_loss(self):
        s = score_forecasts([(1 / 3, 1 / 3, 1 / 3)] * 30, [i % 3 for i in range(30)])
        assert s.logloss == pytest.approx(1.0986, abs=1e-3)   # ln 3

    def test_rps_punishes_distance_on_the_result_axis(self):
        """The property Brier does not have: predicting HOME when AWAY wins is
        a worse miss than predicting DRAW when AWAY wins."""
        adjacent = score_forecasts([(0.0, 1.0, 0.0)], [2])
        distant = score_forecasts([(1.0, 0.0, 0.0)], [2])
        assert distant.rps > adjacent.rps
        assert distant.brier == pytest.approx(adjacent.brier)

    def test_forecasts_are_normalised_before_scoring(self):
        """A pooled forecast arrives proportional; scoring it unnormalised
        would reward whichever arm happened to sum low."""
        a = score_forecasts([(0.5, 0.3, 0.2)], [0])
        b = score_forecasts([(5.0, 3.0, 2.0)], [0])
        assert a.brier == pytest.approx(b.brier)
        assert a.logloss == pytest.approx(b.logloss)

    def test_brier_follows_the_m5_convention(self):
        """Per selection row, not per match: the M5 report is read beside this
        one, and a silent factor of three between them would be worse than
        either convention."""
        s = score_forecasts([(0.5, 0.3, 0.2)], [0])
        expected = ((0.5 - 1) ** 2 + 0.3 ** 2 + 0.2 ** 2) / 3
        assert s.brier == pytest.approx(expected)

    def test_a_confident_miss_is_bounded_in_brier_and_not_in_log_loss(self):
        mild = score_forecasts([(0.3, 0.4, 0.3)], [0])
        severe = score_forecasts([(0.001, 0.5, 0.499)], [0])
        assert severe.brier / mild.brier < 5
        assert severe.logloss / mild.logloss > 5

    def test_mismatched_lengths_are_refused(self):
        with pytest.raises(ValueError):
            score_forecasts([(0.5, 0.3, 0.2)], [0, 1])

    def test_an_empty_sample_is_refused(self):
        with pytest.raises(ValueError):
            score_forecasts([], [])


class TestPairedBootstrap:
    def _arms(self, n=200):
        outcomes = [i % 3 for i in range(n)]
        flat = [(1 / 3, 1 / 3, 1 / 3)] * n
        sharp = []
        for o in outcomes:
            p = [0.2, 0.2, 0.2]
            p[o] = 0.6
            sharp.append(tuple(p))
        return flat, sharp, outcomes

    def test_a_real_improvement_excludes_zero(self):
        flat, sharp, outcomes = self._arms()
        point, lo, hi = paired_bootstrap(flat, sharp, outcomes,
                                         lambda s: s.logloss, draws=300)
        assert point < 0          # lower log-loss is better
        assert hi < 0

    def test_an_identical_arm_gives_an_interval_containing_zero(self):
        flat, _, outcomes = self._arms()
        point, lo, hi = paired_bootstrap(flat, flat, outcomes,
                                         lambda s: s.logloss, draws=300)
        assert point == pytest.approx(0.0, abs=1e-9)
        assert lo <= 0 <= hi

    def test_it_is_reproducible(self):
        flat, sharp, outcomes = self._arms()
        first = paired_bootstrap(flat, sharp, outcomes, lambda s: s.logloss, draws=200)
        second = paired_bootstrap(flat, sharp, outcomes, lambda s: s.logloss, draws=200)
        assert first == second


# ---------------------------------------------------------------------------
# Against a real season, through the real database.
# ---------------------------------------------------------------------------
from pathlib import Path  # noqa: E402

from fiorino.backtest import ModelEdge  # noqa: E402
from fiorino.data.ingest.sources.footballdata import FootballData  # noqa: E402
from fiorino.data.lake import bronze_path, write_bronze  # noqa: E402
from fiorino.data.pipeline import ingest_bronze  # noqa: E402
from fiorino.models.incremental import (  # noqa: E402
    ENSEMBLE_ARM,
    MARKET_ARM,
    build_arms,
    walk_forward_ensemble,
)

REAL = (Path(__file__).parent / "fixtures" / "footballdata_e0_2017-18_real.csv").read_text()


@pytest.fixture(scope="module")
def blended_db(tmp_path_factory):
    """A real season, fitted walk-forward, then blended with the market."""
    from fiorino.data.db.connection import connect
    from fiorino.data.db.migrate import migrate
    from fiorino.data.identity.resolver import IdentityResolver
    from fiorino.data.pipeline import bootstrap_reference
    from fiorino.models.fitting import walk_forward

    con = connect()
    migrate(con)
    bootstrap_reference(con)
    lake = tmp_path_factory.mktemp("lake")
    rows = FootballData().parse(REAL, "ENG_PL", "2017-2018")
    write_bronze(con, [r.as_row() for r in rows],
                 bronze_path(lake, "footballdata", "ENG_PL", "2017-2018", "r"))
    ingest_bronze(con, lake, auto_register_unknown=True)
    for _ in range(5):
        proposals = con.execute(
            "SELECT proposal_id FROM team_alias_proposals WHERE status='PROPOSED'"
        ).fetchall()
        if not proposals:
            break
        resolver = IdentityResolver(con)
        for (pid,) in proposals:
            resolver.reject_proposal(pid, "test", "distinct club")
        con.execute("DELETE FROM match_quarantine")
        ingest_bronze(con, lake, auto_register_unknown=True)
    walk_forward(con, competition_id="ENG_PL", season_id="2017-2018",
                 step=timedelta(days=7))
    steps = walk_forward_ensemble(con, experiment="deployable",
                                  competition_id="ENG_PL", season_id="2017-2018")
    yield con, steps
    con.close()


class TestArmsAgainstRealData:
    def test_the_walk_produces_weights(self, blended_db):
        _, steps = blended_db
        assert len(steps) > 10

    def test_no_weight_trained_past_its_boundary(self, blended_db):
        """The audit view, on real data. It has to be able to fail, and the
        unit tests above prove that it can."""
        con, _ = blended_db
        assert con.execute("SELECT count(*) FROM v_weight_leakage").fetchone()[0] == 0

    def test_the_deployable_path_never_touched_a_closing_price(self, blended_db):
        con, _ = blended_db
        sources = con.execute(
            "SELECT DISTINCT market_source FROM ensemble_weights WHERE experiment='deployable'"
        ).fetchall()
        assert sources == [("PREMATCH",)]

    def test_both_arms_are_written_as_runs_the_engine_can_bet(self, blended_db):
        con, _ = blended_db
        names = {r[0] for r in con.execute(
            "SELECT DISTINCT model_name FROM model_runs").fetchall()}
        assert {MARKET_ARM, ENSEMBLE_ARM, "dixon_coles"} <= names

    def test_the_ensemble_is_not_fed_back_into_itself(self, blended_db):
        """build_arms must read the MODEL, never a previously written arm.
        Without the exclusion a second run would blend the blend."""
        con, _ = blended_db
        before = build_arms(con, "deployable", "ENG_PL")
        walk_forward_ensemble(con, experiment="deployable",
                              competition_id="ENG_PL", season_id="2017-2018")
        after = build_arms(con, "deployable", "ENG_PL")
        assert len(before) == len(after)
        assert [a.model for a in before] == [a.model for a in after]

    def test_the_model_arm_is_the_freshest_fit_before_kickoff(self, blended_db):
        con, _ = blended_db
        arms = build_arms(con, "deployable", "ENG_PL")
        assert arms
        for arm in arms[:50]:
            assert sum(arm.model) == pytest.approx(1.0, abs=1e-6)
            assert sum(arm.market) == pytest.approx(1.0, abs=1e-6)

    def test_the_arms_are_selected_separately_by_name(self, blended_db):
        """Without the model_name filter the freshest-fit window would mix the
        arms, and an ablation would compare each arm with itself."""
        con, _ = blended_db
        from fiorino.data.access.point_in_time import PointInTimeView

        match_ids = [r[0] for r in con.execute(
            """SELECT DISTINCT p.match_id FROM predictions p
               JOIN model_runs r ON r.model_run_id = p.model_run_id
               WHERE r.model_name = ? LIMIT 40""", [ENSEMBLE_ARM]).fetchall()]
        as_of = con.execute(
            "SELECT max(kickoff_utc) FROM v_analytic_matches").fetchone()[0]
        view = PointInTimeView.at(con, as_of)

        picked = {}
        for name in (MARKET_ARM, ENSEMBLE_ARM, "dixon_coles"):
            candidates = ModelEdge(min_edge=0.0, model_name=name).generate(view, match_ids)
            picked[name] = {(c.match_id, c.selection): c.model_prob for c in candidates}
        assert picked[MARKET_ARM] and picked["dixon_coles"]
        shared = set(picked[MARKET_ARM]) & set(picked["dixon_coles"])
        assert shared, "the arms must cover overlapping selections to be comparable"
        assert any(picked[MARKET_ARM][k] != picked["dixon_coles"][k] for k in shared), (
            "the arms returned identical probabilities: the filter is not applied"
        )

    def test_the_blend_moves_off_the_market_in_proportion_to_the_weight(self, blended_db):
        """Not an assertion about the finding — an assertion that the pool
        behaves. To first order the displacement from the market is w times the
        log-ratio between the two forecasts, which on 1X2 probabilities is
        bounded by a small constant. So a tiny w must give a tiny displacement,
        and doubling w must roughly double it.
        """
        con, steps = blended_db
        arms = build_arms(con, "deployable", "ENG_PL")[:30]
        small = min(s["weight"] for s in steps)
        assert small > 0

        def displacement(w):
            return max(abs(pool(a.model, a.market, w)[k] - a.market[k])
                       for a in arms for k in range(3))

        # Bounded, and bounded BY w: the constant is the log-ratio, not a
        # tolerance chosen to make the test pass.
        assert displacement(small) <= 5 * small
        # And it scales: half the weight, roughly half the move.
        assert displacement(small / 2) == pytest.approx(displacement(small) / 2, rel=0.2)
