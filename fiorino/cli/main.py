"""
Command entry points.

    python -m fiorino.cli.main audit --db path.duckdb --out report.md

Deliberately thin: every command is a few lines over the library, so the
behaviour under test is the behaviour that runs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fiorino.data.db.connection import connect
from fiorino.data.db.migrate import migrate
from fiorino.data.pipeline import bootstrap_reference, ingest_bronze, rebuild_from_bronze
from fiorino.data.quality import generate_report, render_markdown


def cmd_bootstrap(args) -> int:
    con = connect(args.db)
    applied = migrate(con)
    bootstrap_reference(con)
    print(f"migrations applied: {applied or 'none (already current)'}")
    return 0


def cmd_ingest(args) -> int:
    con = connect(args.db)
    bootstrap_reference(con)
    result = ingest_bronze(con, args.lake, code_version=args.code_version)
    print(f"matches={result.matches_written} results={result.results_written} "
          f"quarantined={result.quarantined} proposals={result.proposals}")
    return 0


def cmd_rebuild(args) -> int:
    con = connect(args.db)
    result = rebuild_from_bronze(con, args.lake)
    print(f"rebuilt: matches={result.matches_written} quarantined={result.quarantined}")
    return 0


def cmd_audit(args) -> int:
    con = connect(args.db, read_only=False)
    report = generate_report(con, code_version=args.code_version)
    text = render_markdown(report)
    if args.out:
        Path(args.out).write_text(text)
        print(f"written {args.out}")
    else:
        print(text)
    # Non-zero on a failed audit so CI can gate on it.
    return 0 if report.passed else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="fiorino")
    parser.add_argument("--db", default="fiorino.duckdb")
    parser.add_argument("--code-version", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("bootstrap").set_defaults(func=cmd_bootstrap)
    p = sub.add_parser("ingest"); p.add_argument("--lake", required=True); p.set_defaults(func=cmd_ingest)
    p = sub.add_parser("rebuild"); p.add_argument("--lake", required=True); p.set_defaults(func=cmd_rebuild)
    p = sub.add_parser("audit"); p.add_argument("--out", default=None); p.set_defaults(func=cmd_audit)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
