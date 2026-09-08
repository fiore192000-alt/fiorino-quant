"""
The M1 pipeline: bootstrap, ingest, rebuild, audit.

The rebuild guarantee is SEMANTIC: rebuilding from bronze yields the same
records, keys, values and relations in the same canonical order. It is not
byte equality — DuckDB's physical representation varies across versions and
builds, and promising byte equality would be a promise the storage engine
does not make.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fiorino.config.registries import (
    COMPETITIONS,
    SEASONS,
    SOURCE_COVERAGE,
    country_of,
    season_bounds,
)
from fiorino.data.db.migrate import migrate
from fiorino.data.identity.resolver import IdentityResolver
from fiorino.data.ingest.silver import TransformResult, transform_bronze
from fiorino.data.lake import list_bronze, read_bronze

__all__ = ["bootstrap_reference", "ingest_bronze", "rebuild_from_bronze", "canonical_snapshot"]


def bootstrap_reference(con, *, seasons=SEASONS, competitions=COMPETITIONS) -> None:
    """Load the reference dimensions. Idempotent."""
    migrate(con)
    for cid, (name, country, tier, is_cup) in competitions.items():
        con.execute(
            "INSERT INTO competitions VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            [cid, name, country, tier, is_cup],
        )
    for season in seasons:
        starts, ends = season_bounds(season)
        con.execute(
            "INSERT INTO seasons VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
            [season, starts, ends],
        )
        for cid in competitions:
            con.execute(
                "INSERT INTO competition_seasons VALUES (?, ?, NULL) ON CONFLICT DO NOTHING",
                [cid, season],
            )
    for source, comps in SOURCE_COVERAGE.items():
        for cid, xg in comps.items():
            if cid in competitions:
                con.execute(
                    "INSERT INTO source_coverage VALUES (?, ?, ?, NULL) ON CONFLICT DO NOTHING",
                    [source, cid, xg],
                )


def start_run(con, source, competition_id, season_id, *, bronze_path=None, code_version=None) -> str:
    run = "r_" + uuid.uuid4().hex[:10]
    con.execute(
        """INSERT INTO ingestion_runs
           (ingestion_run_id, source, competition_id, season_id, started_at,
            code_version, bronze_path, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'RUNNING')""",
        [run, source, competition_id, season_id, datetime.now(timezone.utc),
         code_version, str(bronze_path) if bronze_path else None],
    )
    return run


def finish_run(con, run_id, result: TransformResult, rows_read: int) -> None:
    con.execute(
        """UPDATE ingestion_runs
           SET finished_at = now(), status = 'DONE', rows_read = ?,
               rows_written = ?, rows_quarantined = ?
           WHERE ingestion_run_id = ?""",
        [rows_read, result.matches_written, result.quarantined, run_id],
    )


def ingest_bronze(
    con, lake_root, *, auto_register_unknown: bool = False, code_version: str | None = None
) -> TransformResult:
    """Promote every bronze partition into silver, one run per partition.

    Partitions are processed in canonical order so that first-writer-wins
    conflicts resolve identically on every rebuild.
    """
    if not list_bronze(lake_root):
        return TransformResult()

    resolver = IdentityResolver(con)
    countries = country_of()
    total = TransformResult()

    partitions = sorted(
        {(r["source"], r["competition"], r["season"]) for r in read_bronze(con, lake_root)}
    )
    for source, competition, season in partitions:
        rows = read_bronze(con, lake_root, source=source, competition_id=competition, season_id=season)
        run_id = start_run(con, source, competition, season, code_version=code_version)
        result = transform_bronze(
            con, rows, country_of=countries, ingestion_run_id=run_id,
            resolver=resolver, auto_register_unknown=auto_register_unknown,
        )
        finish_run(con, run_id, result, len(rows))
        total = total + result
    return total


def rebuild_from_bronze(con, lake_root, *, auto_register_unknown: bool = False) -> TransformResult:
    """Rebuild silver/gold from bronze on an empty database."""
    bootstrap_reference(con)
    return ingest_bronze(con, lake_root, auto_register_unknown=auto_register_unknown)


@dataclass(frozen=True)
class Snapshot:
    """A canonical, comparable projection of the analytic tables.

    Identity surrogates are deliberately excluded and replaced by their
    canonical names: team_id is randomly minted, so two semantically identical
    rebuilds legitimately differ on it. Comparing names verifies what actually
    matters — that the same real-world facts came out.
    """

    matches: tuple
    results: tuple
    teams: tuple
    memberships: tuple
    source_ids: tuple


def canonical_snapshot(con) -> Snapshot:
    def q(sql):
        return tuple(con.execute(sql).fetchall())

    return Snapshot(
        matches=q(
            """SELECT m.competition_id, m.season_id, m.match_date_utc, m.kickoff_utc,
                      h.canonical_name, a.canonical_name, m.neutral_venue, m.status
               FROM v_analytic_matches m
               JOIN teams h ON h.team_id = m.home_team_id
               JOIN teams a ON a.team_id = m.away_team_id
               ORDER BY 1,2,3,5,6"""
        ),
        results=q(
            """SELECT m.competition_id, m.season_id, m.match_date_utc,
                      h.canonical_name, a.canonical_name,
                      r.goals_home, r.goals_away, r.settled_at
               FROM match_results r
               JOIN v_analytic_matches m ON m.match_id = r.match_id
               JOIN teams h ON h.team_id = m.home_team_id
               JOIN teams a ON a.team_id = m.away_team_id
               ORDER BY 1,2,3,4,5"""
        ),
        teams=q("SELECT canonical_name, country FROM teams ORDER BY 1,2"),
        memberships=q(
            """SELECT t.canonical_name, ms.competition_id, ms.season_id
               FROM team_season_membership ms JOIN teams t ON t.team_id = ms.team_id
               ORDER BY 1,2,3"""
        ),
        source_ids=q(
            """SELECT si.source, si.source_id, h.canonical_name, a.canonical_name
               FROM match_source_ids si
               JOIN matches m ON m.match_id = si.match_id
               JOIN teams h ON h.team_id = m.home_team_id
               JOIN teams a ON a.team_id = m.away_team_id
               ORDER BY 1,2"""
        ),
    )
