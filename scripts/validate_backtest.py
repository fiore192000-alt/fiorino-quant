#!/usr/bin/env python3
"""
Out-of-sample validation of the M4 engine.

Runs the backtest over every dataset in the CLV validation set and checks two
different things:

  INVARIANTS   structural properties that must hold on EVERY run, regardless of
               how the strategy performed. A single violation is a bug.

  BEHAVIOUR    what the strategies did. Naive strategies should lose; the
               clairvoyant oracle should win. These are statistical
               expectations, not invariants — a naive strategy profiting on one
               season is luck, and the report says so rather than hiding it.

Not part of the test suite: it fetches from the network.

    python scripts/validate_backtest.py [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fiorino.backtest import (  # noqa: E402
    BacktestConfig,
    Frictions,
    TakeFavourite,
    TakeSelection,
    TakeValueVsClose,
    compute_metrics,
    run_backtest,
)
from fiorino.clv.compute import compute_clv  # noqa: E402
from fiorino.core.capital import OversizePolicy  # noqa: E402
from fiorino.data.db.connection import connect  # noqa: E402
from fiorino.data.db.migrate import migrate  # noqa: E402
from fiorino.data.identity.resolver import IdentityResolver  # noqa: E402
from fiorino.data.ingest.sources.footballdata import FootballData  # noqa: E402
from fiorino.data.lake import bronze_path, write_bronze  # noqa: E402
from fiorino.data.pipeline import bootstrap_reference, ingest_bronze  # noqa: E402
from scripts.validate_clv import DATASETS, fetch  # noqa: E402


def prepare(competition_id, season_id, text):
    """Ingest one league-season, adjudicating look-alike club names."""
    con = connect()
    migrate(con)
    bootstrap_reference(con)
    root = pathlib.Path(tempfile.mkdtemp()) / "lake"
    rows = FootballData().parse(text, competition_id, season_id)
    write_bronze(con, [r.as_row() for r in rows],
                 bronze_path(root, "footballdata", competition_id, season_id, "val"))
    ingest_bronze(con, root, auto_register_unknown=True)
    for _ in range(6):
        open_props = con.execute(
            "SELECT proposal_id FROM team_alias_proposals WHERE status='PROPOSED'"
        ).fetchall()
        if not open_props:
            break
        resolver = IdentityResolver(con)
        for (pid,) in open_props:
            resolver.reject_proposal(pid, "validation", "distinct club")
        con.execute("DELETE FROM match_quarantine")
        ingest_bronze(con, root, auto_register_unknown=True)
    return con


def check_invariants(con, run_id, initial_bankroll) -> list[str]:
    """Structural properties. Any violation is a bug, not bad luck."""
    problems = []

    # 1. Every bet in a cohort was sized against the same equity snapshot.
    offenders = con.execute(
        """SELECT count(*) FROM (
             SELECT cohort_id, count(DISTINCT stake) d, count(*) n FROM bets
             WHERE run_id = ? AND cohort_id IS NOT NULL
             GROUP BY cohort_id HAVING n > 1 AND d > 1)""", [run_id]
    ).fetchone()[0]
    if offenders:
        problems.append(f"{offenders} cohorts have members with different stakes")

    # 2. A cohort never staked more than it had.
    breaches = con.execute(
        "SELECT count(*) FROM cohorts WHERE run_id = ? AND total_staked > available_open + 0.01",
        [run_id],
    ).fetchone()[0]
    if breaches:
        problems.append(f"{breaches} cohorts staked more than was available")

    # 3. Equity never went negative.
    negative = con.execute(
        "SELECT count(*) FROM equity_curve WHERE run_id = ? AND equity < 0", [run_id]
    ).fetchone()[0]
    if negative:
        problems.append(f"equity went negative at {negative} points")

    # 4. Every placed bet was settled.
    unsettled = con.execute(
        """SELECT count(*) FROM bets b
           WHERE b.run_id = ? AND b.stake IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM bet_settlements s WHERE s.bet_id = b.bet_id)""",
        [run_id],
    ).fetchone()[0]
    if unsettled:
        problems.append(f"{unsettled} bets were never settled")

    # 5. Books balance: final equity == initial + sum(pnl).
    pnl = con.execute(
        """SELECT coalesce(sum(s.pnl), 0) FROM bets b
           JOIN bet_settlements s ON s.bet_id = b.bet_id WHERE b.run_id = ?""", [run_id]
    ).fetchone()[0]
    final = con.execute(
        "SELECT equity FROM equity_curve WHERE run_id = ? ORDER BY ts DESC LIMIT 1", [run_id]
    ).fetchone()
    if final is not None:
        expected = Decimal(str(initial_bankroll)) + Decimal(str(pnl))
        if abs(Decimal(str(final[0])) - expected) > Decimal("0.01"):
            problems.append(f"books do not balance: equity {final[0]} vs expected {expected}")

    # 6. No bet claims an instant it cannot know.
    fabricated = con.execute(
        """SELECT count(*) FROM bets WHERE run_id = ?
           AND price_precision <> 'TIMESTAMPED' AND placed_at IS NOT NULL
           AND price_precision NOT IN ('PREMATCH', 'CLOSING', 'OPENING')""", [run_id]
    ).fetchone()[0]
    if fabricated:
        problems.append(f"{fabricated} bets carry a fabricated timestamp")

    return problems


def run_dataset(label, competition_id, season_id, text) -> dict:
    con = prepare(competition_id, season_id, text)
    start = datetime(2000, 1, 1, tzinfo=timezone.utc)
    end = datetime(2030, 1, 1, tzinfo=timezone.utc)
    config = BacktestConfig(
        initial_bankroll=Decimal("1000"), stake_fraction=0.01, max_exposure=0.25,
        frictions=Frictions(), oversize_policy=OversizePolicy.SCALE_PRO_RATA,
    )

    out = {"label": label, "strategies": {}, "invariant_failures": []}
    for strategy in (TakeSelection("HOME"), TakeFavourite(), TakeValueVsClose(min_edge=0.05)):
        result = run_backtest(con, strategy, config, start, end, code_version="validation")
        compute_clv(con, result.run_id)
        metrics = compute_metrics(con, result.run_id, bootstrap=800)
        problems = check_invariants(con, result.run_id, config.initial_bankroll)
        if problems:
            out["invariant_failures"].extend(f"{strategy.name}: {p}" for p in problems)
        out["strategies"][strategy.name] = {
            "n_bets": metrics.n_bets,
            "n_settled": metrics.n_settled,
            "turnover": metrics.turnover,
            "yield": metrics.yield_on_turnover,
            "growth": metrics.growth,
            "max_drawdown": metrics.max_drawdown,
            "clv_ev": metrics.mean_clv_ev,
            "clv_t": metrics.clv_t_stat,
            "yield_ci": [metrics.yield_ci_low, metrics.yield_ci_high],
            "verdict": metrics.verdict,
        }
    n_cohorts, biggest = con.execute(
        "SELECT count(*), max(n_bets) FROM cohorts"
    ).fetchone()
    out["n_cohorts"] = n_cohorts
    out["biggest_cohort"] = biggest
    con.close()
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    results = []
    for label, competition_id, season_id, url in DATASETS:
        try:
            text = fetch(url)
            results.append(run_dataset(label, competition_id, season_id, text))
        except Exception as exc:
            print(f"{label:16} FAILED: {exc}", file=sys.stderr)
            continue
        r = results[-1]
        flag = "INVARIANT FAIL" if r["invariant_failures"] else "ok"
        print(f"\n{r['label']:16} cohorts={r['n_cohorts']:3} biggest={r['biggest_cohort']:2}  [{flag}]")
        for name, s in r["strategies"].items():
            print(f"    {name:20} bets={s['n_bets']:4} yield={s['yield']:+.4f} "
                  f"growth={s['growth']:+.2%} DD={s['max_drawdown']:.1%} "
                  f"CLV={s['clv_ev']:+.4f} t={s['clv_t']:+6.1f}")
        for failure in r["invariant_failures"]:
            print(f"    !! {failure}")

    if not results:
        return 1

    print("\n" + "=" * 78)
    total_failures = sum(len(r["invariant_failures"]) for r in results)
    print(f"{len(results)} datasets")
    print(f"  INVARIANT VIOLATIONS      : {total_failures}   "
          f"({'all clean' if total_failures == 0 else 'BUG'})")
    print(f"  largest cohort seen       : {max(r['biggest_cohort'] or 0 for r in results)} bets")

    for name in ("take_home", "take_favourite", "oracle_beats_close"):
        ys = [r["strategies"][name]["yield"] for r in results if name in r["strategies"]]
        cs = [r["strategies"][name]["clv_ev"] for r in results
              if r["strategies"].get(name, {}).get("clv_ev") is not None]
        print(f"\n  {name}")
        print(f"    yield  : mean {statistics.mean(ys):+.4f}  "
              f"[{min(ys):+.4f}, {max(ys):+.4f}]  positive in {sum(1 for y in ys if y > 0)}/{len(ys)}")
        if cs:
            print(f"    CLV_ev : mean {statistics.mean(cs):+.4f}  "
                  f"[{min(cs):+.4f}, {max(cs):+.4f}]  positive in {sum(1 for c in cs if c > 0)}/{len(cs)}")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(results, indent=2, default=str))
        print(f"\nwritten {args.json}")
    return 0 if total_failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
