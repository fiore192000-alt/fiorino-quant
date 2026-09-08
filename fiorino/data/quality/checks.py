"""
Data-quality checks. Each is a pure function of the database.

Findings are returned, not raised, so one run reports every problem rather than
stopping at the first. Severity decides what blocks: BLOCKING must be zero for
M1 to be considered complete.
"""

from __future__ import annotations

from fiorino.data.identity.audit import BLOCKING, INFO, WARNING, Finding, run_identity_audit

__all__ = ["run_all_checks", "COUNT_QUERIES", "QUALITY_CHECKS"]


def _scalar(con, sql, params=None):
    row = con.execute(sql, params or []).fetchone()
    return row[0] if row else 0


def check_duplicate_matches(con) -> list[Finding]:
    """Same teams, same competition, same date, two rows."""
    rows = con.execute(
        """SELECT competition_id, season_id, match_date_utc, home_team_id, away_team_id,
                  count(*) AS n
           FROM matches GROUP BY 1,2,3,4,5 HAVING n > 1"""
    ).fetchall()
    return [
        Finding("duplicate_match", BLOCKING, f"{n} rows for {h} vs {a} in {c}/{s} on {d}", n)
        for c, s, d, h, a, n in rows
    ]


def check_missing_results(con) -> list[Finding]:
    n = _scalar(
        con,
        """SELECT count(*) FROM v_analytic_matches m
           LEFT JOIN match_results r ON r.match_id = m.match_id
           WHERE r.match_id IS NULL AND m.status = 'FINISHED'""",
    )
    return [Finding("missing_result", WARNING, f"{n} finished matches have no result", n)] if n else []


def check_result_before_kickoff(con) -> list[Finding]:
    """A result knowable at or before kickoff is leakage, full stop."""
    n = _scalar(
        con,
        """SELECT count(*) FROM match_results r JOIN matches m ON m.match_id = r.match_id
           WHERE r.settled_at <= m.kickoff_utc""",
    )
    return [
        Finding("result_settled_before_kickoff", BLOCKING,
                f"{n} results are marked knowable at or before kickoff", n)
    ] if n else []


def check_match_outside_season(con) -> list[Finding]:
    n = _scalar(
        con,
        """SELECT count(*) FROM matches m JOIN seasons s ON s.season_id = m.season_id
           WHERE m.match_date_utc < s.starts_on OR m.match_date_utc > s.ends_on""",
    )
    return [
        Finding("match_outside_season", WARNING, f"{n} matches fall outside their season window", n)
    ] if n else []


def check_provenance(con) -> list[Finding]:
    """Requirement 6: every match must be attributable to a source and a run."""
    no_source = _scalar(
        con,
        """SELECT count(*) FROM matches m
           WHERE NOT EXISTS (SELECT 1 FROM match_source_ids s WHERE s.match_id = m.match_id)""",
    )
    no_run = _scalar(
        con,
        """SELECT count(*) FROM matches m
           WHERE m.ingestion_run_id IS NULL
              OR NOT EXISTS (SELECT 1 FROM ingestion_runs r
                             WHERE r.ingestion_run_id = m.ingestion_run_id)""",
    )
    out = []
    if no_source:
        out.append(Finding("match_without_source_id", BLOCKING,
                           f"{no_source} matches have no source identifier", no_source))
    if no_run:
        out.append(Finding("match_without_run", BLOCKING,
                           f"{no_run} matches have no valid ingestion run", no_run))
    return out


def check_cross_source_join(con) -> list[Finding]:
    """How far the cross-source join actually reaches.

    Severity depends on how many sources were actually ingested. A dataset
    built from ONE source is degraded, not invalid, and blocking on it would
    make the pipeline refuse to run precisely when a second feed is
    unavailable — which is when you most want it to keep running. Two or more
    sources that join nothing is a different matter: that is a broken match
    identity or a broken source-id bridge, and it must block.
    """
    rows = con.execute(
        "SELECT n_sources, count(*) FROM v_cross_source_matches GROUP BY n_sources ORDER BY 1"
    ).fetchall()
    single = sum(c for n, c in rows if (n or 0) <= 1)
    multi = sum(c for n, c in rows if (n or 0) > 1)
    n_sources = _scalar(con, "SELECT count(DISTINCT source) FROM match_source_ids")

    out = [
        Finding("cross_source_reach", INFO,
                f"{multi} matches corroborated by 2+ sources, {single} by a single source "
                f"({n_sources} source(s) ingested)", multi)
    ]
    if multi == 0 and single > 0:
        if n_sources >= 2:
            out.append(Finding("no_cross_source_join", BLOCKING,
                               f"{n_sources} sources ingested but nothing joined; match "
                               "identity or the source-id bridge is broken", single))
        else:
            out.append(Finding("single_source_dataset", WARNING,
                               "only one source ingested, so nothing is corroborated; "
                               "usable but not cross-checked", single))
    return out


def check_membership_consistency(con) -> list[Finding]:
    """Every team in a match must have membership for that competition-season."""
    n = _scalar(
        con,
        """SELECT count(*) FROM (
             SELECT home_team_id AS t, competition_id AS c, season_id AS s FROM matches
             UNION
             SELECT away_team_id, competition_id, season_id FROM matches) x
           WHERE NOT EXISTS (SELECT 1 FROM team_season_membership ms
                             WHERE ms.team_id = x.t AND ms.competition_id = x.c
                               AND ms.season_id = x.s)""",
    )
    return [
        Finding("missing_membership", BLOCKING,
                f"{n} team-season pairs appear in matches without membership", n)
    ] if n else []


def check_source_coverage_scope(con) -> list[Finding]:
    """Ingestion outside the declared coverage matrix is a configuration bug."""
    n = _scalar(
        con,
        """SELECT count(*) FROM ingestion_runs r
           WHERE r.competition_id IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM source_coverage sc
                             WHERE sc.source = r.source AND sc.competition_id = r.competition_id)""",
    )
    return [
        Finding("ingest_outside_coverage", BLOCKING,
                f"{n} ingestion runs targeted an undeclared source-competition pair", n)
    ] if n else []


QUALITY_CHECKS = (
    check_duplicate_matches,
    check_missing_results,
    check_result_before_kickoff,
    check_match_outside_season,
    check_provenance,
    check_cross_source_join,
    check_membership_consistency,
    check_source_coverage_scope,
)


def run_all_checks(con) -> list[Finding]:
    """Identity audit plus data-quality checks, in one pass."""
    findings = list(run_identity_audit(con))
    for check in QUALITY_CHECKS:
        findings.extend(check(con))
    return findings


#: Headline counts for the M1 audit report (requirement 13).
COUNT_QUERIES: dict[str, str] = {
    "competitions": "SELECT count(DISTINCT competition_id) FROM matches",
    "seasons": "SELECT count(DISTINCT season_id) FROM matches",
    "teams": "SELECT count(*) FROM teams",
    "aliases": "SELECT count(*) FROM team_aliases",
    "fuzzy_proposals_total": "SELECT count(*) FROM team_alias_proposals",
    "fuzzy_proposals_open": "SELECT count(*) FROM team_alias_proposals WHERE status='PROPOSED'",
    "overrides": "SELECT count(*) FROM team_identity_overrides",
    "matches": "SELECT count(*) FROM matches",
    "analytic_matches": "SELECT count(*) FROM v_analytic_matches",
    "match_results": "SELECT count(*) FROM match_results",
    "quarantined_matches": "SELECT count(*) FROM match_quarantine",
    "merged_matches": "SELECT count(*) FROM match_merges",
    "team_source_ids": "SELECT count(*) FROM team_source_ids",
    "match_source_ids": "SELECT count(*) FROM match_source_ids",
    "team_season_memberships": "SELECT count(*) FROM team_season_membership",
    "ingestion_runs": "SELECT count(*) FROM ingestion_runs",
}
