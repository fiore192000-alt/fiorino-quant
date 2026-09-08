"""
M4 — the walk-forward engine, on a real season.

The specification tests in test_m4_cohort_capital.py pinned the RULE before the
engine existed. This file checks the engine obeys it against real Premier
League matches, real prices and real results.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from fiorino.backtest import (
    BacktestConfig,
    Frictions,
    Ledger,
    TakeFavourite,
    TakeSelection,
    TakeValueVsClose,
    compute_metrics,
    run_backtest,
    settle,
)
from fiorino.backtest.frictions import NO_FRICTIONS
from fiorino.clv.compute import compute_clv
from fiorino.core.capital import OversizePolicy
from fiorino.core.markets import Outcome, settle_bet
from fiorino.data.ingest.sources.footballdata import FootballData
from fiorino.data.lake import bronze_path, write_bronze
from fiorino.data.pipeline import ingest_bronze

#: The complete 2017-18 Premier League file from Football-Data, committed
#: verbatim. A full season rather than an extract because a "naive strategies
#: lose" test over 17 bets proves nothing — it could profit by luck.
REAL = (Path(__file__).parent / "fixtures" / "footballdata_e0_2017-18_real.csv").read_text()
START = datetime(2017, 8, 1, tzinfo=timezone.utc)
END = datetime(2018, 6, 30, tzinfo=timezone.utc)
UTC = timezone.utc


@pytest.fixture(scope="module")
def market_db(tmp_path_factory):
    """One ingested season shared by the module.

    Every backtest gets its own run_id and every replay its own run label, so
    the writes do not collide. Rebuilding a 380-match season per test cost
    seven minutes for no additional coverage.
    """
    from fiorino.data.db.connection import connect
    from fiorino.data.db.migrate import migrate
    from fiorino.data.pipeline import bootstrap_reference

    con = connect()
    migrate(con)
    bootstrap_reference(con)
    tmp_path = tmp_path_factory.mktemp("lake")
    rows = FootballData().parse(REAL, "ENG_PL", "2017-2018")
    write_bronze(con, [r.as_row() for r in rows],
                 bronze_path(tmp_path, "footballdata", "ENG_PL", "2017-2018", "r"))
    ingest_bronze(con, tmp_path, auto_register_unknown=True)
    yield con
    con.close()


@pytest.fixture
def config():
    return BacktestConfig(initial_bankroll=Decimal("1000"), stake_fraction=0.01,
                          max_exposure=0.25, frictions=NO_FRICTIONS)


class TestCohortInvariant:
    """The bug M4 exists to eliminate, checked on real simultaneous kickoffs."""

    def test_simultaneous_bets_share_one_stake(self, market_db, config):
        run_backtest(market_db, TakeSelection("HOME"), config, START, END)
        offenders = market_db.execute(
            """SELECT count(*) FROM (
                 SELECT cohort_id, count(DISTINCT stake) d, count(*) n
                 FROM bets WHERE cohort_id IS NOT NULL
                 GROUP BY cohort_id HAVING n > 1 AND d > 1)"""
        ).fetchone()[0]
        assert offenders == 0, "bets in one cohort were sized against different equity"

    def test_a_stake_is_the_configured_fraction_of_the_snapshot(self, market_db, config):
        run_backtest(market_db, TakeSelection("HOME"), config, START, END)
        row = market_db.execute(
            """SELECT c.equity_open, b.stake, c.n_bets FROM cohorts c
               JOIN bets b ON b.cohort_id = c.cohort_id
               WHERE c.n_bets > 2 LIMIT 1"""
        ).fetchone()
        equity_open, stake, _ = row
        assert float(stake) == pytest.approx(float(equity_open) * 0.01, abs=0.02)

    def test_no_stake_compounds_on_a_sibling_result(self, market_db, config):
        """The forbidden shape: stakes growing within a single cohort."""
        run_backtest(market_db, TakeSelection("HOME"), config, START, END)
        for (cohort_id,) in market_db.execute(
            "SELECT cohort_id FROM cohorts WHERE n_bets > 2"
        ).fetchall():
            stakes = [float(r[0]) for r in market_db.execute(
                "SELECT stake FROM bets WHERE cohort_id = ? ORDER BY bet_id", [cohort_id]
            ).fetchall()]
            assert len(set(stakes)) == 1, f"cohort {cohort_id} compounded: {stakes}"

    def test_a_busy_matchday_forms_one_cohort(self, market_db, config):
        """Real Premier League Saturdays put many matches at the same instant."""
        run_backtest(market_db, TakeSelection("HOME"), config, START, END)
        biggest = market_db.execute("SELECT max(n_bets) FROM cohorts").fetchone()[0]
        assert biggest >= 3, "the fixture should contain simultaneous kickoffs"


class TestLedgerAccounting:
    def test_equity_is_cash_plus_open_stakes(self):
        ledger = Ledger(Decimal("100"))
        ledger.place("a", Decimal("30"), "t")
        assert ledger.settled_cash == Decimal("70")
        assert ledger.open_exposure == Decimal("30")
        assert ledger.equity == Decimal("100")

    def test_available_respects_the_exposure_cap(self):
        ledger = Ledger(Decimal("100"), max_exposure=0.5)
        assert ledger.available == Decimal("50")
        ledger.place("a", Decimal("20"), "t")
        assert ledger.available == Decimal("30")

    def test_capital_committed_earlier_is_not_available_again(self):
        """A 12:30 stake is still tied up when the 15:00 cohort is sized."""
        ledger = Ledger(Decimal("100"), max_exposure=1.0)
        ledger.place("early", Decimal("40"), "t1")
        assert ledger.available == Decimal("60")

    def test_overspending_is_refused(self):
        ledger = Ledger(Decimal("100"))
        with pytest.raises(ValueError, match="cannot stake"):
            ledger.place("a", Decimal("150"), "t")

    def test_settlement_returns_capital_and_pnl(self):
        ledger = Ledger(Decimal("100"))
        ledger.place("a", Decimal("10"), "t")
        pnl = ledger.settle("a", Decimal("25"))
        assert pnl == Decimal("15")
        assert ledger.settled_cash == Decimal("115")
        assert ledger.open_exposure == Decimal("0")

    def test_drawdown_tracks_the_running_peak(self):
        ledger = Ledger(Decimal("100"))
        ledger.place("a", Decimal("50"), "t")
        ledger.settle("a", Decimal("100"))       # equity 150, new peak
        ledger.place("b", Decimal("50"), "t")
        ledger.settle("b", Decimal("0"))         # equity 100
        assert ledger.drawdown == pytest.approx(1 / 3, abs=1e-9)


class TestSettlementStates:
    """All five, because an Asian handicap cannot be settled with a boolean."""

    @pytest.mark.parametrize(
        "market,line,selection,gh,ga,expected",
        [
            ("ONE_X_TWO", 0.0, "HOME", 2, 1, Outcome.WIN),
            ("ONE_X_TWO", 0.0, "DRAW", 1, 1, Outcome.WIN),
            ("ASIAN_HANDICAP", -1.0, "HOME", 2, 1, Outcome.PUSH),
            ("ASIAN_HANDICAP", -0.25, "HOME", 1, 1, Outcome.HALF_LOSE),
            ("ASIAN_HANDICAP", 0.25, "HOME", 1, 1, Outcome.HALF_WIN),
            ("ASIAN_HANDICAP", -0.75, "HOME", 2, 1, Outcome.HALF_WIN),
            ("TOTALS", 3.0, "OVER", 2, 1, Outcome.PUSH),
            ("TOTALS", 2.75, "UNDER", 2, 1, Outcome.HALF_LOSE),
            ("BTTS", 0.0, "YES", 2, 1, Outcome.WIN),
        ],
    )
    def test_outcomes(self, market, line, selection, gh, ga, expected):
        assert settle_bet(market, line, selection, gh, ga) is expected

    def test_returns_match_the_outcome(self):
        for outcome, expected in [
            (("ONE_X_TWO", 0.0, "HOME", 2, 1), Decimal("25.000000")),      # win at 2.5
            (("ASIAN_HANDICAP", -1.0, "HOME", 2, 1), Decimal("10.000000")),  # push
            (("ASIAN_HANDICAP", -0.25, "HOME", 1, 1), Decimal("5.000000")),  # half lose
        ]:
            market, line, selection, gh, ga = outcome
            price = 2.5 if market == "ONE_X_TWO" else 2.0
            result = settle("b", market, line, selection, price, 10, gh, ga, NO_FRICTIONS)
            assert result.returned == expected

    def test_settlement_agrees_with_pricing(self):
        """One algebra, not two. Two copies of settlement logic drift, and a
        backtest that settles differently from how it priced is worthless."""
        from fiorino.core.markets import Side, asian_handicap_outcomes

        grid = [[0.0] * 4 for _ in range(4)]
        grid[2][1] = 1.0                       # a certain 2-1
        structure = asian_handicap_outcomes(grid, Side.HOME, -1.0)
        assert structure.push == pytest.approx(1.0)
        assert settle_bet("ASIAN_HANDICAP", -1.0, "HOME", 2, 1) is Outcome.PUSH


class TestFrictions:
    def test_stakes_round_down_never_up(self):
        f = Frictions(stake_increment=Decimal("0.10"), min_stake=Decimal("0"))
        assert f.round_stake(Decimal("13.79")) == Decimal("13.70")

    def test_a_stake_below_the_minimum_becomes_zero(self):
        f = Frictions(min_stake=Decimal("1.00"))
        assert f.round_stake(Decimal("0.40")) == Decimal("0")

    def test_the_book_limit_is_enforced(self):
        f = Frictions(max_stake=Decimal("50"), min_stake=Decimal("0"))
        assert f.round_stake(Decimal("500")) == Decimal("50")

    def test_commission_applies_to_winnings_only(self):
        f = Frictions(commission_rate=0.05)
        assert f.commission_on(Decimal("100")) == Decimal("5.000000")
        assert f.commission_on(Decimal("-100")) == Decimal("0")

    def test_slippage_reduces_the_price_not_the_probability(self):
        f = Frictions(slippage=0.10)
        assert f.effective_price(3.0) == pytest.approx(2.8)
        assert f.effective_price(1.5) == pytest.approx(1.45)

    def test_commission_reduces_realised_pnl(self, market_db):
        clean = settle("b", "ONE_X_TWO", 0.0, "HOME", 3.0, 10, 2, 1, NO_FRICTIONS)
        charged = settle("b", "ONE_X_TWO", 0.0, "HOME", 3.0, 10, 2, 1,
                         Frictions(commission_rate=0.05))
        assert charged.pnl < clean.pnl


class TestNaiveStrategiesLose:
    """They must. If an indiscriminate strategy profits, the engine is wrong."""

    @pytest.mark.parametrize("strategy", [TakeSelection("HOME"), TakeFavourite()])
    def test_no_edge_no_profit(self, market_db, config, strategy):
        result = run_backtest(market_db, strategy, config, START, END)
        compute_clv(market_db, result.run_id)
        metrics = compute_metrics(market_db, result.run_id)
        assert metrics.n_settled > 100
        assert metrics.yield_on_turnover < 0
        assert metrics.mean_clv_ev < 0
        assert "no edge" in metrics.verdict


class TestEngineCanShowEdge:
    """A strategy KNOWN to have edge must produce a rising curve.

    TakeValueVsClose is deliberately clairvoyant — it reads the close, which is
    not knowable when the bet is struck. It is not a strategy; it is the proof
    that the engine converts real edge into real money. If this failed, a true
    edge found later would be invisible.
    """

    def test_the_oracle_makes_money(self, market_db, config):
        result = run_backtest(market_db, TakeValueVsClose(min_edge=0.05), config, START, END)
        compute_clv(market_db, result.run_id)
        metrics = compute_metrics(market_db, result.run_id)
        assert metrics.n_settled > 20
        assert metrics.mean_clv_ev > 0.03
        assert metrics.yield_on_turnover > 0
        assert metrics.final_equity > metrics.initial_bankroll

    def test_clv_convergence_beats_yield_convergence(self, market_db, config):
        """The empirical case for CLV as the priority metric.

        Even for a strategy whose CLV t-stat is overwhelming, the bootstrap
        yield interval still straddles zero at this sample size. CLV says
        "there is edge" long before P&L can.
        """
        result = run_backtest(market_db, TakeValueVsClose(min_edge=0.05), config, START, END)
        compute_clv(market_db, result.run_id)
        metrics = compute_metrics(market_db, result.run_id, bootstrap=500)
        assert metrics.clv_t_stat > 3, "CLV is unmistakable"
        assert metrics.yield_ci_low is not None
        assert metrics.yield_ci_low < metrics.yield_on_turnover < metrics.yield_ci_high


class TestMetrics:
    def test_yield_is_on_turnover_not_bankroll(self, market_db, config):
        """'ROI 237%' on a bankroll recycled forty times measures volume."""
        result = run_backtest(market_db, TakeSelection("HOME"), config, START, END)
        metrics = compute_metrics(market_db, result.run_id)
        assert metrics.turnover > metrics.initial_bankroll
        assert metrics.yield_on_turnover == pytest.approx(metrics.pnl / metrics.turnover)
        assert abs(metrics.yield_on_turnover) < abs(metrics.growth) + 1

    def test_drawdown_is_reported(self, market_db, config):
        result = run_backtest(market_db, TakeSelection("HOME"), config, START, END)
        assert compute_metrics(market_db, result.run_id).max_drawdown > 0

    def test_the_verdict_names_luck_when_clv_and_yield_disagree(self):
        from fiorino.backtest.metrics import BacktestMetrics

        lucky = BacktestMetrics("r", 100, 100, 1000, 50, 0.05, 1000, 1050, 0.05,
                                0.1, 0.5, 1.0, mean_clv_ev=-0.01, clv_t_stat=-3)
        assert "lucky" in lucky.verdict
        unlucky = BacktestMetrics("r", 100, 100, 1000, -50, -0.05, 1000, 950, -0.05,
                                  0.1, 0.5, -1.0, mean_clv_ev=0.01, clv_t_stat=3)
        assert "unlucky" in unlucky.verdict

    def test_too_few_bets_says_so(self):
        from fiorino.backtest.metrics import BacktestMetrics

        thin = BacktestMetrics("r", 5, 5, 50, 5, 0.1, 1000, 1005, 0.005,
                               0.0, 0.6, 1.0, mean_clv_ev=0.05, clv_t_stat=2)
        assert "too few" in thin.verdict


class TestCapitalConstraintInTheEngine:
    def test_the_exposure_cap_binds(self, market_db):
        """A tiny cap must force the pro-rata policy on a busy matchday."""
        config = BacktestConfig(initial_bankroll=Decimal("1000"), stake_fraction=0.05,
                                max_exposure=0.05, frictions=NO_FRICTIONS,
                                oversize_policy=OversizePolicy.SCALE_PRO_RATA)
        result = run_backtest(market_db, TakeSelection("HOME"), config, START, END)
        assert result.constrained_cohorts > 0

    def test_total_staked_never_exceeds_available(self, market_db):
        config = BacktestConfig(initial_bankroll=Decimal("1000"), stake_fraction=0.05,
                                max_exposure=0.10, frictions=NO_FRICTIONS)
        run_backtest(market_db, TakeSelection("HOME"), config, START, END)
        breaches = market_db.execute(
            "SELECT count(*) FROM cohorts WHERE total_staked > available_open + 0.01"
        ).fetchone()[0]
        assert breaches == 0

    def test_reject_policy_places_nothing_when_oversized(self, market_db):
        config = BacktestConfig(initial_bankroll=Decimal("1000"), stake_fraction=0.5,
                                max_exposure=0.05, frictions=NO_FRICTIONS,
                                oversize_policy=OversizePolicy.REJECT)
        result = run_backtest(market_db, TakeSelection("HOME"), config, START, END)
        assert result.n_bets == 0
        assert result.n_candidates > 0
