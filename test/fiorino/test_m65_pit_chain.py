"""
M6.5 — the end-to-end point-in-time chain, and the lineup entity.

Every check here is exercised twice: once on data that satisfies it, and once
on data constructed to violate it. A guard that has never fired is a guard
nobody has tested, and this file exists because M1's own leakage guard caught a
real bug in M4 only because something actually violated it.
"""

from datetime import datetime, timedelta, timezone

import pytest

from fiorino.data.db.connection import connect
from fiorino.data.db.migrate import migrate
from fiorino.data.identity.audit import BLOCKING, WARNING
from fiorino.data.quality.pit_chain import (
    PIT_CHAIN_CHECKS,
    check_decision_precedes_kickoff,
    check_kickoff_precedes_settlement,
    check_lineup_informed_bets,
    check_lineup_precedes_kickoff,
    check_timestamped_coverage,
    run_pit_chain_audit,
)

UTC = timezone.utc
KICKOFF = datetime(2025, 3, 1, 15, 0, tzinfo=UTC)


@pytest.fixture
def db():
    con = connect()
    migrate(con)
    con.execute("INSERT INTO competitions VALUES ('ENG_PL', 'Premier League', 'ENG', 1, FALSE)")
    con.execute("INSERT INTO seasons VALUES ('2024-2025', DATE '2024-08-01', DATE '2025-05-31')")
    con.execute("INSERT INTO teams (team_id, canonical_name, country, created_at) "
                "VALUES ('t_home', 'Home FC', 'ENG', now()), ('t_away', 'Away FC', 'ENG', now())")
    con.execute(
        """INSERT INTO matches (match_id, competition_id, season_id, match_date_utc,
                                kickoff_utc, home_team_id, away_team_id, status, ingested_at)
           VALUES ('m1', 'ENG_PL', '2024-2025', DATE '2025-03-01', ?, 't_home', 't_away',
                   'SCHEDULED', now())""", [KICKOFF])
    yield con
    con.close()


def _add_result(con, settled_at):
    con.execute(
        """INSERT INTO match_results (match_id, goals_home, goals_away, settled_at, source, ingested_at)
           VALUES ('m1', 2, 1, ?, 'test', now())""", [settled_at])


def _add_lineup(con, published_at, status="CONFIRMED", lineup_id="l1"):
    con.execute("INSERT INTO players VALUES ('p1', 'A Player', NULL, now(), NULL)")
    con.execute(
        """INSERT INTO lineups (lineup_id, match_id, team_id, source, published_at,
                                lineup_status, ingested_at)
           VALUES (?, 'm1', 't_home', 'test', ?, ?, now())""",
        [lineup_id, published_at, status])
    con.execute("INSERT INTO lineup_slots VALUES (?, 'p1', 'STARTER', 9)", [lineup_id])


class TestKickoffAndSettlement:
    def test_a_result_settling_after_kickoff_is_accepted(self, db):
        _add_result(db, KICKOFF + timedelta(hours=2))
        assert check_kickoff_precedes_settlement(db) == []

    def test_a_result_settling_before_kickoff_is_caught(self, db):
        _add_result(db, KICKOFF - timedelta(hours=1))
        findings = check_kickoff_precedes_settlement(db)
        assert len(findings) == 1
        assert findings[0].severity == BLOCKING
        assert findings[0].n_affected == 1


class TestLineupOrdering:
    """The link the milestone exists for."""

    def test_a_lineup_published_before_kickoff_is_accepted(self, db):
        _add_lineup(db, KICKOFF - timedelta(minutes=70))
        assert check_lineup_precedes_kickoff(db) == []

    def test_a_lineup_published_after_kickoff_is_flagged(self, db):
        """Back-filled after the match. Not corrupt, but it can never inform a
        decision, and counting it as available turns a lineup study into a
        post-hoc study."""
        _add_lineup(db, KICKOFF + timedelta(minutes=5))
        findings = check_lineup_precedes_kickoff(db)
        assert len(findings) == 1
        assert findings[0].severity == WARNING

    def test_a_predicted_eleven_is_not_an_analytic_lineup(self, db):
        """PREDICTED is a forecast OF the eleven, a different fact entirely."""
        _add_lineup(db, KICKOFF + timedelta(minutes=5), status="PREDICTED")
        assert check_lineup_precedes_kickoff(db) == []
        assert db.execute("SELECT count(*) FROM v_analytic_lineups").fetchone()[0] == 0

    def test_published_at_has_no_default(self, db):
        """The column the whole milestone depends on cannot be fabricated by
        omission: no DEFAULT, NOT NULL."""
        with pytest.raises(Exception):
            db.execute(
                """INSERT INTO lineups (lineup_id, match_id, team_id, source,
                                        lineup_status, ingested_at)
                   VALUES ('l2', 'm1', 't_home', 'test', 'CONFIRMED', now())""")


class TestPlayerIdentityFollowsRuleNine:
    def test_a_fuzzy_player_alias_is_refused_by_the_database(self, db):
        """Rule 9 on a new entity. Player names collide far more than club
        names — initials, transliterations, fathers and sons — so a fuzzy
        alias here is more dangerous, not less."""
        db.execute("INSERT INTO players VALUES ('p9', 'Someone', NULL, now(), NULL)")
        with pytest.raises(Exception):
            db.execute(
                """INSERT INTO player_aliases
                   (alias_id, player_id, source, raw_name, normalized_name, match_method)
                   VALUES ('a1', 'p9', 'src', 'Somone', 'somone', 'FUZZY')""")

    def test_an_adjudicated_alias_is_accepted(self, db):
        db.execute("INSERT INTO players VALUES ('p9', 'Someone', NULL, now(), NULL)")
        db.execute(
            """INSERT INTO player_aliases
               (alias_id, player_id, source, raw_name, normalized_name,
                match_method, status, decided_by, decided_at)
               VALUES ('a1', 'p9', 'src', 'S. Omeone', 's omeone', 'MANUAL',
                       'APPROVED', 'human', now())""")
        assert db.execute("SELECT count(*) FROM player_aliases").fetchone()[0] == 1

    def test_a_slot_cannot_name_a_player_that_does_not_exist(self, db):
        """The foreign key, not the view, is what makes this impossible — which
        is why the view guards something else."""
        _add_lineup(db, KICKOFF - timedelta(minutes=70))
        with pytest.raises(Exception):
            db.execute("INSERT INTO lineup_slots VALUES ('l1', 'ghost', 'BENCH', 7)")

    def test_a_lineup_with_an_unadjudicated_player_leaves_the_analytic_view(self, db):
        """The guard that IS reachable, and the one M1 showed matters: a player
        who exists but whose alias is only PROPOSED. One wrong identity
        corrupts the label for the whole match, because an 'unexpected absence'
        is computed against the entire eleven."""
        _add_lineup(db, KICKOFF - timedelta(minutes=70))
        db.execute(
            """INSERT INTO player_aliases
               (alias_id, player_id, source, raw_name, normalized_name,
                match_method, status)
               VALUES ('a1', 'p1', 'src', 'A. Player', 'a player', 'EXACT', 'PROPOSED')""")
        assert db.execute("SELECT count(*) FROM v_analytic_lineups").fetchone()[0] == 0

        db.execute("UPDATE player_aliases SET status = 'APPROVED' WHERE alias_id = 'a1'")
        assert db.execute("SELECT count(*) FROM v_analytic_lineups").fetchone()[0] == 1


class TestCoverageIsReportedNotAssumed:
    def test_an_empty_database_says_the_links_are_untested(self, db):
        """The most dangerous output this module could produce is 'all clean'
        over an empty set."""
        findings = check_timestamped_coverage(db)
        assert findings and findings[0].check_name == "no_lineups"

    def test_untimestamped_odds_are_reported_as_untested(self, db):
        db.execute("INSERT INTO bookmakers VALUES ('bk', 'Book', 'SOFT', FALSE, 0.0, NULL, 'ENG', NULL)")
        db.execute(
            """INSERT INTO odds_observations
               (observation_id, match_id, bookmaker_id, market_type, line, selection,
                price_decimal, capture_precision, captured_at, source, ingested_at)
               VALUES ('o1', 'm1', 'bk', 'ONE_X_TWO', 0.0, 'HOME', 2.10,
                       'PREMATCH', NULL, 'test', now())""")  # noqa: E501
        findings = check_timestamped_coverage(db)
        assert findings[0].check_name == "no_timestamped_odds"
        assert "untested, not proven" in findings[0].detail

    def test_the_audit_runs_every_check(self, db):
        run_pit_chain_audit(db)
        assert len(PIT_CHAIN_CHECKS) == 8


class TestTheWholeChain:
    def test_a_coherent_chain_produces_no_blocking_finding(self, db):
        _add_result(db, KICKOFF + timedelta(hours=2))
        _add_lineup(db, KICKOFF - timedelta(minutes=70))
        blocking = [f for f in run_pit_chain_audit(db) if f.severity == BLOCKING]
        assert blocking == []

    def test_one_broken_link_is_enough_to_block(self, db):
        _add_result(db, KICKOFF - timedelta(hours=1))
        _add_lineup(db, KICKOFF - timedelta(minutes=70))
        blocking = [f for f in run_pit_chain_audit(db) if f.severity == BLOCKING]
        assert [f.check_name for f in blocking] == ["settlement_before_kickoff"]

    def test_the_audit_returns_findings_rather_than_raising(self, db):
        """One run must report every problem, not stop at the first."""
        _add_result(db, KICKOFF - timedelta(hours=1))
        _add_lineup(db, KICKOFF + timedelta(minutes=5))
        names = {f.check_name for f in run_pit_chain_audit(db)}
        assert "settlement_before_kickoff" in names
        assert "lineup_published_after_kickoff" in names
