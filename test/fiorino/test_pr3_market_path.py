"""
PR #3 — the timestamped market layer.

Built before its data, on purpose: the dump's schema is documented and stable,
so the transformation and its guards can exist now and the ingest becomes one
command later.

WHAT THESE TESTS ARE AND ARE NOT
--------------------------------
They exercise a TRANSFORMATION with constructed inputs. They do not pretend to
be observations: nothing here is presented as a real price, nothing enters the
analytic dataset, and no test asserts anything about how a market behaved.

The distinction matters because it is the one the adapter itself enforces — a
row without an instant is refused rather than defaulted — and a test suite that
quietly supplied instants would be undoing the guard it is meant to check.
"""

from datetime import datetime, timedelta, timezone

import pytest

from fiorino.data.db.connection import connect
from fiorino.data.db.migrate import migrate
from fiorino.data.ingest.sources.beatthebookie import (
    BOOKMAKERS,
    RESULT_TO_SELECTION,
    BeatTheBookie,
    MissingInstant,
)

UTC = timezone.utc
KICKOFF = datetime(2016, 3, 5, 20, 0, tzinfo=UTC)


def _row(**over):
    base = {"ID": 879672, "result": 1, "odds": "2.35",
            "odds_datetime": "2016-03-05 14:03:11",
            "bookmaker": "Pinnacle Sports", "disabled_date": None}
    base.update(over)
    return base


class TestTheAdapterRefusesToInventAnInstant:
    def test_a_row_without_a_datetime_is_refused(self):
        """Defaulting here would reintroduce exactly what choosing the dump
        over the hourly export was meant to avoid."""
        with pytest.raises(MissingInstant):
            BeatTheBookie().parse([_row(odds_datetime=None)])

    def test_an_empty_datetime_is_refused(self):
        with pytest.raises(MissingInstant):
            BeatTheBookie().parse([_row(odds_datetime="")])

    def test_an_unparseable_datetime_is_refused_not_guessed(self):
        with pytest.raises(MissingInstant):
            BeatTheBookie().parse([_row(odds_datetime="last tuesday")])

    def test_a_naive_instant_is_read_as_utc_and_says_so(self):
        """The export script sets the timezone to UTC. Attaching the wrong zone
        to a real instant is worse than having none: it looks correct."""
        parsed = BeatTheBookie().parse([_row()])[0]
        assert parsed.captured_at.tzinfo is not None
        assert parsed.captured_at == datetime(2016, 3, 5, 14, 3, 11, tzinfo=UTC)

    def test_every_emitted_row_is_timestamped_and_nothing_else(self):
        row = BeatTheBookie().parse([_row()])[0].as_row()
        assert row["capture_precision"] == "TIMESTAMPED"
        assert row["captured_at"] is not None


class TestTheAdapterMatchesTheVerifiedSchema:
    def test_result_codes_map_as_the_export_script_does(self):
        assert RESULT_TO_SELECTION == {1: "HOME", 2: "DRAW", 3: "AWAY"}

    def test_the_bookmaker_travels_by_name(self):
        """The whole reason to prefer the dump: the .txt export reduces the
        book to a row index."""
        parsed = BeatTheBookie().parse([_row(bookmaker="bet365")])[0]
        assert parsed.bookmaker_raw == "bet365"

    def test_the_dataset_declares_thirty_two_books(self):
        assert len(BOOKMAKERS) == 32
        assert "Pinnacle Sports" in BOOKMAKERS and "bet365" in BOOKMAKERS

    def test_other_bet_types_are_skipped_not_coerced(self):
        assert BeatTheBookie().parse([_row(result=7)]) == []

    def test_a_price_at_or_below_evens_is_dropped(self):
        """Below 1.0 a decimal price returns less than the stake: a parsing
        artefact, not an offer."""
        assert BeatTheBookie().parse([_row(odds="0.90")]) == []

    def test_a_withdrawn_market_keeps_its_disabled_instant(self):
        """A price that was pulled is a different fact from one that merely
        stopped changing."""
        parsed = BeatTheBookie().parse(
            [_row(disabled_date="2016-03-05 19:45:00")])[0]
        assert parsed.disabled_at == datetime(2016, 3, 5, 19, 45, tzinfo=UTC)

    def test_the_query_is_kept_beside_the_parser(self):
        """So somebody with the dump and not this code can reproduce it."""
        sql = BeatTheBookie.query(879672)
        for token in ("odds_datetime", "odds_history_series", "bettype = '1x2'"):
            assert token in sql


@pytest.fixture
def db():
    con = connect()
    migrate(con)
    con.execute("INSERT INTO competitions VALUES ('ENG_PL', 'Premier League', 'ENG', 1, FALSE)")
    con.execute("INSERT INTO seasons VALUES ('2015-2016', DATE '2015-08-01', DATE '2016-05-31')")
    con.execute("INSERT INTO teams (team_id, canonical_name, country, created_at) "
                "VALUES ('h', 'Home FC', 'ENG', now()), ('a', 'Away FC', 'ENG', now())")
    con.execute("INSERT INTO bookmakers VALUES ('bk1', 'Book One', 'SHARP', TRUE, 0, NULL, 'ENG', NULL),"
                "('bk2', 'Book Two', 'SOFT', FALSE, 0, NULL, 'ENG', NULL)")
    con.execute(
        """INSERT INTO matches (match_id, competition_id, season_id, match_date_utc,
                                kickoff_utc, home_team_id, away_team_id, status, ingested_at)
           VALUES ('m1', 'ENG_PL', '2015-2016', DATE '2016-03-05', ?, 'h', 'a',
                   'SCHEDULED', now())""", [KICKOFF])
    yield con
    con.close()


def _observe(con, book, minutes_before, price, precision="TIMESTAMPED"):
    at = KICKOFF - timedelta(minutes=minutes_before)
    con.execute(
        """INSERT INTO odds_observations
           (observation_id, match_id, bookmaker_id, market_type, line, selection,
            price_decimal, capture_precision, captured_at, source, ingested_at)
           VALUES (?, 'm1', ?, 'ONE_X_TWO', 0.0, 'HOME', ?, ?, ?, 'constructed', now())""",
        [f"o_{book}_{minutes_before}_{precision}", book, price, precision,
         at if precision == "TIMESTAMPED" else None])


class TestThePathIgnoresUntimestampedPrices:
    def test_a_prematch_and_a_closing_price_produce_no_path(self, db):
        """Two observations of unknown instants give a total drift and say
        nothing about when it happened. Letting them in would produce a table
        that looks like a time series and is not one."""
        _observe(db, "bk1", 0, 2.20, precision="CLOSING")
        _observe(db, "bk1", 0, 2.35, precision="PREMATCH")
        assert db.execute("SELECT count(*) FROM v_market_path").fetchone()[0] == 0

    def test_an_empty_path_means_no_data_not_no_movement(self, db):
        """The same distinction PR #2 drew between DATA_GAP and NO_SIGNAL."""
        _observe(db, "bk1", 0, 2.35, precision="PREMATCH")
        coverage = db.execute("SELECT * FROM v_path_coverage").df().iloc[0]
        assert int(coverage["n_with_path"]) == 0
        assert int(coverage["n_untimestamped_rows"]) == 1


class TestThePathDescribesMovement:
    def test_consecutive_observations_carry_their_step(self, db):
        for minutes, price in ((180, 2.50), (120, 2.40), (60, 2.20)):
            _observe(db, "bk1", minutes, price)
        rows = db.execute(
            "SELECT price_decimal, previous_price, implied_delta, minutes_to_kickoff "
            "FROM v_market_path ORDER BY captured_at").df()
        assert len(rows) == 3
        assert rows["previous_price"].isna().iloc[0]
        assert rows["implied_delta"].iloc[2] > 0     # price shortening
        assert list(rows["minutes_to_kickoff"]) == [180, 120, 60]

    def test_a_reversal_shows_as_travel_without_drift(self, db):
        """Net drift alone would hide a price that moved out and came back —
        an overreaction and a correction look like nothing."""
        for minutes, price in ((180, 2.40), (120, 2.10), (60, 2.40)):
            _observe(db, "bk1", minutes, price)
        row = db.execute("SELECT * FROM v_market_summary").df().iloc[0]
        assert abs(float(row["net_implied_drift"])) < 1e-9
        assert float(row["total_implied_travel"]) > 0.10

    def test_a_small_step_is_not_a_move(self, db):
        for minutes, price in ((180, 2.400), (120, 2.395)):
            _observe(db, "bk1", minutes, price)
        assert db.execute("SELECT count(*) FROM v_market_moves").fetchone()[0] == 0

    def test_breadth_separates_one_book_from_the_market(self, db):
        """A single book moving can be a stale price being corrected. Every
        book moving is the market changing its mind, and only the second is
        information about the fixture."""
        for book in ("bk1", "bk2"):
            _observe(db, book, 180, 2.50)
            _observe(db, book, 120, 2.20)
        row = db.execute(
            "SELECT * FROM v_market_breadth ORDER BY minute DESC").df().iloc[0]
        assert int(row["n_books_moving"]) == 2


class TestNothingWasIngested:
    def test_no_beatthebookie_rows_exist_anywhere(self, db):
        """The dump is behind a blocked host. The adapter exists before its
        data, and this asserts that the distinction has not quietly eroded."""
        n = db.execute(
            "SELECT count(*) FROM odds_observations WHERE source = 'beatthebookie'"
        ).fetchone()[0]
        assert n == 0

    def test_the_source_is_registered_as_not_accessible(self):
        import json
        from pathlib import Path

        registry = json.loads(
            (Path(__file__).resolve().parents[2] / "docs/research/SOURCES.json").read_text())
        source = next(s for s in registry["sources"] if s["id"] == "beatthebookie-sql")
        assert source["pit_usable"]
        assert not source["accessible_here"]
        assert source["status"] == "USABLE_WITH_EXTERNAL_INGEST"
