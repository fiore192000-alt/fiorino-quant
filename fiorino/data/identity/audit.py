"""
Identity audit — the guards that run on every ingestion.

Each check returns findings rather than raising, so one run reports every
problem instead of stopping at the first. The caller decides what is blocking.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Finding", "run_identity_audit", "BLOCKING", "WARNING", "INFO"]

BLOCKING, WARNING, INFO = "BLOCKING", "WARNING", "INFO"


@dataclass(frozen=True)
class Finding:
    check_name: str
    severity: str
    detail: str
    n_affected: int = 0
    entity: str | None = None


def _rows(con, sql, params=None):
    return con.execute(sql, params or []).fetchall()


def check_alias_collisions(con) -> list[Finding]:
    """One alias bound to two different teams within a source and country."""
    rows = _rows(
        con,
        """SELECT alias_raw, source, country, count(DISTINCT team_id) AS n
           FROM team_aliases WHERE status = 'APPROVED'
           GROUP BY alias_raw, source, country HAVING n > 1""",
    )
    return [
        Finding("alias_collision", BLOCKING,
                f"alias {a!r} ({s}/{c}) maps to {n} teams", n, f"{s}:{a}")
        for a, s, c, n in rows
    ]


def check_homonyms(con) -> list[Finding]:
    """Two distinct teams sharing a normalised name in one country.

    Not automatically wrong — but it is the shape of a bad merge waiting to
    happen, so it must be adjudicated rather than tolerated.
    """
    rows = _rows(
        con,
        """SELECT alias_normalized, country, count(DISTINCT team_id) AS n,
                  string_agg(DISTINCT team_id, ',') AS ids
           FROM team_aliases WHERE status = 'APPROVED'
           GROUP BY alias_normalized, country HAVING n > 1""",
    )
    return [
        Finding("homonym", BLOCKING,
                f"normalised name {name!r} in {c} maps to {n} teams ({ids})", n, name)
        for name, c, n, ids in rows
    ]


def check_open_proposals(con) -> list[Finding]:
    """Fuzzy proposals nobody has adjudicated."""
    rows = _rows(
        con,
        """SELECT count(*), count(DISTINCT alias_raw)
           FROM team_alias_proposals WHERE status = 'PROPOSED'""",
    )
    total, distinct = rows[0]
    if not total:
        return []
    return [
        Finding("open_fuzzy_proposal", BLOCKING,
                f"{total} fuzzy proposals covering {distinct} names await a decision; "
                f"matches using them are quarantined", total)
    ]


def check_orphan_teams(con) -> list[Finding]:
    rows = _rows(
        con,
        """SELECT t.team_id, t.canonical_name FROM teams t
           LEFT JOIN team_aliases a ON a.team_id = t.team_id
           WHERE a.team_id IS NULL""",
    )
    return [
        Finding("orphan_team", WARNING, f"team {tid} ({name}) has no alias", 1, tid)
        for tid, name in rows
    ]


def check_quarantined_matches(con) -> list[Finding]:
    rows = _rows(con, "SELECT count(*), count(DISTINCT source) FROM match_quarantine")
    total, sources = rows[0]
    if not total:
        return []
    return [
        Finding("quarantined_match", BLOCKING,
                f"{total} matches from {sources} source(s) excluded for unapproved identity",
                total)
    ]


def check_fuzzy_never_became_alias(con) -> list[Finding]:
    """Rule 9, verified rather than assumed."""
    rows = _rows(
        con, "SELECT count(*) FROM team_aliases WHERE match_method = 'FUZZY'"
    )
    n = rows[0][0]
    if not n:
        return []
    return [
        Finding("fuzzy_leaked_into_aliases", BLOCKING,
                f"{n} aliases carry match_method FUZZY; rule 9 has been violated", n)
    ]


def check_analytic_matches_are_approved(con) -> list[Finding]:
    """No analytic match may reference a team with an unapproved identity."""
    rows = _rows(
        con,
        """SELECT count(*) FROM matches m
           WHERE EXISTS (SELECT 1 FROM team_aliases a
                         WHERE a.team_id IN (m.home_team_id, m.away_team_id)
                           AND a.status <> 'APPROVED')""",
    )
    n = rows[0][0]
    if not n:
        return []
    return [
        Finding("unapproved_identity_in_matches", BLOCKING,
                f"{n} matches reference a team with an unapproved alias", n)
    ]


IDENTITY_CHECKS = (
    check_alias_collisions,
    check_homonyms,
    check_open_proposals,
    check_orphan_teams,
    check_quarantined_matches,
    check_fuzzy_never_became_alias,
    check_analytic_matches_are_approved,
)


def run_identity_audit(con) -> list[Finding]:
    findings: list[Finding] = []
    for check in IDENTITY_CHECKS:
        findings.extend(check(con))
    return findings
