"""
Command entry points.

    python -m fiorino.cli.main audit --db path.duckdb --out report.md

Deliberately thin: every command is a few lines over the library, so the
behaviour under test is the behaviour that runs.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from fiorino.config.storage import bronze_root, manifest_root, warehouse_root
from fiorino.data.db.connection import connect
from fiorino.data.db.migrate import migrate
from fiorino.data.lake.manifest import (
    build_manifest,
    ledger_path_for,
    list_versions,
    load_manifest,
    read_head,
    save_manifest,
    verify_integrity,
    write_head,
)
from fiorino.data.pipeline import (
    bootstrap_reference,
    ingest_bronze,
    logical_digest,
    rebuild_from_bronze,
    rebuild_from_manifest,
)
from fiorino.data.identity.ledger import export_ledger, import_ledger, ledger_digest
from fiorino.data.quality import generate_report, render_markdown

#: The identity ledger lives in the repository, not the data root: it is a
#: small, human-authored decision log, versioned with the code that reads it.
DEFAULT_LEDGER = Path("configs/identity/ledger.json")


def cmd_bootstrap(args) -> int:
    con = connect(args.db)
    applied = migrate(con)
    bootstrap_reference(con)
    print(f"migrations applied: {applied or 'none (already current)'}")
    return 0


def cmd_ingest(args) -> int:
    con = connect(args.db)
    bootstrap_reference(con)
    lake = Path(args.lake or bronze_root(args.data_root))
    result = ingest_bronze(con, lake, code_version=args.code_version,
                           auto_register_unknown=args.auto_register)
    print(f"matches={result.matches_written} results={result.results_written} "
          f"quarantined={result.quarantined} proposals={result.proposals}")
    return 0


def cmd_rebuild(args) -> int:
    lake = Path(args.lake or bronze_root(args.data_root))
    with _fresh_warehouse(args.db) as con:
        migrate(con)
        if args.ledger and Path(args.ledger).exists():
            import_ledger(con, args.ledger)
        result = rebuild_from_bronze(con, lake, auto_register_unknown=args.auto_register)
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


@contextmanager
def _fresh_warehouse(db_path):
    """Build into a temporary file, then swap it into place atomically.

    A rebuild must start from nothing: appending to the existing warehouse
    accumulates rows across runs and stops being a rebuild at all. Building
    aside and swapping also means a failed rebuild leaves the working
    warehouse untouched rather than half-destroyed.
    """
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_suffix(target.suffix + ".building")
    for stale in (staging, Path(str(staging) + ".wal")):
        stale.unlink(missing_ok=True)

    con = connect(staging)
    try:
        yield con
        con.close()
        for suffix in ("", ".wal"):
            Path(str(target) + suffix).unlink(missing_ok=True)
        staging.replace(target)
    except Exception:
        con.close()
        staging.unlink(missing_ok=True)
        raise


def _rebuild(con, bronze, manifest, auto_register, ledger=None):
    """Migrate, load the identity decisions, then rebuild from bronze.

    The ledger goes in FIRST. Rebuilding without it would re-derive identity
    from scratch and produce a different dataset from the same bronze.
    """
    migrate(con)
    if ledger and Path(ledger).exists():
        import_ledger(con, ledger)
    return rebuild_from_manifest(con, bronze, manifest, auto_register_unknown=auto_register)


def cmd_snapshot(args) -> int:
    """Cut a new dataset version from the current bronze, and prove it builds.

    A version is published only if the rebuild succeeds and the audit has no
    blocking findings. A dataset that cannot be built is not a dataset.
    """
    bronze = Path(args.lake or bronze_root(args.data_root))
    manifests = Path(manifest_root(args.data_root))

    ledger = Path(args.ledger)
    parent = read_head(manifests)
    identity = ledger_digest(path=ledger) if ledger.exists() else None
    manifest = build_manifest(bronze, parent_version=parent,
                              code_version=args.code_version, note=args.note,
                              identity_digest=identity)

    if parent == manifest.dataset_version:
        print(f"no change: bronze still resolves to {manifest.dataset_version}")
        return 0

    with _fresh_warehouse(args.db) as con:
        _rebuild(con, bronze, manifest, args.auto_register, ledger)
        report = generate_report(con, code_version=args.code_version)
        digest = logical_digest(con)
        # Any identity minted during this build is a decision, and decisions
        # are inputs: write them back so the next rebuild reproduces this
        # dataset rather than re-deriving a different one.
        export_ledger(con, ledger)

    manifest = replace(
        manifest,
        logical_digest=digest,
        audit_status="PASS" if report.passed else "FAIL",
        n_blocking=len(report.blocking),
    )

    if not report.passed and not args.allow_failing_audit:
        print(f"AUDIT FAILED with {len(report.blocking)} blocking findings; "
              f"version {manifest.dataset_version} NOT published", file=sys.stderr)
        for finding in report.blocking:
            print(f"  - {finding.check_name}: {finding.detail}", file=sys.stderr)
        return 1

    save_manifest(manifest, manifests)
    # Freeze BOTH inputs. Bronze is immutable on its own; the ledger is not,
    # so a copy is kept per version or rollback cannot restore this dataset.
    shutil.copyfile(ledger, ledger_path_for(manifest.dataset_version, manifests))
    write_head(manifest.dataset_version, manifests)
    print(f"published {manifest.dataset_version}")
    print(f"  parent  {parent or '(none)'}")
    print(f"  files   {len(manifest.files)}  ({manifest.total_bytes / 1e6:.1f} MB)")
    print(f"  sources {', '.join(manifest.sources)}")
    print(f"  logical  {digest}")
    print(f"  identity {manifest.identity_digest}")
    print(f"  audit    {manifest.audit_status}")
    return 0


def cmd_rollback(args) -> int:
    """Move HEAD to an earlier version and rebuild exactly its inputs."""
    manifests = Path(manifest_root(args.data_root))
    bronze = Path(args.lake or bronze_root(args.data_root))

    manifest = load_manifest(args.to, manifests)
    problems = verify_integrity(manifest, bronze)
    if problems:
        print(f"cannot roll back: bronze no longer matches {args.to}", file=sys.stderr)
        for problem in problems[:10]:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    # Restore the identity decisions this version was built with. Without
    # this, replaying old bronze under today's adjudications yields a dataset
    # that matches neither version.
    frozen = ledger_path_for(args.to, manifests)
    if frozen.exists():
        shutil.copyfile(frozen, args.ledger)
    elif manifest.identity_digest:
        print(f"no frozen ledger for {args.to}; cannot restore its identity inputs",
              file=sys.stderr)
        return 1

    with _fresh_warehouse(args.db) as con:
        _rebuild(con, bronze, manifest, args.auto_register, args.ledger)
        digest = logical_digest(con)

    if manifest.logical_digest and digest != manifest.logical_digest:
        print(f"rebuild does NOT reproduce {args.to}", file=sys.stderr)
        print(f"  recorded {manifest.logical_digest}\n  rebuilt  {digest}", file=sys.stderr)
        return 1

    write_head(args.to, manifests)
    print(f"HEAD -> {args.to}")
    print(f"  logical digest {digest} matches the recorded value")
    print(f"  identity ledger restored from {frozen.name}"
          if frozen.exists() else "  no identity ledger to restore")
    return 0


def cmd_verify(args) -> int:
    """Prove a version's bronze is intact and still rebuilds to the same facts."""
    manifests = Path(manifest_root(args.data_root))
    bronze = Path(args.lake or bronze_root(args.data_root))
    version = args.version or read_head(manifests)
    if not version:
        print("no version to verify", file=sys.stderr)
        return 1

    manifest = load_manifest(version, manifests)
    problems = verify_integrity(manifest, bronze)
    print(f"{version}: {len(manifest.files)} files, integrity "
          f"{'OK' if not problems else 'FAILED'}")
    for problem in problems[:10]:
        print(f"  - {problem}")
    if problems:
        return 1

    frozen = ledger_path_for(version, manifests)
    ledger_for_verify = frozen if frozen.exists() else Path(args.ledger)
    with _fresh_warehouse(args.db) as con:
        _rebuild(con, bronze, manifest, args.auto_register, ledger_for_verify)
        digest = logical_digest(con)
    if manifest.logical_digest is None:
        print(f"  logical digest {digest} (none recorded to compare against)")
        return 0
    match = digest == manifest.logical_digest
    print(f"  logical digest {'MATCHES' if match else 'DIFFERS'}: {digest}")
    if not match:
        print(f"  recorded: {manifest.logical_digest}")
    return 0 if match else 1


def cmd_clv(args) -> int:
    """Score the bet ledger against the reference close and print the summary."""
    from fiorino.clv.compute import compute_clv
    from fiorino.clv import replay as replay_module

    con = connect(args.db)
    if args.replay:
        n = getattr(replay_module, f"take_{args.replay}")(con)
        print(f"replayed {n} bets ({args.replay})")
    result = compute_clv(con, args.run)
    print(f"scored {result.scored}, excluded {result.excluded} "
          f"(no close {result.no_reference_close}, line mismatch {result.line_not_matched}, "
          f"no fair prob {result.no_fair_probability})")
    rows = con.execute(
        """SELECT run_id, competition_id, season_id, market_type, n_bets,
                  round(mean_clv_ev, 5), round(beat_close_rate, 3), round(clv_t_stat, 2)
           FROM v_clv_summary ORDER BY run_id, competition_id, season_id"""
    ).fetchall()
    if not rows:
        print("nothing scored yet")
        return 0
    print(f"\n{'run':22} {'comp':9} {'season':11} {'market':14} {'n':>6} "
          f"{'CLV_ev':>9} {'beat':>6} {'t':>7}")
    for r in rows:
        print(f"{r[0][:22]:22} {r[1] or '':9} {r[2] or '':11} {r[3]:14} {r[4]:6} "
              f"{r[5]:>+9} {r[6]:>6} {r[7]:>7}")
    return 0


def cmd_versions(args) -> int:
    manifests = Path(manifest_root(args.data_root))
    head = read_head(manifests)
    versions = list_versions(manifests)
    if not versions:
        print("no dataset versions published yet")
        return 0
    for version in versions:
        manifest = load_manifest(version, manifests)
        marker = "*" if version == head else " "
        print(f"{marker} {version}  {manifest.created_at}  "
              f"{len(manifest.files):4} files  {manifest.total_bytes / 1e6:7.1f} MB  "
              f"audit={manifest.audit_status or '?'}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="fiorino")
    parser.add_argument("--db", default=None,
                        help="warehouse path; defaults under the data root")
    parser.add_argument("--data-root", default=None,
                        help=f"overrides ${{{'FIORINO_DATA_ROOT'}}}")
    parser.add_argument("--lake", default=None, help="bronze root; defaults under the data root")
    parser.add_argument("--code-version", default=None)
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER),
                        help="identity decision log; lives in the repository")
    parser.add_argument("--auto-register", action="store_true",
                        help="mint canonical teams for names with no candidate (seeding only)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("bootstrap").set_defaults(func=cmd_bootstrap)
    sub.add_parser("ingest").set_defaults(func=cmd_ingest)
    sub.add_parser("rebuild").set_defaults(func=cmd_rebuild)
    p = sub.add_parser("audit"); p.add_argument("--out", default=None); p.set_defaults(func=cmd_audit)

    p = sub.add_parser("snapshot", help="publish a new dataset version")
    p.add_argument("--note", default=None)
    p.add_argument("--allow-failing-audit", action="store_true")
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("rollback", help="move HEAD to an earlier version")
    p.add_argument("--to", required=True)
    p.set_defaults(func=cmd_rollback)

    p = sub.add_parser("verify", help="check integrity and rebuild equivalence")
    p.add_argument("--version", default=None)
    p.set_defaults(func=cmd_verify)

    sub.add_parser("versions").set_defaults(func=cmd_versions)

    p = sub.add_parser("clv", help="score bets against the reference closing line")
    p.add_argument("--run", default=None, help="limit to one run_id")
    p.add_argument("--replay", default=None, choices=["prematch", "closing"],
                   help="populate the ledger with a replay instrument first")
    p.set_defaults(func=cmd_clv)

    args = parser.parse_args(argv)
    if args.db is None:
        warehouse = Path(warehouse_root(args.data_root))
        warehouse.mkdir(parents=True, exist_ok=True)
        args.db = str(warehouse / "fiorino.duckdb")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
