"""
M3 — CLV against the real reference closing line.

The pure formulas are covered in test_m3_clv.py. This file tests the wiring:
scoring real bets against a real de-vigged Pinnacle close, and refusing to
score when the comparison is not available.
"""

from pathlib import Path

import pytest

from fiorino.clv.compute import compute_clv, record_bet
from fiorino.clv.replay import take_closing, take_prematch, take_selection
from fiorino.data.ingest.sources.footballdata import FootballData
from fiorino.data.lake import bronze_path, write_bronze
from fiorino.data.pipeline import ingest_bronze
from fiorino.odds.ingest import compute_fair_probabilities

REAL = (Path(__file__).parent / "fixtures" / "footballdata_e0_2017-18_real.csv").read_text()


def _build(con, tmp_path, method=None):
    rows = FootballData().parse(REAL, "ENG_PL", "2017-2018")
    write_bronze(con, [r.as_row() for r in rows],
                 bronze_path(tmp_path, "footballdata", "ENG_PL", "2017-2018", "real"))
    ingest_bronze(con, tmp_path, auto_register_unknown=True)
    if method:
        compute_fair_probabilities(con, method)
        con.execute("DELETE FROM fair_probabilities WHERE devig_method <> ?", [method])
    return con


@pytest.fixture
def market_db(seeded_db, tmp_path):
    return _build(seeded_db, tmp_path)


class TestCalibrationIdentity:
    """The analytical check that proves the machinery, not just exercises it.

    Take the closing price ITSELF. Under multiplicative de-vigging the fair
    probability is (1/price)/S, so fair * price = 1/S for every selection and

        CLV_ev  ==  1/(1 + overround) - 1  ==  -overround / (1 + overround)

    a number known in advance. If this drifts, something in the chain —
    de-vig, closing materialisation, or the CLV arithmetic — is wrong.
    """

    def test_multiplicative_devig_reproduces_the_closed_form(self, seeded_db, tmp_path):
        con = _build(seeded_db, tmp_path, "MULTIPLICATIVE")
        take_closing(con)
        compute_clv(con, "replay_closing")
        mean_clv, = con.execute(
            "SELECT avg(clv_ev) FROM v_bet_clv WHERE run_id='replay_closing' AND line_matched"
        ).fetchone()
        overround, = con.execute("SELECT avg(closing_overround) FROM reference_market").fetchone()
        assert mean_clv == pytest.approx(-overround / (1 + overround), abs=1e-4)

    def test_shin_deviates_from_it_by_design(self, seeded_db, tmp_path):
        """Shin redistributes, so fair * price is deliberately NOT constant.

        The deviation is not an error and not noise: it is ~80 bps, larger
        than most claimed edges, which is why the de-vig method is recorded
        per row rather than assumed.
        """
        con = _build(seeded_db, tmp_path, "SHIN")
        take_closing(con)
        compute_clv(con, "replay_closing")
        mean_clv, = con.execute(
            "SELECT avg(clv_ev) FROM v_bet_clv WHERE run_id='replay_closing' AND line_matched"
        ).fetchone()
        overround, = con.execute("SELECT avg(closing_overround) FROM reference_market").fetchone()
        assert abs(mean_clv - (-overround / (1 + overround))) > 1e-3

    def test_shin_keeps_more_value_on_the_favourite(self, seeded_db, tmp_path):
        con = _build(seeded_db, tmp_path, "SHIN")
        take_closing(con)
        compute_clv(con, "replay_closing")
        by_selection = dict(con.execute(
            """SELECT selection, avg(closing_fair_prob * price_taken) FROM v_bet_clv
               WHERE run_id='replay_closing' AND line_matched GROUP BY 1"""
        ).fetchall())
        assert by_selection["HOME"] > by_selection["DRAW"] > by_selection["AWAY"]

    def test_taking_the_close_yields_exactly_zero_price_clv(self, market_db):
        take_closing(market_db)
        compute_clv(market_db, "replay_closing")
        mean_price_clv, = market_db.execute(
            "SELECT avg(clv_price) FROM v_bet_clv WHERE run_id='replay_closing' AND line_matched"
        ).fetchone()
        assert mean_price_clv == pytest.approx(0.0, abs=1e-12)


class TestPrematchBaseline:
    """What every future model must beat.

    Thresholds are set for the committed 17-match fixture (51 bets). On the
    full 2017-18 season the same measurements are far sharper — 918 bets,
    mean CLV_ev -0.028, t = -10.66 — but the fixture keeps the suite offline
    and fast, so the assertions state only what 51 bets can support.
    """

    def test_an_indiscriminate_prematch_taker_loses_the_margin(self, market_db):
        take_prematch(market_db)
        compute_clv(market_db, "replay_prematch")
        row = market_db.execute(
            "SELECT n_bets, mean_clv_ev, clv_t_stat FROM v_clv_summary WHERE run_id='replay_prematch'"
        ).fetchone()
        assert row[0] > 40
        assert row[1] < 0, "betting everything indiscriminately cannot beat the close"
        assert row[2] < -1.5, "and the loss is already visible at this sample size"

    def test_price_drift_is_near_zero_on_average(self, market_db):
        """Pure price CLV nets out: the market is not systematically generous."""
        take_prematch(market_db)
        compute_clv(market_db, "replay_prematch")
        mean_price_clv, = market_db.execute(
            "SELECT avg(clv_price) FROM v_bet_clv WHERE run_id='replay_prematch' AND line_matched"
        ).fetchone()
        assert abs(mean_price_clv) < 0.02

    def test_home_and_away_prices_drift_in_opposite_directions(self, market_db):
        """A real market effect: home prices shorten, away prices lengthen."""
        take_prematch(market_db)
        compute_clv(market_db, "replay_prematch")
        by_selection = dict(market_db.execute(
            """SELECT selection, avg(clv_price) FROM v_bet_clv
               WHERE run_id='replay_prematch' AND line_matched GROUP BY 1"""
        ).fetchall())
        assert by_selection["HOME"] < 0 < by_selection["AWAY"]

    def test_beat_close_rate_is_near_a_coin_flip(self, market_db):
        take_prematch(market_db)
        compute_clv(market_db, "replay_prematch")
        rate, = market_db.execute(
            "SELECT beat_close_rate FROM v_clv_summary WHERE run_id='replay_prematch'"
        ).fetchone()
        assert 0.35 < rate < 0.65

    def test_a_single_selection_can_be_replayed(self, market_db):
        n = take_selection(market_db, "HOME")
        assert n > 0
        compute_clv(market_db, "replay_home")
        rows, = market_db.execute(
            "SELECT count(*) FROM v_bet_clv WHERE run_id='replay_home' AND selection <> 'HOME'"
        ).fetchone()
        assert rows == 0


class TestExclusions:
    """Refusing to answer is part of answering honestly."""

    def test_a_market_the_reference_never_priced_is_excluded(self, market_db):
        match_id, = market_db.execute("SELECT match_id FROM matches LIMIT 1").fetchone()
        record_bet(market_db, run_id="probe", match_id=match_id, bookmaker_id="bet365",
                   market_type="TOTALS", line=2.5, selection="OVER",
                   price_taken=1.95, price_precision="PREMATCH")
        result = compute_clv(market_db, "probe")
        assert result.scored == 0 and result.excluded == 1
        reason, = market_db.execute(
            "SELECT exclusion_reason FROM v_bet_clv WHERE run_id='probe'"
        ).fetchone()
        assert reason == "line_not_matched"

    def test_excluded_bets_are_kept_out_of_the_statistics(self, market_db):
        match_id, = market_db.execute("SELECT match_id FROM matches LIMIT 1").fetchone()
        record_bet(market_db, run_id="probe", match_id=match_id, bookmaker_id="bet365",
                   market_type="TOTALS", line=2.5, selection="OVER",
                   price_taken=1.95, price_precision="PREMATCH")
        compute_clv(market_db, "probe")
        assert market_db.execute(
            "SELECT count(*) FROM v_clv_summary WHERE run_id='probe'"
        ).fetchone()[0] == 0

    def test_coverage_reports_what_could_be_scored(self, market_db):
        take_prematch(market_db)
        compute_clv(market_db, "replay_prematch")
        row = market_db.execute(
            "SELECT n_bets, n_scored, scored_fraction FROM v_clv_coverage "
            "WHERE run_id='replay_prematch'"
        ).fetchone()
        assert row[0] == row[1] and row[2] == pytest.approx(1.0)


class TestBetLedgerHonesty:
    """The M2 timestamp rule, carried into the bet ledger."""

    def test_a_prematch_bet_cannot_claim_an_instant(self, market_db):
        match_id, = market_db.execute("SELECT match_id FROM matches LIMIT 1").fetchone()
        from datetime import datetime, timezone

        with pytest.raises(ValueError, match="no known instant"):
            record_bet(market_db, run_id="bad", match_id=match_id, bookmaker_id="pinnacle",
                       market_type="ONE_X_TWO", line=0.0, selection="HOME",
                       price_taken=2.0, price_precision="PREMATCH",
                       placed_at=datetime.now(timezone.utc))

    def test_a_timestamped_bet_requires_an_instant(self, market_db):
        match_id, = market_db.execute("SELECT match_id FROM matches LIMIT 1").fetchone()
        with pytest.raises(ValueError, match="TIMESTAMPED"):
            record_bet(market_db, run_id="bad", match_id=match_id, bookmaker_id="pinnacle",
                       market_type="ONE_X_TWO", line=0.0, selection="HOME",
                       price_taken=2.0, price_precision="TIMESTAMPED")

    def test_no_replayed_bet_carries_a_fabricated_clock(self, market_db):
        take_prematch(market_db)
        n, = market_db.execute(
            "SELECT count(*) FROM bets WHERE placed_at IS NOT NULL"
        ).fetchone()
        assert n == 0

    def test_recording_is_idempotent(self, market_db):
        first = take_prematch(market_db)
        before, = market_db.execute("SELECT count(*) FROM bets").fetchone()
        take_prematch(market_db)
        after, = market_db.execute("SELECT count(*) FROM bets").fetchone()
        assert before == after == first


class TestReferenceIsTheSharpBook:
    def test_clv_is_measured_against_pinnacle_not_the_struck_book(self, market_db):
        take_prematch(market_db)
        compute_clv(market_db, "replay_prematch")
        books = market_db.execute(
            "SELECT DISTINCT ref_bookmaker_id FROM bet_clv"
        ).fetchall()
        assert books == [("pinnacle",)]
