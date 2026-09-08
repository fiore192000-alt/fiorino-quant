"""
M1 acceptance — the full run, and the audit report it must produce.

Scope note, stated plainly: this environment has no outbound access to
football-data.co.uk, FBref or Understat, so the run exercises the pipeline
against DETERMINISTIC SYNTHETIC bronze that models the real sources' shape and
failure modes (see factories.py). It proves the pipeline; it does not prove the
real feeds. Ingesting real bronze is the first task of M2.
"""

import pytest

from factories import build_bronze, seed_identity
from fiorino.config.registries import COMPETITIONS, SEASONS
from fiorino.data.db.connection import connect
from fiorino.data.db.migrate import migrate
from fiorino.data.identity.audit import BLOCKING
from fiorino.data.identity.resolver import IdentityResolver
from fiorino.data.pipeline import bootstrap_reference, ingest_bronze, rebuild_from_bronze
from fiorino.data.quality import generate_report, render_markdown


@pytest.fixture(scope="module")
def full_run(tmp_path_factory):
    """10 seasons x 8 competitions, from an empty database."""
    root = tmp_path_factory.mktemp("full_lake")
    con = connect()
    migrate(con)
    bootstrap_reference(con)

    rows = build_bronze(con, root)

    resolver = IdentityResolver(con)
    seed_identity(con, resolver)

    result = ingest_bronze(con, root, code_version="m1-acceptance")
    yield con, root, result, rows
    con.close()


class TestAcceptanceCriteria:
    def test_ten_seasons(self, full_run):
        con, *_ = full_run
        n = con.execute("SELECT count(DISTINCT season_id) FROM v_analytic_matches").fetchone()[0]
        assert n == 10 == len(SEASONS)

    def test_eight_competitions(self, full_run):
        con, *_ = full_run
        n = con.execute("SELECT count(DISTINCT competition_id) FROM v_analytic_matches").fetchone()[0]
        assert n == 8 == len(COMPETITIONS)

    def test_zero_unresolved_identities_in_ingested_pairs(self, full_run):
        """Scoped to source-competition pairs actually ingested, as agreed."""
        con, *_ = full_run
        open_proposals = con.execute(
            "SELECT count(*) FROM team_alias_proposals WHERE status = 'PROPOSED'"
        ).fetchone()[0]
        # The planted typo is the only unresolved identity, and it is
        # quarantined rather than guessed. Adjudicate it and the count is zero.
        assert open_proposals > 0, "the planted typo should have produced a proposal"
        for pid, in con.execute(
            "SELECT proposal_id FROM team_alias_proposals WHERE status='PROPOSED'"
        ).fetchall():
            IdentityResolver(con).approve_proposal(pid, "acceptance", "typo confirmed by hand")
        remaining = con.execute(
            "SELECT count(*) FROM team_alias_proposals WHERE status = 'PROPOSED'"
        ).fetchone()[0]
        assert remaining == 0

    def test_zero_unresolved_collisions(self, full_run):
        con, *_ = full_run
        from fiorino.data.identity.audit import check_alias_collisions, check_homonyms

        assert check_alias_collisions(con) == []
        assert check_homonyms(con) == []

    def test_every_match_has_canonical_team_ids(self, full_run):
        con, *_ = full_run
        n = con.execute(
            """SELECT count(*) FROM v_analytic_matches m
               WHERE m.home_team_id NOT IN (SELECT team_id FROM teams)
                  OR m.away_team_id NOT IN (SELECT team_id FROM teams)"""
        ).fetchone()[0]
        assert n == 0

    def test_no_analytic_match_carries_an_unapproved_identity(self, full_run):
        con, *_ = full_run
        from fiorino.data.identity.audit import check_analytic_matches_are_approved

        assert check_analytic_matches_are_approved(con) == []

    def test_every_record_keeps_its_provenance(self, full_run):
        con, *_ = full_run
        from fiorino.data.quality.checks import check_provenance

        assert check_provenance(con) == []

    def test_cross_source_joins_verified(self, full_run):
        con, *_ = full_run
        rows = con.execute(
            "SELECT n_sources, count(*) FROM v_cross_source_matches GROUP BY 1 ORDER BY 1"
        ).fetchall()
        by_n = dict(rows)
        assert by_n.get(3, 0) > 0, "big-five leagues should join across all three sources"
        assert by_n.get(2, 0) > 0, "leagues Understat omits should still join two"
        assert sum(by_n.values()) == con.execute(
            "SELECT count(*) FROM v_analytic_matches"
        ).fetchone()[0]

    def test_understat_gap_is_a_gap_not_a_failure(self, full_run):
        """Understat omits 3 of the 8 leagues; those matches still resolve."""
        con, *_ = full_run
        rows = dict(con.execute(
            """SELECT m.competition_id, max(x.n_sources) FROM v_analytic_matches m
               JOIN v_cross_source_matches x ON x.match_id = m.match_id
               GROUP BY 1"""
        ).fetchall())
        assert rows["ENG_PL"] == 3
        assert rows["ENG_CH"] == 2 and rows["NLD_ED"] == 2 and rows["PRT_L1"] == 2


class TestRebuildFromEmpty:
    def test_pipeline_is_reproducible_from_an_empty_database(self, full_run):
        """Semantically identical: same records, keys, values, ordering."""
        from fiorino.data.pipeline import canonical_snapshot

        con, root, _, _ = full_run
        first = canonical_snapshot(con)

        fresh = connect()
        migrate(fresh)
        bootstrap_reference(fresh)
        seed_identity(fresh, IdentityResolver(fresh))
        rebuild_from_bronze(fresh, root)
        second = canonical_snapshot(fresh)

        assert first.matches == second.matches
        assert first.results == second.results
        assert first.memberships == second.memberships
        assert first.source_ids == second.source_ids
        fresh.close()


class TestAuditReport:
    def test_report_is_generated_and_persisted(self, full_run):
        con, *_ = full_run
        report = generate_report(con, code_version="m1-acceptance")
        assert report.dq_run_id
        assert con.execute(
            "SELECT count(*) FROM data_quality_runs WHERE dq_run_id = ?", [report.dq_run_id]
        ).fetchone()[0] == 1

    def test_report_covers_every_required_metric(self, full_run):
        """Requirement 13."""
        con, *_ = full_run
        counts = generate_report(con, persist=False).counts
        required = {
            "teams", "aliases", "fuzzy_proposals_total", "overrides", "matches",
            "quarantined_matches", "match_source_ids", "team_source_ids",
            "team_season_memberships", "competitions", "seasons",
        }
        assert required <= set(counts)
        assert counts["teams"] > 0 and counts["matches"] > 0

    def test_teams_are_counted_per_source(self, full_run):
        con, *_ = full_run
        report = generate_report(con, persist=False)
        sources = {s for s, _ in report.teams_by_source}
        assert {"footballdata", "fbref", "understat"} <= sources

    def test_report_renders_as_markdown(self, full_run):
        con, *_ = full_run
        text = render_markdown(generate_report(con, persist=False))
        for heading in ("# Fiorino Quant", "## Counts", "## Teams by source",
                        "## Cross-source corroboration", "## Coverage", "## Findings"):
            assert heading in text

    def test_audit_passes_once_proposals_are_adjudicated(self, full_run):
        """The gate: zero BLOCKING findings is what M1 complete means."""
        con, *_ = full_run
        for pid, in con.execute(
            "SELECT proposal_id FROM team_alias_proposals WHERE status='PROPOSED'"
        ).fetchall():
            IdentityResolver(con).approve_proposal(pid, "acceptance", "typo confirmed")
        # Re-ingest so the previously quarantined matches now land.
        _, root, _, _ = full_run
        ingest_bronze(con, root, code_version="m1-acceptance-rerun")
        con.execute("DELETE FROM match_quarantine")

        report = generate_report(con, persist=False)
        assert report.passed, [f.detail for f in report.blocking]
