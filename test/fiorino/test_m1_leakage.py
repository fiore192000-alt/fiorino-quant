"""
M1 — point-in-time correctness.

Requirement 8: nothing knowable only after kickoff may reach a consumer that
runs before it. This is the property that makes every later milestone
trustworthy, so it is tested by construction and by Hypothesis rather than by
a couple of examples.
"""

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fiorino.data.access.point_in_time import PointInTimeView
from fiorino.data.ingest.silver import MATCH_DURATION

UTC = timezone.utc


@pytest.fixture
def timeline(seeded_db):
    """Three matches on three consecutive days, with known settle instants."""
    con = seeded_db
    con.execute(
        """INSERT INTO teams VALUES
           ('t1','Alpha','ENG',now(),NULL), ('t2','Beta','ENG',now(),NULL),
           ('t3','Gamma','ENG',now(),NULL)"""
    )
    con.execute(
        """INSERT INTO ingestion_runs (ingestion_run_id, source, started_at, status)
           VALUES ('run1','test',now(),'DONE')"""
    )
    made = []
    for i, (h, a) in enumerate([("t1", "t2"), ("t2", "t3"), ("t3", "t1")]):
        kickoff = datetime(2021, 1, 10 + i, 15, 0, tzinfo=UTC)
        mid = f"m{i}"
        con.execute(
            """INSERT INTO matches (match_id, competition_id, season_id, match_date_utc,
               kickoff_utc, home_team_id, away_team_id, status, ingestion_run_id)
               VALUES (?, 'ENG_PL', '2020-2021', ?, ?, ?, ?, 'FINISHED', 'run1')""",
            [mid, kickoff.date(), kickoff, h, a],
        )
        con.execute(
            """INSERT INTO match_results VALUES (?, 2, 1, NULL, NULL, ?, 'test', now())""",
            [mid, kickoff + MATCH_DURATION],
        )
        con.execute(
            "INSERT INTO match_source_ids VALUES ('test', ?, ?, 'run1', now())", [mid, mid]
        )
        made.append((mid, kickoff))
    return con, made


class TestResultsAreNotVisibleEarly:
    def test_no_result_before_the_first_match_ends(self, timeline):
        con, made = timeline
        _, first_kickoff = made[0]
        view = PointInTimeView.at(con, first_kickoff)
        assert view.results() == []

    def test_a_result_appears_only_after_it_settles(self, timeline):
        con, made = timeline
        mid, kickoff = made[0]
        assert PointInTimeView.at(con, kickoff + MATCH_DURATION - timedelta(seconds=1)).results() == []
        after = PointInTimeView.at(con, kickoff + MATCH_DURATION).results()
        assert [r["match_id"] for r in after] == [mid]

    def test_results_accumulate_monotonically(self, timeline):
        con, made = timeline
        counts = [
            len(PointInTimeView.at(con, k + MATCH_DURATION).results()) for _, k in made
        ]
        assert counts == [1, 2, 3]

    def test_a_match_never_sees_its_own_result(self, timeline):
        """The single most important invariant in the system."""
        con, made = timeline
        for mid, kickoff in made:
            visible = {r["match_id"] for r in PointInTimeView.at(con, kickoff).results()}
            assert mid not in visible


class TestUpcomingMatches:
    def test_only_future_matches_are_bettable(self, timeline):
        con, made = timeline
        _, second = made[1]
        upcoming = PointInTimeView.at(con, second - timedelta(hours=1)).upcoming_matches()
        ids = [m["match_id"] for m in upcoming]
        assert "m0" not in ids and "m1" in ids and "m2" in ids

    def test_nothing_is_bettable_after_the_last_kickoff(self, timeline):
        con, made = timeline
        _, last = made[-1]
        assert PointInTimeView.at(con, last + timedelta(seconds=1)).upcoming_matches() == []


class TestMembershipIsPointInTime:
    def test_membership_is_derived_from_matches_played(self, timeline):
        con, made = timeline
        _, first = made[0]
        before = PointInTimeView.at(con, first - timedelta(days=1)).team_membership()
        assert before == []
        after = PointInTimeView.at(con, made[-1][1]).team_membership()
        assert {r["team_id"] for r in after} == {"t1", "t2", "t3"}


class TestViewContract:
    def test_naive_timestamps_are_rejected(self, seeded_db):
        with pytest.raises(ValueError, match="timezone-aware"):
            PointInTimeView(seeded_db, datetime(2021, 1, 1))

    def test_a_view_cannot_travel_backwards(self, seeded_db):
        view = PointInTimeView.at(seeded_db, datetime(2021, 6, 1, tzinfo=UTC))
        with pytest.raises(ValueError, match="backwards"):
            view.advance_to(datetime(2021, 1, 1, tzinfo=UTC))

    def test_advancing_forwards_is_allowed(self, seeded_db):
        view = PointInTimeView.at(seeded_db, datetime(2021, 1, 1, tzinfo=UTC))
        assert view.advance_to(datetime(2021, 6, 1, tzinfo=UTC)).as_of.month == 6


class TestNoRawTableAccessInConsumers:
    """The structural guard: consumers must go through the PIT reader."""

    RAW_TABLES = ("matches", "match_results", "odds_snapshots", "team_aliases")
    GUARDED = ("strategy", "backtest", "portfolio", "staking", "pricing")

    def test_consumer_packages_never_name_a_raw_table(self):
        from pathlib import Path

        import fiorino

        root = Path(fiorino.__file__).parent
        offenders = []
        for package in self.GUARDED:
            for path in (root / package).rglob("*.py"):
                text = path.read_text()
                for table in self.RAW_TABLES:
                    if f"FROM {table}" in text or f"from {table}" in text:
                        offenders.append(f"{path.relative_to(root)} -> {table}")
        assert not offenders, (
            "these modules query raw tables directly and can therefore see the "
            f"future; read through PointInTimeView instead: {offenders}"
        )


class TestLeakageProperties:
    """Hypothesis: no reachable clock exposes a result settled after it.

    The `timeline` fixture is function-scoped and therefore not rebuilt between
    generated inputs. That is fine here and the suppression is deliberate:
    these properties only read, so a shared database is exactly the fixed
    history we want to probe from many different clocks.
    """

    _RO = settings(
        max_examples=50, deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )

    @_RO
    @given(offset_hours=st.integers(min_value=-48, max_value=96))
    def test_no_result_is_ever_visible_before_it_settles(self, timeline, offset_hours):
        con, made = timeline
        base = made[0][1]
        as_of = base + timedelta(hours=offset_hours)
        for row in PointInTimeView.at(con, as_of).results():
            assert row["settled_at"] <= as_of

    @_RO
    @given(offset_hours=st.integers(min_value=-48, max_value=96))
    def test_upcoming_never_includes_a_started_match(self, timeline, offset_hours):
        con, made = timeline
        as_of = made[0][1] + timedelta(hours=offset_hours)
        for row in PointInTimeView.at(con, as_of).upcoming_matches():
            assert row["kickoff_utc"] > as_of

    @_RO
    @given(offset_hours=st.integers(min_value=0, max_value=96))
    def test_results_and_upcoming_never_overlap(self, timeline, offset_hours):
        con, made = timeline
        view = PointInTimeView.at(con, made[0][1] + timedelta(hours=offset_hours))
        settled = {r["match_id"] for r in view.results()}
        upcoming = {m["match_id"] for m in view.upcoming_matches()}
        assert not (settled & upcoming)
