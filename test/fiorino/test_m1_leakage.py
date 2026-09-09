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
    """The structural guard: deciders must go through the PIT reader.

    The list of guarded packages used to live here, and everything not on it
    was silently exempt. It now lives in fiorino.data.access.roles beside the
    reader it protects, and a package on NEITHER list fails: the default is
    "declare which you are", not "you are free".
    """

    def _root(self):
        from pathlib import Path

        import fiorino

        return Path(fiorino.__file__).parent

    def test_every_package_declares_a_role(self):
        """A package that declares nothing inherits no rule, and the guard
        would say nothing about it forever."""
        from fiorino.data.access.roles import DECIDERS, PRODUCERS

        root = self._root()
        declared = set(DECIDERS) | set(PRODUCERS)
        found = {p.name for p in root.iterdir()
                 if p.is_dir() and not p.name.startswith(("_", "."))}
        assert found <= declared, (
            f"undeclared packages: {sorted(found - declared)}. Add each to "
            "DECIDERS or PRODUCERS in fiorino/data/access/roles.py with the "
            "reason, so the guard covers it."
        )

    def _reads(self, packages, tables):
        root = self._root()
        found = []
        for package in packages:
            for path in (root / package).rglob("*.py"):
                text = path.read_text()
                for table in tables:
                    if f"FROM {table}" in text or f"JOIN {table}" in text:
                        found.append((package, path.name, table))
        return found

    def test_deciders_never_name_external_history(self):
        from fiorino.data.access.roles import (
            BOUNDED_READS,
            DECIDERS,
            HISTORY_TABLES,
        )

        offenders = [r for r in self._reads(DECIDERS, HISTORY_TABLES)
                     if r not in BOUNDED_READS]
        assert not offenders, (
            "these modules query external history directly and can therefore "
            f"see the future; read through PointInTimeView instead: {offenders}"
        )

    def test_every_bounded_read_is_still_real(self):
        """An exemption for a read that no longer exists is stale permission.
        It would quietly re-authorise the next edit that reintroduces it."""
        from fiorino.data.access.roles import (
            BOUNDED_READS,
            DECIDERS,
            HISTORY_TABLES,
        )

        actual = set(self._reads(DECIDERS, HISTORY_TABLES))
        stale = [k for k in BOUNDED_READS if k not in actual]
        assert not stale, f"exemptions for reads that no longer happen: {stale}"

    def test_every_bounded_read_states_why_it_is_safe(self):
        from fiorino.data.access.roles import BOUNDED_READS

        for key, reason in BOUNDED_READS.items():
            assert len(reason) > 80, f"{key}: the reason must be a reason"

    def test_no_decider_reaches_a_closing_price_by_another_spelling(self):
        """A closing price is also reachable as fair_probabilities filtered to
        capture_precision = 'CLOSING'. The table-name check walks past that;
        this hole was found by widening the guard, not by review."""
        from fiorino.data.access.roles import CLOSING_ALLOWED, DECIDERS

        root = self._root()
        offenders = []
        for package in DECIDERS:
            for path in (root / package).rglob("*.py"):
                if (package, path.name) in CLOSING_ALLOWED:
                    continue
                if "'CLOSING'" in path.read_text():
                    offenders.append(f"{path.relative_to(root)}")
        assert not offenders, (
            "a decider names the closing line without a declared reason: "
            f"{offenders}"
        )

    def test_every_closing_exemption_states_why_it_cannot_be_bet(self):
        from fiorino.data.access.roles import CLOSING_ALLOWED

        for key, reason in CLOSING_ALLOWED.items():
            assert len(reason) > 80, f"{key}: the reason must be a reason"

    def test_a_decider_may_read_its_own_ledger(self):
        """The distinction widening the guard forced. A backtest reading the
        equity curve it just wrote is not the same act as a strategy reading
        match results, and a guard that cannot tell them apart is useless."""
        from fiorino.data.access.roles import DECIDERS, LEDGER_TABLES

        assert self._reads(DECIDERS, LEDGER_TABLES), (
            "no decider reads a ledger table: either the engine changed or "
            "this distinction is no longer needed"
        )

    def test_every_guarded_table_exists(self):
        """A guard naming a table that does not exist cannot fail, and gives
        the same reassurance as one that can. The previous list contained
        'odds_snapshots', which is in no migration."""
        from fiorino.data.access.roles import (
            HISTORY_TABLES,
            LEDGER_TABLES,
            ORACLE_TABLES,
        )

        migrations = self._root() / "data" / "db" / "migrations"
        schema = " ".join(p.read_text() for p in migrations.glob("*.sql"))
        missing = [t for t in HISTORY_TABLES + LEDGER_TABLES + ORACLE_TABLES
                   if f"TABLE {t}" not in schema and f"VIEW {t}" not in schema]
        assert not missing, f"guarded names absent from the schema: {missing}"

    def test_only_the_declared_oracle_reads_a_closing_price(self):
        """Reading the close inside a decider is the clairvoyance the system
        exists to prevent. Exactly one file may, and it is named."""
        from fiorino.data.access.roles import (
            DECIDERS,
            ORACLE_ALLOWED,
            ORACLE_TABLES,
        )

        root = self._root()
        offenders = []
        for package in DECIDERS:
            for path in (root / package).rglob("*.py"):
                key = (package, path.name)
                if key in ORACLE_ALLOWED:
                    continue
                text = path.read_text()
                for table in ORACLE_TABLES:
                    if f"FROM {table}" in text or f"JOIN {table}" in text:
                        offenders.append(f"{path.relative_to(root)} -> {table}")
        assert not offenders, (
            "a closing price reached a decision. Only the declared oracle may "
            f"read one: {offenders}"
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
