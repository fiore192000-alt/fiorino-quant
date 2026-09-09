#!/usr/bin/env python3
"""
How much is the market-microstructure channel worth, at most?

Of everything on the "new information" list — lineups, injuries, xG, rest,
congestion, weather — exactly one item is already in the warehouse: the price
path. Football-Data gives a prematch and a closing Pinnacle price, so the
movement between them is measurable today.

This script puts a CEILING on that whole channel, and the ceiling is what
decides whether a timestamped odds feed is worth building.

The argument
------------
Any signal derived from watching prices move — steam, drops, reverse line
movement, sharp-money detection — is a signal about where the price is GOING.
Its perfect version, the one no real system could beat, is the closing price
itself: the endpoint of every path, known only in hindsight.

So the forecasting gap between the PREMATCH price and the CLOSING price is an
upper bound on the entire channel. A system with a perfectly timestamped feed,
a perfect microstructure model and no execution cost could capture that gap and
no more. If the gap is small, the channel is small, and no feed pays for itself.

This measures nothing about tradability and does not claim to. It is a bound.

    python scripts/measure_market_channel.py [--json out.json]

Not part of the test suite: it fetches from the network.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fiorino.models.scoring import paired_bootstrap, score_forecasts  # noqa: E402
from scripts.validate_backtest import prepare  # noqa: E402
from scripts.validate_clv import DATASETS, fetch  # noqa: E402

BOOTSTRAP_DRAWS = 2000


def collect(con, competition_id):
    """Prematch and closing de-vigged probabilities for the same fixtures."""
    rows = con.execute(
        """
        SELECT m.match_id,
               max(pre.fair_prob) FILTER (WHERE pre.selection = 'HOME'),
               max(pre.fair_prob) FILTER (WHERE pre.selection = 'DRAW'),
               max(pre.fair_prob) FILTER (WHERE pre.selection = 'AWAY'),
               max(cl.fair_prob)  FILTER (WHERE cl.selection  = 'HOME'),
               max(cl.fair_prob)  FILTER (WHERE cl.selection  = 'DRAW'),
               max(cl.fair_prob)  FILTER (WHERE cl.selection  = 'AWAY'),
               max(CASE WHEN r.goals_home > r.goals_away THEN 0
                        WHEN r.goals_home = r.goals_away THEN 1 ELSE 2 END)
        FROM v_analytic_matches m
        JOIN match_results r ON r.match_id = m.match_id
        JOIN fair_probabilities pre
          ON pre.match_id = m.match_id AND pre.market_type = 'ONE_X_TWO'
         AND pre.capture_precision = 'PREMATCH'
         AND pre.bookmaker_id IN (SELECT bookmaker_id FROM bookmakers WHERE is_reference)
        JOIN fair_probabilities cl
          ON cl.match_id = m.match_id AND cl.market_type = 'ONE_X_TWO'
         AND cl.capture_precision = 'CLOSING' AND cl.selection = pre.selection
         AND cl.bookmaker_id = pre.bookmaker_id
        WHERE (? IS NULL OR m.competition_id = ?)
        GROUP BY m.match_id
        ORDER BY m.match_id
        """,
        [competition_id, competition_id],
    ).fetchall()

    pre, close, outcomes, moves = [], [], [], []
    for _, ph, pd_, pa, ch, cd, ca, outcome in rows:
        if None in (ph, pd_, pa, ch, cd, ca) or outcome is None:
            continue
        pre.append((ph, pd_, pa))
        close.append((ch, cd, ca))
        outcomes.append(outcome)
        moves.append(max(abs(ch - ph), abs(cd - pd_), abs(ca - pa)))
    return pre, close, outcomes, moves


def run_dataset(label, competition_id, season_id, text) -> dict:
    con = prepare(competition_id, season_id, text)
    pre, close, outcomes, moves = collect(con, competition_id)
    con.close()
    if len(outcomes) < 50:
        raise RuntimeError(f"only {len(outcomes)} usable fixtures")

    s_pre = score_forecasts(pre, outcomes)
    s_close = score_forecasts(close, outcomes)
    out = {
        "label": label,
        "n": len(outcomes),
        "prematch": {"brier": s_pre.brier, "logloss": s_pre.logloss, "rps": s_pre.rps},
        "closing": {"brier": s_close.brier, "logloss": s_close.logloss, "rps": s_close.rps},
        # How much the line actually moves, so a null gap can be told apart
        # from a line that simply never moved in this sample.
        "movement": {
            "median_max_abs": statistics.median(moves),
            "mean_max_abs": statistics.mean(moves),
            "fraction_moved_1pct": sum(1 for m in moves if m > 0.01) / len(moves),
        },
    }
    for name, metric in (("logloss", lambda s: s.logloss),
                         ("brier", lambda s: s.brier),
                         ("rps", lambda s: s.rps)):
        point, lo, hi = paired_bootstrap(pre, close, outcomes, metric,
                                         draws=BOOTSTRAP_DRAWS)
        # Negative = the close is better = the channel has something in it.
        out[f"{name}_gain"] = [point, lo, hi]
        out[f"{name}_significant"] = hi < 0
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    datasets = DATASETS[: args.limit] if args.limit else DATASETS
    results = []
    for label, competition_id, season_id, url in datasets:
        try:
            results.append(run_dataset(label, competition_id, season_id, fetch(url)))
        except Exception as exc:
            print(f"{label:16} FAILED: {exc}", file=sys.stderr)
            continue
        r = results[-1]
        g = r["logloss_gain"]
        print(f"{r['label']:16} n={r['n']:4}  "
              f"Brier {r['prematch']['brier']:.5f} -> {r['closing']['brier']:.5f}  "
              f"LogLoss {r['prematch']['logloss']:.5f} -> {r['closing']['logloss']:.5f}  "
              f"guadagno {g[0]:+.5f} [{g[1]:+.5f}, {g[2]:+.5f}] "
              f"{'SIGNIFICATIVO' if r['logloss_significant'] else '0 nel CI'}  "
              f"mosse>1% {r['movement']['fraction_moved_1pct']:.0%}")

    if not results:
        return 1

    print("\n" + "=" * 78)
    print(f"{len(results)} dataset, {sum(r['n'] for r in results)} partite\n")
    for name in ("brier", "logloss", "rps"):
        gains = [r[f"{name}_gain"][0] for r in results]
        sig = sum(1 for r in results if r[f"{name}_significant"])
        print(f"  {name:8} guadagno della chiusura sulla prematch: "
              f"medio {statistics.mean(gains):+.5f}  "
              f"[{min(gains):+.5f}, {max(gains):+.5f}]  "
              f"significativo in {sig}/{len(results)}")

    med = statistics.mean(r["movement"]["median_max_abs"] for r in results)
    frac = statistics.mean(r["movement"]["fraction_moved_1pct"] for r in results)
    print(f"\n  la linea si muove: spostamento mediano {med:.4f} di probabilita, "
          f"oltre 1 punto nel {frac:.0%} delle partite")
    print("\n  QUESTO E UN TETTO. Un sistema con feed timestampato perfetto,")
    print("  modello di microstruttura perfetto e costi zero cattura al massimo")
    print("  questo, e nient'altro, dall'intero canale dei movimenti di quota.")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(results, indent=2, default=str))
        print(f"\nscritto {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
