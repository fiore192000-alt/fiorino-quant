"""
The research opportunity list, and the falsification it exists to prevent.

A fixture with no price is not a fixture with no edge. Collapsing those two
into one status would let a missing price read as a measured absence of
advantage — the system would be claiming to have looked. Most of this file
asserts that they stay apart, in the view, in the score and in the decision.
"""

from datetime import datetime, timedelta, timezone

import pytest

from fiorino.data.db.connection import connect
from fiorino.data.db.migrate import migrate
from fiorino.decision import SignalLevel, classify, score_signal

UTC = timezone.utc


@pytest.fixture
def db():
    con = connect()
    migrate(con)
    con.execute("INSERT INTO competitions VALUES ('ENG_PL', 'Premier League', 'ENG', 1, FALSE)")
    con.execute("INSERT INTO seasons VALUES ('2026-2027', DATE '2026-08-01', DATE '2027-05-31')")
    con.execute("INSERT INTO teams (team_id, canonical_name, country, created_at) "
                "VALUES ('h', 'Home FC', 'ENG', now()), ('a', 'Away FC', 'ENG', now())")
    con.execute("INSERT INTO bookmakers VALUES ('bk', 'Book', 'SHARP', TRUE, 0, NULL, 'ENG', NULL)")
    yield con
    con.close()


def _fixture(con, match_id, kickoff, *, played=False):
    con.execute(
        """INSERT INTO matches (match_id, competition_id, season_id, match_date_utc,
                                kickoff_utc, home_team_id, away_team_id, status, ingested_at)
           VALUES (?, 'ENG_PL', '2026-2027', ?, ?, 'h', 'a', 'SCHEDULED', now())""",
        [match_id, kickoff.date(), kickoff])
    if played:
        con.execute(
            """INSERT INTO match_results (match_id, goals_home, goals_away, settled_at,
                                          source, ingested_at)
               VALUES (?, 1, 0, ?, 'test', now())""",
            [match_id, kickoff + timedelta(hours=2)])


def _price(con, match_id):
    con.execute(
        """INSERT INTO odds_observations
           (observation_id, match_id, bookmaker_id, market_type, line, selection,
            price_decimal, capture_precision, captured_at, source, ingested_at)
           VALUES (?, ?, 'bk', 'ONE_X_TWO', 0.0, 'HOME', 2.5, 'PREMATCH', NULL,
                   'test', now())""",
        [f"o_{match_id}", match_id])


def _row(con, match_id):
    return con.execute(
        "SELECT * FROM v_research_opportunities WHERE match_id = ?", [match_id]
    ).df().iloc[0]


class TestTheStatesAreIndependent:
    def test_an_upcoming_fixture_with_no_price_is_a_data_gap_not_a_verdict(self, db):
        _fixture(db, "m1", datetime.now(UTC) + timedelta(days=3))
        row = _row(db, "m1")
        assert row["fixture_status"] == "UPCOMING"
        assert row["odds_status"] == "DATA_GAP"
        assert row["decision_status"] == "DATA_GAP"

    def test_a_finished_fixture_is_finished_regardless_of_prices(self, db):
        _fixture(db, "m2", datetime.now(UTC) - timedelta(days=3), played=True)
        assert _row(db, "m2")["fixture_status"] == "FINISHED"

    def test_odds_availability_and_instant_quality_are_separate(self, db):
        """A price with no instant is available and still cannot support any
        statement about WHEN the market knew something."""
        _fixture(db, "m3", datetime.now(UTC) + timedelta(days=1))
        _price(db, "m3")
        row = _row(db, "m3")
        assert row["odds_status"] == "AVAILABLE"
        assert row["odds_timestamp_quality"] == "UNKNOWN_INSTANT"

    def test_a_missing_lineup_before_kickoff_is_not_yet_available(self, db):
        """Before the match it is simply too early — that is not the same as
        a gap that will never be filled."""
        _fixture(db, "m4", datetime.now(UTC) + timedelta(days=2))
        assert _row(db, "m4")["lineup_status"] == "NOT_YET_AVAILABLE"

    def test_a_missing_lineup_after_kickoff_is_a_gap(self, db):
        _fixture(db, "m5", datetime.now(UTC) - timedelta(days=2), played=True)
        assert _row(db, "m5")["lineup_status"] == "DATA_GAP"

    def test_a_price_without_a_model_is_still_not_evaluable(self, db):
        _fixture(db, "m6", datetime.now(UTC) + timedelta(days=1))
        _price(db, "m6")
        assert _row(db, "m6")["decision_status"] == "DATA_GAP"


class TestNoOddsIsNeverScoredAsZero:
    def test_the_score_is_none_not_zero(self):
        """Zero says 'assessed and found worthless'. None says 'could not
        assess'. Rendering the second as the first is a falsification."""
        score = score_signal()
        assert score.value is None
        assert score.value != 0.0
        assert score.data_gap == "NO_ODDS"
        assert not score.scorable

    def test_a_real_but_tiny_edge_does_score_zero_ish(self):
        """The contrast: with a price, a worthless opportunity IS scored."""
        score = score_signal(edge=0.0001)
        assert score.scorable
        assert score.value is not None
        assert score.value < 0.05

    def test_an_unscorable_signal_explains_nothing_rather_than_inventing(self):
        assert score_signal().explain() == []

    def test_the_decision_is_data_gap_not_no_signal(self):
        decision = classify(edge=None)
        assert decision.level == SignalLevel.DATA_GAP
        assert decision.level != SignalLevel.NO_SIGNAL
        assert "NO_ODDS" in {r.code for r in decision.reasons}

    def test_data_gap_is_not_on_the_ladder(self):
        """Putting it at the bottom of the same scale would make 'could not
        evaluate' a weaker version of 'evaluated and found nothing'."""
        from fiorino.decision import LEVELS

        assert SignalLevel.DATA_GAP not in LEVELS


class TestReadiness:
    def test_readiness_counts_gaps_separately_from_verdicts(self, db):
        for i in range(3):
            _fixture(db, f"u{i}", datetime.now(UTC) + timedelta(days=i + 1))
        _price(db, "u0")
        rows = db.execute(
            "SELECT * FROM v_data_readiness WHERE fixture_status = 'UPCOMING'").df()
        assert int(rows["n_matches"].iloc[0]) == 3
        assert int(rows["n_with_odds"].iloc[0]) == 1
        assert int(rows["n_timestamped"].iloc[0]) == 0
        assert int(rows["n_data_gap"].iloc[0]) == 3

    def test_nothing_is_evaluable_without_timestamped_odds_and_a_model(self, db):
        _fixture(db, "z", datetime.now(UTC) + timedelta(days=1))
        _price(db, "z")
        assert int(db.execute(
            "SELECT n_evaluable FROM v_data_readiness").df()["n_evaluable"].iloc[0]) == 0


class TestOpenFootballCarriesFutureFixtures:
    def test_a_fixture_with_no_score_parses(self):
        """Future fixtures have no score. Dropping them would leave the
        terminal with nothing upcoming to show."""
        from fiorino.data.ingest.sources.openfootball import OpenFootball

        payload = {"matches": [
            {"date": "2027-05-01", "time": "15:00",
             "team1": "Home FC", "team2": "Away FC"},
            {"date": "2026-08-16", "time": "20:00", "team1": "A", "team2": "B",
             "score": {"ft": [1, 0]}},
        ]}
        rows = OpenFootball().parse(payload, "ENG_PL", "2026-2027")
        assert len(rows) == 2
        upcoming = [r for r in rows if r.goals_home is None]
        assert len(upcoming) == 1
        assert upcoming[0].kickoff_utc.startswith("2027-05-01")

    def test_the_season_path_matches_openfootball_layout(self):
        from fiorino.data.ingest.sources.openfootball import to_openfootball_season

        assert to_openfootball_season("2026-2027") == "2026-27"
