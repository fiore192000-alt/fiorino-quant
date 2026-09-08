"""
M5 — model adapter, pricing and the walk-forward fit.

The headline finding is negative and it is the point: a Dixon-Coles model does
not beat the Pinnacle close, and the infrastructure says so plainly instead of
letting the model's own confidence stand in for evidence.
"""

import datetime as dt
from datetime import timedelta
from pathlib import Path

import pytest

from fiorino.core.markets import Outcome
from fiorino.data.ingest.sources.footballdata import FootballData
from fiorino.data.lake import bronze_path, write_bronze
from fiorino.data.pipeline import ingest_bronze
from fiorino.models.adapters.penaltyblog import MODELS, PenaltyblogModel
from fiorino.pricing.grid import MAX_GOALS, score_grid
from fiorino.pricing.markets import DEFAULT_HANDICAPS, price_grid

REAL = (Path(__file__).parent / "fixtures" / "footballdata_e0_2017-18_real.csv").read_text()


@pytest.fixture(scope="module")
def synthetic_matches():
    import numpy as np

    rng = np.random.default_rng(7)
    teams = [f"t{i}" for i in range(12)]
    base = dt.date(2024, 1, 1)
    matches = []
    for i in range(320):
        home, away = rng.choice(teams, 2, replace=False)
        matches.append({
            "home_team_id": home, "away_team_id": away,
            "goals_home": int(rng.poisson(1.6)), "goals_away": int(rng.poisson(1.1)),
            "match_date_utc": base + dt.timedelta(days=i // 3),
        })
    return matches


@pytest.fixture(scope="module")
def fitted(synthetic_matches):
    model = PenaltyblogModel("dixon_coles", half_life_days=180)
    model.fit(synthetic_matches)
    return model


class TestAdapter:
    def test_every_declared_model_fits(self, synthetic_matches):
        for name in MODELS:
            model = PenaltyblogModel(name, half_life_days=None)
            result = model.fit(synthetic_matches)
            assert result.n_teams == 12
            assert model.expected_goals("t0", "t1").home > 0

    def test_an_unknown_model_is_refused(self):
        with pytest.raises(ValueError, match="unknown model"):
            PenaltyblogModel("crystal_ball")

    def test_a_tiny_sample_is_refused(self, synthetic_matches):
        with pytest.raises(ValueError, match="noise wearing a model"):
            PenaltyblogModel().fit(synthetic_matches[:10])

    def test_time_decay_weights_recent_matches_more(self, synthetic_matches):
        decayed = PenaltyblogModel("dixon_coles", half_life_days=30)
        flat = PenaltyblogModel("dixon_coles", half_life_days=None)
        decayed.fit(synthetic_matches)
        flat.fit(synthetic_matches)
        assert decayed.expected_goals("t0", "t1") != flat.expected_goals("t0", "t1")

    def test_strengths_are_keyed_by_team_not_by_offset(self, fitted):
        strengths = fitted.team_strengths()
        assert set(strengths) == fitted.teams
        assert all({"attack", "defence"} == set(v) for v in strengths.values())


class TestUnseenTeams:
    """penaltyblog raises for an unseen team; in a walk-forward that is every
    promoted side in August. Deleting them would delete the hardest fixtures."""

    def test_a_promoted_side_is_priced_from_a_prior(self, fitted):
        pair = fitted.expected_goals("PROMOTED_FC", "t1")
        assert pair.used_prior
        assert 0.2 < pair.home < 5.0 and 0.2 < pair.away < 5.0

    def test_the_prior_flag_travels_with_the_prediction(self, fitted):
        assert not fitted.expected_goals("t0", "t1").used_prior
        assert fitted.expected_goals("t0", "UNSEEN").used_prior
        assert fitted.expected_goals("UNSEEN_A", "UNSEEN_B").used_prior

    def test_a_known_side_keeps_its_own_strength_against_an_unseen_one(self, fitted):
        strengths = fitted.team_strengths()
        best = max(strengths, key=lambda t: strengths[t]["attack"])
        worst = min(strengths, key=lambda t: strengths[t]["attack"])
        assert (fitted.expected_goals(best, "UNSEEN").home
                > fitted.expected_goals(worst, "UNSEEN").home)


class TestLibraryBugIsShielded:
    """The adapter exists partly to absorb a real defect in the dependency."""

    def test_lambdas_can_be_derived_without_the_library_grid(self, fitted):
        """penaltyblog bounds rho to (-2.5, 2.5), but the range that keeps the
        Dixon-Coles grid a distribution depends on the lambdas, so a fitted rho
        can drive a cell negative and `predict()` raises. Only the lambdas are
        needed; the grid is built here with rho clamped."""
        import numpy as np

        model = fitted._model
        indices = model.param_indices()
        params = model.params_array
        n = model.n_teams
        position = {t: i for i, t in enumerate(model.teams)}
        hfa = float(params[indices["home_advantage"]])
        h, a = position["t0"], position["t1"]
        derived = (float(np.exp(params[h] + params[n + a] + hfa)),
                   float(np.exp(params[a] + params[n + h])))
        library = fitted.expected_goals("t0", "t1")
        assert derived[0] == pytest.approx(library.home, rel=1e-6)
        assert derived[1] == pytest.approx(library.away, rel=1e-6)

    def test_the_fitted_rho_is_exposed(self, fitted):
        assert isinstance(fitted.fitted_rho, float)

    def test_a_model_without_rho_reports_zero(self, synthetic_matches):
        model = PenaltyblogModel("poisson", half_life_days=None)
        model.fit(synthetic_matches)
        assert model.fitted_rho == 0.0


class TestGrid:
    def test_the_grid_covers_zero_to_max_goals_inclusive(self):
        grid = score_grid(1.5, 1.1)
        assert len(grid) == len(grid[0]) == MAX_GOALS + 1

    def test_the_grid_is_a_distribution(self):
        assert sum(sum(row) for row in score_grid(1.6, 1.2, rho=-0.05)) == pytest.approx(1.0)

    def test_an_out_of_range_rho_is_clamped_not_propagated(self):
        """The bug that kills the library: an unclamped rho makes a cell
        negative and the grid stops being a distribution."""
        grid = score_grid(1.5, 1.1, rho=5.0)
        assert sum(sum(row) for row in grid) == pytest.approx(1.0)
        assert all(cell >= 0 for row in grid for cell in row)

    def test_non_positive_lambdas_are_refused(self):
        with pytest.raises(ValueError, match="must be positive"):
            score_grid(0.0, 1.1)

    def test_rho_shifts_low_scores(self):
        plain = score_grid(1.5, 1.1, rho=0.0)
        adjusted = score_grid(1.5, 1.1, rho=-0.1)
        assert plain[0][0] != adjusted[0][0]


class TestMultiMarketPricing:
    def test_all_markets_come_from_one_grid(self):
        priced = price_grid(score_grid(1.6, 1.1))
        kinds = {p.market_type for p in priced}
        assert kinds == {"ONE_X_TWO", "ASIAN_HANDICAP", "TOTALS", "BTTS"}

    def test_one_x_two_sums_to_one(self):
        priced = price_grid(score_grid(1.6, 1.1))
        total = sum(p.outcome.win for p in priced if p.market_type == "ONE_X_TWO")
        assert total == pytest.approx(1.0)

    def test_integer_handicaps_carry_push_mass(self):
        priced = price_grid(score_grid(1.6, 1.1))
        integer = [p for p in priced
                   if p.market_type == "ASIAN_HANDICAP" and p.line == -1.0]
        assert all(p.outcome.push > 0 for p in integer)

    def test_quarter_handicaps_carry_half_states(self):
        priced = price_grid(score_grid(1.6, 1.1))
        quarter = [p for p in priced
                   if p.market_type == "ASIAN_HANDICAP" and p.line == -0.25]
        assert quarter
        for p in quarter:
            assert p.outcome.push == 0.0
            assert p.outcome.half_win > 0 or p.outcome.half_lose > 0

    def test_half_lines_are_two_state(self):
        priced = price_grid(score_grid(1.6, 1.1))
        for p in priced:
            if p.market_type == "ASIAN_HANDICAP" and p.line == -0.5:
                assert not p.outcome.has_push_risk

    def test_the_two_sides_of_a_handicap_are_complementary(self):
        grid = score_grid(1.6, 1.1)
        priced = {(p.line, p.selection): p.outcome
                  for p in price_grid(grid) if p.market_type == "ASIAN_HANDICAP"}
        for line in DEFAULT_HANDICAPS:
            home, away = priced[(line, "HOME")], priced[(line, "AWAY")]
            assert home.win == pytest.approx(away.lose)
            assert home.push == pytest.approx(away.push)

    def test_every_structure_is_a_valid_distribution(self):
        for p in price_grid(score_grid(1.4, 1.3)):
            assert sum(p.outcome.as_dict().values()) == pytest.approx(1.0)

    def test_markets_agree_with_each_other(self):
        """Coherence by construction: 1X2 home and AH -0.5 home are the same
        bet, so one grid cannot price them differently."""
        priced = {(p.market_type, p.line, p.selection): p.outcome
                  for p in price_grid(score_grid(1.6, 1.1))}
        assert (priced[("ONE_X_TWO", 0.0, "HOME")].win
                == pytest.approx(priced[("ASIAN_HANDICAP", -0.5, "HOME")].win))


@pytest.fixture(scope="module")
def priced_db(tmp_path_factory):
    """A real season ingested, fitted walk-forward and priced."""
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
    walk_forward(con, model_name="dixon_coles", competition_id="ENG_PL",
                 season_id="2017-2018", step=timedelta(days=7))
    yield con
    con.close()


class TestWalkForward:
    def test_the_training_set_grows(self, priced_db):
        sizes = [r[0] for r in priced_db.execute(
            "SELECT n_matches FROM model_runs ORDER BY trained_through"
        ).fetchall()]
        assert sizes == sorted(sizes)
        assert sizes[-1] > sizes[0]

    def test_no_fit_trained_on_the_future(self, priced_db):
        """The invariant the whole point-in-time layer exists for."""
        leaks = priced_db.execute(
            """SELECT count(*) FROM model_runs r
               JOIN predictions p ON p.model_run_id = r.model_run_id
               JOIN v_analytic_matches m ON m.match_id = p.match_id
               JOIN match_results res ON res.match_id = m.match_id
               WHERE res.settled_at <= r.trained_through
                 AND m.kickoff_utc > r.trained_through"""
        ).fetchone()[0]
        assert leaks == 0

    def test_predictions_precede_their_kickoffs(self, priced_db):
        late = priced_db.execute(
            """SELECT count(*) FROM predictions p
               JOIN v_analytic_matches m ON m.match_id = p.match_id
               WHERE p.as_of > m.kickoff_utc"""
        ).fetchone()[0]
        assert late == 0

    def test_predictions_join_to_odds_without_translation(self, priced_db):
        joined = priced_db.execute(
            "SELECT count(*) FROM v_model_vs_market WHERE market_type = 'ONE_X_TWO'"
        ).fetchone()[0]
        assert joined > 0


class TestModelVersusMarket:
    """The finding M5 exists to establish."""

    def test_the_market_beats_the_model(self, priced_db):
        """A Dixon-Coles fit does not beat a de-vigged Pinnacle close. Stating
        it as a test means a future change that claims otherwise has to explain
        itself."""
        row = priced_db.execute(
            """SELECT sum(model_brier * n) / sum(n), sum(market_brier * n) / sum(n)
               FROM v_model_calibration"""
        ).fetchone()
        model_brier, market_brier = row
        assert market_brier < model_brier, (
            "the model beat the close — verify this is real before believing it"
        )

    def test_the_model_still_reports_many_apparent_edges(self, priced_db):
        """A model that is WORSE than the market still finds 'value' on a third
        of selections. Those are model errors, not edges — which is the entire
        reason CLV, not the model's own confidence, decides."""
        total, edged = priced_db.execute(
            """SELECT count(*), count(*) FILTER (WHERE edge_ev > 0.05)
               FROM v_model_vs_market WHERE capture_precision = 'PREMATCH'"""
        ).fetchone()
        assert total > 0
        assert edged / total > 0.10
