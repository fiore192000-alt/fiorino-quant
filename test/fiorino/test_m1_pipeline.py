"""
M1 — bronze/silver pipeline: migrations, quarantine, dedup and merge,
cross-source joins, rebuild determinism.
"""

import pytest

from factories import PROMOTED, RELEGATED, SWAP_SEASON, TYPO, TYPO_SEASON, build_bronze, seed_identity
from fiorino.data.db.migrate import discover, migrate
from fiorino.data.identity.resolver import IdentityResolver
from fiorino.data.lake import list_bronze, read_bronze
from fiorino.data.pipeline import canonical_snapshot, ingest_bronze, rebuild_from_bronze


class TestMigrations:
    def test_versions_are_contiguous(self):
        versions = [m.version for m in discover()]
        assert versions == list(range(1, len(versions) + 1))

    def test_applying_twice_is_a_no_op(self, db):
        assert migrate(db) == []          # already applied by the fixture

    def test_a_changed_migration_is_refused(self, db, monkeypatch):
        migs = discover()
        target = migs[0]
        monkeypatch.setattr(type(target), "checksum", property(lambda self: "deadbeef"))
        with pytest.raises(RuntimeError, match="changed after being applied"):
            migrate(db)

    def test_from_empty_reaches_the_current_version(self):
        from fiorino.data.db.connection import connect, installed_version

        con = connect()
        migrate(con)
        assert installed_version(con) == len(discover())


class TestBronze:
    def test_bronze_is_immutable(self, seeded_db, tmp_path):
        from fiorino.data.lake import bronze_path, write_bronze

        target = bronze_path(tmp_path, "footballdata", "ENG_PL", "2020-2021", "run1")
        write_bronze(seeded_db, [{"a": "1"}], target)
        with pytest.raises(FileExistsError, match="immutable"):
            write_bronze(seeded_db, [{"a": "2"}], target)

    def test_partitions_are_written_per_source_competition_season(self, small_lake):
        files = list_bronze(small_lake)
        assert files, "no bronze written"
        assert all("source=" in str(f) and "competition=" in str(f) for f in files)

    def test_understat_gap_is_honest(self, seeded_db, tmp_path):
        """Understat does not cover Liga Portugal, so no partition exists."""
        root = tmp_path / "lake"
        build_bronze(seeded_db, root, competitions=["PRT_L1"], seasons=["2019-2020"])
        sources = {str(f).split("source=")[1].split("/")[0] for f in list_bronze(root)}
        assert "understat" not in sources
        assert {"footballdata", "fbref"} <= sources

    def test_read_order_is_canonical(self, seeded_db, small_lake):
        a = read_bronze(seeded_db, small_lake)
        b = read_bronze(seeded_db, small_lake)
        assert [r["source_id"] for r in a] == [r["source_id"] for r in b]


COMPS = ["ENG_PL", "PRT_L1"]
SEASONS_2 = ["2017-2018", "2019-2020"]


def build_ingested(lake):
    """Fresh database, identity seeded, lake ingested."""
    from fiorino.data.db.connection import connect
    from fiorino.data.db.migrate import migrate
    from fiorino.data.pipeline import bootstrap_reference

    con = connect()
    migrate(con)
    bootstrap_reference(con)
    resolver = IdentityResolver(con)
    seed_identity(con, resolver, competitions=COMPS, seasons=SEASONS_2)
    result = ingest_bronze(con, lake)
    return con, lake, result


@pytest.fixture(scope="module")
def ingested_ro(small_lake):
    """Ingested database shared by read-only tests."""
    con, lake, result = build_ingested(small_lake)
    yield con, lake, result
    con.close()


@pytest.fixture
def ingested(small_lake):
    """Ingested database for tests that mutate it."""
    con, lake, result = build_ingested(small_lake)
    yield con, lake, result
    con.close()


class TestQuarantine:
    """Rule 9 end to end: the typo must not reach `matches`."""

    def test_typo_matches_are_quarantined(self, ingested_ro):
        con, _, result = ingested_ro
        canonical, typo, source, comp = TYPO
        rows = con.execute(
            """SELECT DISTINCT source, season_id FROM match_quarantine
               WHERE raw_home_name = ? OR raw_away_name = ?""", [typo, typo],
        ).fetchall()
        assert rows, "the typo produced no quarantine record"
        assert {s for s, _ in rows} == {source}, "only the source with the typo"
        assert {ssn for _, ssn in rows} == {TYPO_SEASON}, "only the affected season"

    def test_everything_quarantined_has_a_recorded_cause(self, ingested_ro):
        """Quarantine is never a silent drop: each row says which side failed."""
        con, _, result = ingested_ro
        assert result.quarantined > 0
        n_uncaused = con.execute(
            "SELECT count(*) FROM match_quarantine WHERE reason IS NULL OR reason = ''"
        ).fetchone()[0]
        assert n_uncaused == 0

    def test_no_analytic_match_uses_the_typo(self, ingested_ro):
        con, _, _ = ingested_ro
        _, typo, _, _ = TYPO
        n = con.execute(
            """SELECT count(*) FROM v_analytic_matches m
               JOIN teams h ON h.team_id = m.home_team_id
               JOIN teams a ON a.team_id = m.away_team_id
               WHERE h.canonical_name = ? OR a.canonical_name = ?""", [typo, typo],
        ).fetchone()[0]
        assert n == 0

    def test_the_same_match_survives_via_other_sources(self, ingested_ro):
        """Quarantining one source's row must not lose the match itself."""
        con, _, _ = ingested_ro
        canonical, _, typo_source, comp = TYPO
        n = con.execute(
            """SELECT count(*) FROM v_analytic_matches m
               JOIN teams h ON h.team_id = m.home_team_id
               WHERE m.season_id = ? AND m.competition_id = ? AND h.canonical_name = ?""",
            [TYPO_SEASON, comp, canonical],
        ).fetchone()[0]
        assert n > 0, "footballdata and understat still supply these matches"

    def test_quarantine_records_why(self, ingested_ro):
        con, _, _ = ingested_ro
        rows = con.execute(
            "SELECT unresolved_side, reason FROM match_quarantine LIMIT 5"
        ).fetchall()
        assert all(side in ("HOME", "AWAY", "BOTH") for side, _ in rows)
        assert all(reason for _, reason in rows)


class TestDeterministicMatchId:
    def test_three_sources_converge_on_one_match(self, ingested_ro):
        con, _, _ = ingested_ro
        rows = con.execute(
            "SELECT n_sources, count(*) FROM v_cross_source_matches GROUP BY 1 ORDER BY 1"
        ).fetchall()
        multi = sum(c for n, c in rows if n >= 2)
        assert multi > 0
        assert max(n for n, _ in rows) >= 2

    def test_a_kickoff_time_correction_updates_rather_than_duplicates(self, ingested):
        """The reason match_id hashes the DATE and not the instant."""
        from datetime import timedelta

        from fiorino.data.ingest.silver import transform_bronze
        from fiorino.config.registries import country_of

        con, lake, _ = ingested
        before = con.execute("SELECT count(*) FROM matches").fetchone()[0]

        rows = read_bronze(con, lake, source="footballdata")[:5]
        corrected = []
        for r in rows:
            r = dict(r)
            from datetime import datetime
            ts = datetime.fromisoformat(r["kickoff_utc"])
            r["kickoff_utc"] = (ts + timedelta(minutes=15)).isoformat()
            corrected.append(r)

        run = con.execute("SELECT ingestion_run_id FROM ingestion_runs LIMIT 1").fetchone()[0]
        transform_bronze(con, corrected, country_of=country_of(), ingestion_run_id=run)

        after = con.execute("SELECT count(*) FROM matches").fetchone()[0]
        assert after == before, "a corrected kickoff time must not mint a second match"

    def test_reingesting_the_same_bronze_is_idempotent(self, ingested):
        con, lake, _ = ingested
        before = con.execute("SELECT count(*) FROM matches").fetchone()[0]
        ingest_bronze(con, lake)
        assert con.execute("SELECT count(*) FROM matches").fetchone()[0] == before


class TestControlledMerge:
    def test_a_merge_redirects_lookups_and_removes_the_loser(self, ingested):
        from fiorino.data.ingest.silver import merge_matches, resolve_match_id

        con, _, _ = ingested
        a, b = [r[0] for r in con.execute("SELECT match_id FROM matches LIMIT 2").fetchall()]
        merge_matches(con, merged=a, surviving=b, reason="postponed, re-listed", created_by="ops")

        assert resolve_match_id(con, a) == b
        assert con.execute("SELECT count(*) FROM matches WHERE match_id = ?", [a]).fetchone()[0] == 0
        assert con.execute(
            "SELECT count(*) FROM match_source_ids WHERE match_id = ?", [a]
        ).fetchone()[0] == 0

    def test_merged_matches_leave_the_analytic_view(self, ingested):
        from fiorino.data.ingest.silver import merge_matches

        con, _, _ = ingested
        a, b = [r[0] for r in con.execute("SELECT match_id FROM matches LIMIT 2").fetchall()]
        before = con.execute("SELECT count(*) FROM v_analytic_matches").fetchone()[0]
        merge_matches(con, a, b, "duplicate", "ops")
        assert con.execute("SELECT count(*) FROM v_analytic_matches").fetchone()[0] == before - 1

    def test_self_merge_is_refused(self, ingested):
        from fiorino.data.ingest.silver import merge_matches

        con, _, _ = ingested
        a = con.execute("SELECT match_id FROM matches LIMIT 1").fetchone()[0]
        with pytest.raises(ValueError, match="into itself"):
            merge_matches(con, a, a, "nonsense", "ops")


class TestPromotionRelegation:
    def test_a_promoted_club_keeps_one_identity_across_divisions(self, seeded_db, tmp_path):
        root = tmp_path / "lake"
        seasons = ["2017-2018", "2019-2020"]
        build_bronze(seeded_db, root, competitions=["ENG_PL", "ENG_CH"], seasons=seasons)
        resolver = IdentityResolver(seeded_db)
        seed_identity(seeded_db, resolver, competitions=["ENG_PL", "ENG_CH"], seasons=seasons)
        ingest_bronze(seeded_db, root)

        rows = seeded_db.execute(
            """SELECT ms.competition_id, ms.season_id FROM team_season_membership ms
               JOIN teams t ON t.team_id = ms.team_id
               WHERE t.canonical_name = ? ORDER BY 2, 1""", [PROMOTED],
        ).fetchall()
        comps = {c for c, _ in rows}
        assert comps == {"ENG_PL", "ENG_CH"}, "one club, two divisions"

        n_ids = seeded_db.execute(
            "SELECT count(*) FROM teams WHERE canonical_name = ?", [PROMOTED]
        ).fetchone()[0]
        assert n_ids == 1, "promotion must not mint a second team"

        assert ("ENG_CH", "2017-2018") in rows
        assert ("ENG_PL", SWAP_SEASON) in rows

    def test_the_relegated_club_moves_the_other_way(self, seeded_db, tmp_path):
        root = tmp_path / "lake"
        seasons = ["2017-2018", "2019-2020"]
        build_bronze(seeded_db, root, competitions=["ENG_PL", "ENG_CH"], seasons=seasons)
        resolver = IdentityResolver(seeded_db)
        seed_identity(seeded_db, resolver, competitions=["ENG_PL", "ENG_CH"], seasons=seasons)
        ingest_bronze(seeded_db, root)
        rows = set(seeded_db.execute(
            """SELECT ms.competition_id, ms.season_id FROM team_season_membership ms
               JOIN teams t ON t.team_id = ms.team_id WHERE t.canonical_name = ?""", [RELEGATED],
        ).fetchall())
        assert ("ENG_PL", "2017-2018") in rows
        assert ("ENG_CH", SWAP_SEASON) in rows


class TestRebuildDeterminism:
    """Semantic determinism, not byte equality."""

    def test_rebuild_from_bronze_reproduces_the_same_facts(self, seeded_db, small_lake):
        from fiorino.data.db.connection import connect
        from fiorino.data.db.migrate import migrate

        resolver = IdentityResolver(seeded_db)
        seed_identity(seeded_db, resolver,
                      competitions=["ENG_PL", "PRT_L1"], seasons=["2017-2018", "2019-2020"])
        ingest_bronze(seeded_db, small_lake)
        first = canonical_snapshot(seeded_db)

        fresh = connect()
        migrate(fresh)
        r2 = IdentityResolver(fresh)
        from fiorino.data.pipeline import bootstrap_reference

        bootstrap_reference(fresh)
        seed_identity(fresh, r2, competitions=["ENG_PL", "PRT_L1"],
                      seasons=["2017-2018", "2019-2020"])
        ingest_bronze(fresh, small_lake)
        second = canonical_snapshot(fresh)

        assert first.matches == second.matches
        assert first.results == second.results
        assert first.teams == second.teams
        assert first.memberships == second.memberships
        assert first.source_ids == second.source_ids
        fresh.close()

    def test_surrogate_ids_legitimately_differ(self, seeded_db, small_lake):
        """team_id is randomly minted; that is why the snapshot compares names."""
        from fiorino.data.db.connection import connect
        from fiorino.data.db.migrate import migrate
        from fiorino.data.pipeline import bootstrap_reference

        r1 = IdentityResolver(seeded_db)
        a = r1.register_team("Ajax", "NLD")
        fresh = connect()
        migrate(fresh)
        bootstrap_reference(fresh)
        b = IdentityResolver(fresh).register_team("Ajax", "NLD")
        assert a != b
        fresh.close()


class TestProvenance:
    def test_every_match_has_a_source_and_a_run(self, ingested_ro):
        con, _, _ = ingested_ro
        assert con.execute(
            """SELECT count(*) FROM matches m WHERE m.ingestion_run_id IS NULL
               OR NOT EXISTS (SELECT 1 FROM match_source_ids s WHERE s.match_id = m.match_id)"""
        ).fetchone()[0] == 0

    def test_source_ids_are_recorded_for_teams(self, ingested_ro):
        con, _, _ = ingested_ro
        assert con.execute("SELECT count(*) FROM team_source_ids").fetchone()[0] > 0

    def test_runs_record_counts(self, ingested_ro):
        con, _, _ = ingested_ro
        rows = con.execute(
            "SELECT rows_read, rows_written, status FROM ingestion_runs"
        ).fetchall()
        assert rows and all(r[0] > 0 and r[2] == "DONE" for r in rows)

    def test_a_source_id_cannot_be_remapped(self, ingested):
        from fiorino.data.ingest.silver import _upsert_team_source_id

        con, _, _ = ingested
        source, sid, tid = con.execute(
            "SELECT source, source_id, team_id FROM team_source_ids LIMIT 1"
        ).fetchone()
        other = con.execute(
            "SELECT team_id FROM teams WHERE team_id <> ? LIMIT 1", [tid]
        ).fetchone()[0]
        with pytest.raises(ValueError, match="collision"):
            _upsert_team_source_id(con, source, sid, other)
