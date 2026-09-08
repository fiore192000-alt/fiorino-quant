#!/usr/bin/env python3
"""
Out-of-sample validation of the M5 model layer.

Same shape as validate_backtest.py, and for the same reason: a model measured
on one league-season is an anecdote. This runs the walk-forward fit, the
multi-market pricing and the model-driven strategy over every dataset in the
validation set, and separates two questions that are easy to conflate:

  INVARIANTS   properties of the machinery. A prediction fitted on matches it
               is pricing, probabilities that do not sum to one, a handicap and
               a totals line that disagree about the same grid — each is a bug,
               independent of whether the model makes money.

  BEHAVIOUR    whether the model forecasts better than the de-vigged close, and
               what happens to a bankroll that acts on the difference. These
               are measurements, not requirements. The expected answer is that
               the market wins; the point of running it on ten datasets is to
               find out whether that holds everywhere or only in England.

The gap between the two is the whole reason this file exists. On PL 2017-18 the
model reported edges above 5% on a third of all priced selections while losing
to the close on both Brier and log-loss. Correct machinery, no edge: exactly the
failure mode a backtest without CLV would have sold as a discovery.

Not part of the test suite: it fetches from the network.

    python scripts/validate_models.py [--json out.json] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fiorino.backtest import (  # noqa: E402
    BacktestConfig,
    Frictions,
    ModelEdge,
    TakeSelection,
    compute_metrics,
    run_backtest,
)
from fiorino.clv.compute import compute_clv  # noqa: E402
from fiorino.core.capital import OversizePolicy  # noqa: E402
from fiorino.models.fitting import walk_forward  # noqa: E402
from scripts.validate_backtest import prepare  # noqa: E402
from scripts.validate_clv import DATASETS, fetch  # noqa: E402

#: Edge thresholds to backtest. The hypothesis this was built to test: a model
#: with a real edge should do BETTER at a higher threshold, because the
#: threshold selects; a model whose "edge" is its own miscalibration should do
#: worse, because the threshold then selects the fixtures it misprices hardest.
#:
#: Measured on ten datasets, the hypothesis does NOT hold per dataset — yield
#: decreases in 4/10, CLV in 4/10, and only the pooled means are monotone. The
#: thresholds stay in the report because the SPREAD is still informative, but
#: the shape is reported and not relied on. What separates the two cases
#: cleanly is the calibration comparison below, which is unanimous.
THRESHOLDS = (0.05, 0.15, 0.30)

PROB_TOLERANCE = 1e-9


# --------------------------------------------------------------------------
# Invariants
# --------------------------------------------------------------------------
def check_invariants(con) -> list[str]:
    """Structural properties of the model layer. Any violation is a bug."""
    problems = []

    # 1. R1, the point-in-time rule, where it is easiest to break: no fit may
    #    have been trained through an instant at or after the kickoff of a
    #    match it prices. This is the single check that separates a walk-forward
    #    from a look-ahead, and it is worth more than every metric below.
    leaks = con.execute(
        """SELECT count(*) FROM predictions p
           JOIN model_runs r ON r.model_run_id = p.model_run_id
           JOIN v_analytic_matches m ON m.match_id = p.match_id
           WHERE r.trained_through >= m.kickoff_utc"""
    ).fetchone()[0]
    if leaks:
        problems.append(f"{leaks} predictions were fitted through their own kickoff")

    # 2. A prediction must also not be dated after the match it prices.
    late = con.execute(
        """SELECT count(*) FROM predictions p
           JOIN v_analytic_matches m ON m.match_id = p.match_id
           WHERE p.as_of >= m.kickoff_utc"""
    ).fetchone()[0]
    if late:
        problems.append(f"{late} predictions carry an as_of at or after kickoff")

    # 3. The five settlement states partition the outcome space, so they sum
    #    to one. A grid that leaks probability off the edge shows up here.
    unnormalised = con.execute(
        f"""SELECT count(*) FROM predictions
            WHERE abs(prob_win + prob_half_win + prob_push
                      + prob_half_lose + prob_lose - 1.0) > {PROB_TOLERANCE * 1e3}"""
    ).fetchone()[0]
    if unnormalised:
        problems.append(f"{unnormalised} predictions do not sum to 1")

    negatives = con.execute(
        """SELECT count(*) FROM predictions
           WHERE least(prob_win, prob_half_win, prob_push,
                       prob_half_lose, prob_lose) < 0"""
    ).fetchone()[0]
    if negatives:
        problems.append(f"{negatives} predictions carry a negative probability")

    # 4. Multi-market coherence. Every market is priced from the SAME score
    #    grid, so they must agree. Two independent identities:
    #      1X2 must sum to one over its three selections, and
    #      OVER + UNDER on a half-goal total must sum to one.
    #    A disagreement means a market was priced from a different grid than it
    #    claims, which is exactly the bug that makes a multi-market book
    #    arbitrageable against itself.
    incoherent_1x2 = con.execute(
        """SELECT count(*) FROM (
             SELECT model_run_id, match_id, sum(prob_win) s
             FROM predictions WHERE market_type = 'ONE_X_TWO'
             GROUP BY model_run_id, match_id
             HAVING abs(s - 1.0) > 1e-6)"""
    ).fetchone()[0]
    if incoherent_1x2:
        problems.append(f"{incoherent_1x2} fixtures have 1X2 probabilities off 1")

    incoherent_ou = con.execute(
        """SELECT count(*) FROM (
             SELECT model_run_id, match_id, line, sum(prob_win) s, count(*) n
             FROM predictions
             WHERE market_type = 'TOTALS' AND abs(line * 2 - round(line * 2)) < 1e-9
               AND abs(line - floor(line)) > 0.4   -- half-goal lines only: no push
             GROUP BY model_run_id, match_id, line
             HAVING n = 2 AND abs(s - 1.0) > 1e-6)"""
    ).fetchone()[0]
    if incoherent_ou:
        problems.append(f"{incoherent_ou} half-goal totals lines do not sum to 1")

    # 5. Every prediction belongs to a recorded fit, and every fit records what
    #    it was trained on. A model_run without provenance cannot be replayed.
    orphans = con.execute(
        """SELECT count(*) FROM predictions p
           WHERE NOT EXISTS (SELECT 1 FROM model_runs r
                             WHERE r.model_run_id = p.model_run_id)"""
    ).fetchone()[0]
    if orphans:
        problems.append(f"{orphans} predictions have no model_run")

    unprovenanced = con.execute(
        """SELECT count(*) FROM model_runs
           WHERE trained_through IS NULL OR n_matches IS NULL OR params IS NULL"""
    ).fetchone()[0]
    if unprovenanced:
        problems.append(f"{unprovenanced} model runs lack provenance")

    return problems


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------
def calibration(con) -> dict | None:
    """Model vs de-vigged close on 1X2, using the fit the strategy would use.

    v_model_calibration groups by model_run_id, which double-counts fixtures
    covered by two overlapping horizons. A headline number has to pick one
    prediction per (match, selection) — the freshest fit, which is precisely
    what ModelEdge bets on.
    """
    row = con.execute(
        """WITH freshest AS (
               SELECT p.*, row_number() OVER (
                          PARTITION BY p.match_id, p.selection
                          ORDER BY r.trained_through DESC, p.model_run_id
                      ) AS rn
               FROM predictions p
               JOIN model_runs r ON r.model_run_id = p.model_run_id
               WHERE p.market_type = 'ONE_X_TWO'
           ),
           joined AS (
               SELECT f.prob_win AS model_p,
                      rm.closing_fair_prob AS market_p,
                      CASE WHEN f.selection = CASE
                             WHEN mr.goals_home > mr.goals_away THEN 'HOME'
                             WHEN mr.goals_away > mr.goals_home THEN 'AWAY'
                             ELSE 'DRAW' END THEN 1 ELSE 0 END AS won,
                      f.used_prior
               FROM freshest f
               JOIN match_results mr ON mr.match_id = f.match_id
               JOIN reference_market rm
                 ON rm.match_id = f.match_id AND rm.market_type = 'ONE_X_TWO'
                AND rm.selection = f.selection
               WHERE f.rn = 1 AND rm.closing_fair_prob BETWEEN 1e-6 AND 1 - 1e-6
           )
           SELECT count(*),
                  avg((model_p - won) ^ 2),
                  avg((market_p - won) ^ 2),
                  avg(-ln(CASE WHEN won = 1 THEN model_p ELSE 1 - model_p END)),
                  avg(-ln(CASE WHEN won = 1 THEN market_p ELSE 1 - market_p END)),
                  avg(used_prior::INTEGER)
           FROM joined"""
    ).fetchone()
    if not row or not row[0]:
        return None
    n, mb, kb, ml, kl = row[0], row[1], row[2], row[3], row[4]
    return {
        "n": n,
        "model_brier": mb,
        "market_brier": kb,
        "brier_edge": kb - mb,          # positive => the model is better
        "model_logloss": ml,
        "market_logloss": kl,
        "logloss_edge": kl - ml,
        "prior_fraction": row[5],
        "model_wins": (kb - mb) > 0 and (kl - ml) > 0,
    }


def edge_census(con) -> dict:
    """How many edges the model claims, and how large. Claims, not earnings."""
    row = con.execute(
        """SELECT count(*), sum((edge_ev > 0.05)::INTEGER),
                  sum((edge_ev > 0.30)::INTEGER), max(edge_ev)
           FROM v_model_vs_market
           WHERE market_type = 'ONE_X_TWO' AND capture_precision = 'PREMATCH'"""
    ).fetchone()
    n = row[0] or 0
    return {
        "n_priced": n,
        "n_edge_5pct": row[1] or 0,
        "n_edge_30pct": row[2] or 0,
        "max_edge": row[3],
        "fraction_edge_5pct": (row[1] or 0) / n if n else None,
    }


# --------------------------------------------------------------------------
# One dataset
# --------------------------------------------------------------------------
def run_dataset(label, competition_id, season_id, text) -> dict:
    con = prepare(competition_id, season_id, text)

    t0 = time.perf_counter()
    windows = walk_forward(
        con, competition_id=competition_id, season_id=season_id,
        step=timedelta(days=7), horizon=timedelta(days=8),
    )
    walk_seconds = time.perf_counter() - t0

    out = {
        "label": label,
        "n_fits": len(windows),
        "walk_seconds": round(walk_seconds, 1),
        "n_predictions": con.execute("SELECT count(*) FROM predictions").fetchone()[0],
        "n_prior_fixtures": sum(w.n_prior for w in windows),
        "library_fallbacks": con.execute(
            """SELECT coalesce(sum(CAST(json_extract(params, '$.library_fallbacks')
                                        AS INTEGER)), 0) FROM model_runs"""
        ).fetchone()[0],
        "invariant_failures": check_invariants(con),
        "calibration": calibration(con),
        "edges": edge_census(con),
        "strategies": {},
    }

    start = datetime(2000, 1, 1, tzinfo=timezone.utc)
    end = datetime(2030, 1, 1, tzinfo=timezone.utc)
    config = BacktestConfig(
        initial_bankroll=Decimal("1000"), stake_fraction=0.01, max_exposure=0.25,
        frictions=Frictions(), oversize_policy=OversizePolicy.SCALE_PRO_RATA,
    )

    # take_home is the control: a strategy with no opinion at all. If the model
    # cannot beat it, the fitting was decoration.
    strategies = [(f"model_edge_{int(t * 100)}", ModelEdge(min_edge=t)) for t in THRESHOLDS]
    strategies.append(("take_home", TakeSelection("HOME")))

    for name, strategy in strategies:
        result = run_backtest(con, strategy, config, start, end, code_version="validation")
        compute_clv(con, result.run_id)
        metrics = compute_metrics(con, result.run_id, bootstrap=800)
        out["strategies"][name] = {
            "n_bets": metrics.n_bets,
            "yield": metrics.yield_on_turnover,
            "growth": metrics.growth,
            "max_drawdown": metrics.max_drawdown,
            "clv_ev": metrics.mean_clv_ev,
            "clv_t": metrics.clv_t_stat,
            "yield_ci": [metrics.yield_ci_low, metrics.yield_ci_high],
            "verdict": metrics.verdict,
        }
    con.close()
    return out


# --------------------------------------------------------------------------
def _mono(series) -> str:
    """Does yield fall as the threshold rises? The miscalibration signature."""
    clean = [y for y in series if y is not None]
    if len(clean) < 2:
        return "n/a"
    return "decreasing" if all(b <= a for a, b in zip(clean, clean[1:])) else "mixed"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    datasets = DATASETS[: args.limit] if args.limit else DATASETS
    results = []
    for label, competition_id, season_id, url in datasets:
        try:
            text = fetch(url)
            results.append(run_dataset(label, competition_id, season_id, text))
        except Exception as exc:
            print(f"{label:16} FAILED: {exc}", file=sys.stderr)
            continue
        r = results[-1]
        flag = "INVARIANT FAIL" if r["invariant_failures"] else "ok"
        print(f"\n{r['label']:16} fits={r['n_fits']:3} preds={r['n_predictions']:6} "
              f"({r['walk_seconds']}s)  fallbacks={r['library_fallbacks']}  [{flag}]")
        c = r["calibration"]
        if c:
            print(f"    calibration n={c['n']:5}  "
                  f"Brier {c['model_brier']:.5f} vs {c['market_brier']:.5f} "
                  f"({c['brier_edge']:+.5f})  "
                  f"LogLoss {c['model_logloss']:.5f} vs {c['market_logloss']:.5f} "
                  f"({c['logloss_edge']:+.5f})  "
                  f"-> {'MODEL' if c['model_wins'] else 'MARKET'}")
        e = r["edges"]
        if e["n_priced"]:
            print(f"    claims edge>5% on {e['n_edge_5pct']}/{e['n_priced']} "
                  f"({e['fraction_edge_5pct']:.1%}), max {e['max_edge']:+.3f}")
        for name, s in r["strategies"].items():
            print(f"    {name:16} bets={s['n_bets']:4} yield={s['yield']:+.4f} "
                  f"growth={s['growth']:+.2%} DD={s['max_drawdown']:.1%} "
                  f"CLV={s['clv_ev']:+.4f} t={s['clv_t']:+6.1f}")
        for failure in r["invariant_failures"]:
            print(f"    !! {failure}")

    if not results:
        return 1

    print("\n" + "=" * 78)
    total_failures = sum(len(r["invariant_failures"]) for r in results)
    print(f"{len(results)} datasets, "
          f"{sum(r['n_fits'] for r in results)} fits, "
          f"{sum(r['n_predictions'] for r in results):,} predictions")
    print(f"  INVARIANT VIOLATIONS      : {total_failures}   "
          f"({'all clean' if total_failures == 0 else 'BUG'})")
    print(f"  library rho fallbacks      : {sum(r['library_fallbacks'] for r in results)}")

    cals = [r["calibration"] for r in results if r["calibration"]]
    if cals:
        wins = sum(1 for c in cals if c["model_wins"])
        print(f"\n  MODEL vs DE-VIGGED CLOSE (1X2)")
        print(f"    model beats market in {wins}/{len(cals)} datasets")
        print(f"    Brier edge   : mean {statistics.mean(c['brier_edge'] for c in cals):+.5f}  "
              f"[{min(c['brier_edge'] for c in cals):+.5f}, "
              f"{max(c['brier_edge'] for c in cals):+.5f}]")
        print(f"    LogLoss edge : mean {statistics.mean(c['logloss_edge'] for c in cals):+.5f}  "
              f"[{min(c['logloss_edge'] for c in cals):+.5f}, "
              f"{max(c['logloss_edge'] for c in cals):+.5f}]")
        fr = [c["prior_fraction"] for c in cals]
        print(f"    priced from league prior: mean {statistics.mean(fr):.1%}")

    names = [f"model_edge_{int(t * 100)}" for t in THRESHOLDS] + ["take_home"]
    for name in names:
        ys = [r["strategies"][name]["yield"] for r in results
              if r["strategies"].get(name, {}).get("yield") is not None]
        cs = [r["strategies"][name]["clv_ev"] for r in results
              if r["strategies"].get(name, {}).get("clv_ev") is not None]
        if not ys:
            continue
        print(f"\n  {name}")
        print(f"    yield  : mean {statistics.mean(ys):+.4f}  "
              f"[{min(ys):+.4f}, {max(ys):+.4f}]  "
              f"positive in {sum(1 for y in ys if y > 0)}/{len(ys)}")
        if cs:
            print(f"    CLV_ev : mean {statistics.mean(cs):+.4f}  "
                  f"[{min(cs):+.4f}, {max(cs):+.4f}]  "
                  f"positive in {sum(1 for c in cs if c > 0)}/{len(cs)}")

    # Reported, not relied on: see THRESHOLDS. Per dataset the shape is mostly
    # mixed, which is itself the finding — one season of yield cannot tell a
    # real edge from a miscalibration.
    print("\n  YIELD vs THRESHOLD (per dataset)")
    shapes = []
    for r in results:
        series = [r["strategies"].get(f"model_edge_{int(t * 100)}", {}).get("yield")
                  for t in THRESHOLDS]
        shape = _mono(series)
        shapes.append(shape)
        pretty = "  ".join("  n/a  " if y is None else f"{y:+.4f}" for y in series)
        print(f"    {r['label']:16} {pretty}   {shape}")
    print(f"    -> decreasing in {shapes.count('decreasing')}/{len(shapes)} datasets")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(results, indent=2, default=str))
        print(f"\nwritten {args.json}")
    return 0 if total_failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
