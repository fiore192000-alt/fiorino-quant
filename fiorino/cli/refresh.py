"""
Scheduled refresh: fetch every covered source-competition-season into bronze.

Designed to run unattended in CI. Two properties matter:

* Bronze is immutable, so each run writes a NEW partition file keyed by run id.
  A refresh never rewrites history; it appends today's view of it.
* A source that fails is reported and skipped, not fatal. One league being
  briefly unavailable must not stop the other seven from updating.
"""

from __future__ import annotations

import argparse
import sys
import traceback
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from fiorino.config.registries import COMPETITIONS, all_seasons, current_season
from fiorino.data.db.connection import connect
from fiorino.data.ingest.sources.footballdata import FootballData
from fiorino.data.ingest.sources.openfootball import OpenFootball
from fiorino.data.lake import bronze_path, write_bronze

__all__ = ["refresh", "SOURCES"]

SOURCES = {"openfootball": OpenFootball, "footballdata": FootballData}


def refresh(
    lake_root, sources=("openfootball",), seasons=None, competitions=None, today=None
) -> dict:
    """Fetch into bronze. Returns a per-source summary.

    Defaults to the current season only: a daily job should not re-download a
    decade every morning. Pass `seasons=all_seasons()` for a backfill.
    """
    today = today or date.today()
    seasons = list(seasons or [current_season(today)])
    competitions = list(competitions or COMPETITIONS)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]

    con = connect()
    summary: dict[str, dict] = {}

    for source_name in sources:
        adapter = SOURCES[source_name]()
        stats = {"rows": 0, "partitions": 0, "skipped": [], "failed": []}
        for competition_id in competitions:
            if competition_id not in adapter.supports:
                stats["skipped"].append(f"{competition_id}: not covered")
                continue
            for season_id in seasons:
                try:
                    rows = adapter.fetch(competition_id, season_id)
                except Exception as exc:  # one league must not sink the rest
                    stats["failed"].append(f"{competition_id}/{season_id}: {exc}")
                    continue
                if not rows:
                    stats["skipped"].append(f"{competition_id}/{season_id}: empty")
                    continue
                target = bronze_path(lake_root, source_name, competition_id, season_id, run_id)
                if target.file.exists():
                    stats["skipped"].append(f"{competition_id}/{season_id}: already written")
                    continue
                write_bronze(con, [r.as_row() for r in rows], target)
                stats["rows"] += len(rows)
                stats["partitions"] += 1
        summary[source_name] = stats
    con.close()
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="fiorino-refresh")
    parser.add_argument("--lake", default="data/bronze")
    parser.add_argument("--sources", default="openfootball",
                        help="comma separated; footballdata needs network egress to the site")
    parser.add_argument("--backfill", action="store_true",
                        help="fetch every tracked season, not just the current one")
    args = parser.parse_args(argv)

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    unknown = [s for s in sources if s not in SOURCES]
    if unknown:
        print(f"unknown sources: {unknown}", file=sys.stderr)
        return 2

    seasons = all_seasons() if args.backfill else None
    try:
        summary = refresh(Path(args.lake), sources=sources, seasons=seasons)
    except Exception:
        traceback.print_exc()
        return 1

    failures = 0
    for name, stats in summary.items():
        print(f"{name}: {stats['rows']} rows in {stats['partitions']} partitions")
        for line in stats["skipped"]:
            print(f"  skip: {line}")
        for line in stats["failed"]:
            print(f"  FAIL: {line}")
            failures += 1
    # Partial success is still success: a single unavailable league is normal.
    return 1 if failures and not any(s["rows"] for s in summary.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
