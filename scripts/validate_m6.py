#!/usr/bin/env python3
"""
M6 — does the model add information to the market?

Runs the full ablation on every dataset in the validation set:

    MARKET          the de-vigged reference price, alone
    MODEL           the walk-forward Dixon-Coles fit, alone
    MARKET + MODEL  the two pooled, with a weight fitted only on settled matches

twice over, against two different market sources:

    INFORMATION   market = the CLOSING price. Evaluated, never bet: the close
                  is not knowable before kickoff. This answers the scientific
                  question against the hardest benchmark there is.

    DEPLOYABLE    market = the PREMATCH price. Knowable at the decision
                  instant, so this arm is also BET and its CLV measured
                  against the close.

Why they are separate is the single most important design decision in M6, and
it is worth restating where it will be read: CLV is measured against the
closing line, so a forecast built FROM the closing line shows positive CLV by
construction. That is M4's clairvoyant oracle, and it would arrive here looking
like a discovery. Nothing in the deployable path reads a closing price.

Not part of the test suite: it fetches from the network.

    python scripts/validate_m6.py [--json out.json] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fiorino.backtest import (  # noqa: E402
    BacktestConfig,
    Frictions,
    ModelEdge,
    compute_metrics,
    run_backtest,
)
from fiorino.clv.compute import compute_clv  # noqa: E402
from fiorino.core.capital import OversizePolicy  # noqa: E402
from fiorino.models.fitting import walk_forward  # noqa: E402
from fiorino.models.incremental import (  # noqa: E402
    ENSEMBLE_ARM,
    MARKET_ARM,
    build_arms,
    walk_forward_ensemble,
)
from fiorino.models.scoring import paired_bootstrap, score_forecasts  # noqa: E402
from scripts.validate_backtest import prepare  # noqa: E402
from scripts.validate_clv import DATASETS, fetch  # noqa: E402

EXPERIMENTS = ("information", "deployable")
BOOTSTRAP_DRAWS = 1500

#: Two thresholds, because they answer different halves of one question.
#: At 5% a well-calibrated arm almost never fires — the market arm places ten
#: bets on a season, which is not a sample. At 2% every arm has one. Using only
#: the loose threshold would flatter the model; only the tight one would leave
#: the market arm unmeasured.
BET_THRESHOLDS = (0.02, 0.05)


def _score_arms(arms, weights_by_boundary):
    """Score MARKET, MODEL and MARKET+MODEL on the fixtures every arm covers.

    The pooled forecast for a fixture uses the weight from the LAST boundary
    that precedes its kickoff — the weight a forecaster would actually have
    held, not the season's final one.
    """
    boundaries = sorted(weights_by_boundary)
    scored = []
    for arm in arms:
        if arm.outcome is None:
            continue
        applicable = [b for b in boundaries if b < arm.kickoff_utc]
        if not applicable:
            continue
        scored.append((arm, weights_by_boundary[applicable[-1]]))
    if not scored:
        return None

    from fiorino.models.ensemble import pool

    outcomes = [a.outcome for a, _ in scored]
    market = [a.market for a, _ in scored]
    model = [a.model for a, _ in scored]
    blended = [pool(a.model, a.market, w) for a, w in scored]

    out = {"n": len(outcomes), "n_available": sum(1 for a in arms if a.outcome is not None),
           "arms": {}}
    for name, forecasts in (("MARKET", market), ("MODEL", model),
                            ("MARKET+MODEL", blended)):
        s = score_forecasts(forecasts, outcomes)
        entry = {"n": s.n, "brier": s.brier, "logloss": s.logloss,
                 "logloss_selection": s.logloss_selection, "rps": s.rps}
        if name != "MARKET":
            for metric_name, metric in (("logloss", lambda x: x.logloss),
                                        ("brier", lambda x: x.brier),
                                        ("rps", lambda x: x.rps)):
                point, lo, hi = paired_bootstrap(
                    market, forecasts, outcomes, metric, draws=BOOTSTRAP_DRAWS
                )
                entry[f"{metric_name}_vs_market"] = [point, lo, hi]
                # The acceptance rule, applied here rather than left to the
                # reader: an interval containing zero is not evidence.
                entry[f"{metric_name}_beats_market"] = hi < 0
        out["arms"][name] = entry
    return out


def check_acceptance(con, result) -> list[str]:
    """The M6 gates. Any entry returned is a failed gate, not a warning."""
    problems = []

    # Gate 1 — PIT. Inherited from M5 and re-checked, because M6 writes new
    # rows into the same tables.
    leaks = con.execute(
        """SELECT count(*) FROM predictions p
           JOIN model_runs r ON r.model_run_id = p.model_run_id
           JOIN v_analytic_matches m ON m.match_id = p.match_id
           WHERE r.trained_through >= m.kickoff_utc"""
    ).fetchone()[0]
    if leaks:
        problems.append(f"{leaks} predictions fitted through their own kickoff")

    # The one new parameter, audited against the data it recorded consuming.
    peeking = con.execute("SELECT count(*) FROM v_weight_leakage").fetchone()[0]
    if peeking:
        problems.append(f"{peeking} ensemble weights trained past their boundary")

    # No weight may have been fitted on a match it then forecast.
    self_fitted = con.execute(
        """SELECT count(*) FROM ensemble_weights w
           JOIN model_runs r
             ON r.trained_through = w.trained_through AND r.model_name = ?
           JOIN predictions p ON p.model_run_id = r.model_run_id
           JOIN v_analytic_matches m ON m.match_id = p.match_id
           WHERE m.kickoff_utc <= w.train_max_settled_at""",
        [ENSEMBLE_ARM],
    ).fetchone()[0]
    if self_fitted:
        problems.append(f"{self_fitted} pooled forecasts covered a training match")

    # The deployable path must never have touched a closing price.
    from_close = con.execute(
        """SELECT count(*) FROM ensemble_weights
           WHERE experiment = 'deployable' AND market_source <> 'PREMATCH'"""
    ).fetchone()[0]
    if from_close:
        problems.append(f"{from_close} deployable weights were fitted on closing prices")

    # An arm scored on a different sample than the arm it is compared with is
    # a comparison between samples.
    for experiment in EXPERIMENTS:
        scores = result.get(experiment, {}).get("scores")
        if not scores:
            continue
        sizes = {name: arm["n"] for name, arm in scores["arms"].items()}
        if len(set(sizes.values())) > 1:
            problems.append(f"{experiment}: arms scored on different samples {sizes}")

    return problems


def run_dataset(label, competition_id, season_id, text) -> dict:
    con = prepare(competition_id, season_id, text)

    # M5's walk-forward first: M6 reads the predictions it wrote rather than
    # refitting, so both experiments score the forecasts the model made.
    walk_forward(con, competition_id=competition_id, season_id=season_id,
                 step=timedelta(days=7), horizon=timedelta(days=8))

    out = {"label": label}
    for experiment in EXPERIMENTS:
        steps = walk_forward_ensemble(
            con, experiment=experiment, competition_id=competition_id,
            season_id=season_id,
        )
        arms = build_arms(con, experiment, competition_id)
        weights = {s["boundary"]: s["weight"] for s in steps}
        out[experiment] = {
            "n_steps": len(steps),
            "weights": [s["weight"] for s in steps],
            "weight_mean": statistics.mean(s["weight"] for s in steps) if steps else None,
            "weight_max": max((s["weight"] for s in steps), default=None),
            "unconstrained_mean": (
                statistics.mean(s["unconstrained"] for s in steps) if steps else None
            ),
            "scores": _score_arms(arms, weights) if steps else None,
        }

    # Only the deployable arms are bet. Same engine, same config, three arms.
    start = datetime(2000, 1, 1, tzinfo=timezone.utc)
    end = datetime(2030, 1, 1, tzinfo=timezone.utc)
    config = BacktestConfig(
        initial_bankroll=Decimal("1000"), stake_fraction=0.01, max_exposure=0.25,
        frictions=Frictions(), oversize_policy=OversizePolicy.SCALE_PRO_RATA,
    )
    out["betting"] = {}
    for threshold in BET_THRESHOLDS:
      for arm, model_name in (("MARKET", MARKET_ARM),
                              ("MODEL", "dixon_coles"),
                              ("MARKET+MODEL", ENSEMBLE_ARM)):
        strategy = ModelEdge(min_edge=threshold, model_name=model_name)
        result = run_backtest(con, strategy, config, start, end, code_version="m6")
        compute_clv(con, result.run_id)
        metrics = compute_metrics(con, result.run_id, bootstrap=800)
        out["betting"][f"{arm}@{int(threshold * 100)}"] = {
            "n_settled": metrics.n_settled,
            "n_bets": metrics.n_bets,
            "yield": metrics.yield_on_turnover,
            "yield_ci": [metrics.yield_ci_low, metrics.yield_ci_high],
            "clv_ev": metrics.mean_clv_ev,
            "clv_price": metrics.mean_clv_price,
            "clv_t": metrics.clv_t_stat,
            "beat_close_rate": metrics.beat_close_rate,
            "growth": metrics.growth,
            "max_drawdown": metrics.max_drawdown,
            "verdict": metrics.verdict,
        }

    out["gate_failures"] = check_acceptance(con, out)
    con.close()
    return out


def _fmt_ci(triple) -> str:
    if not triple:
        return "—"
    point, lo, hi = triple
    verdict = "SI" if hi < 0 else ("no" if lo > 0 else "0 nel CI")
    return f"{point:+.5f} [{lo:+.5f}, {hi:+.5f}] {verdict}"


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
        print(f"\n{'=' * 78}\n{r['label']}"
              f"{'   [GATE FAIL]' if r['gate_failures'] else ''}")
        for experiment in EXPERIMENTS:
            e = r[experiment]
            if not e["scores"]:
                print(f"  {experiment}: nessun passo")
                continue
            print(f"  {experiment.upper()}  ({e['n_steps']} pesi, "
                  f"w medio {e['weight_mean']:.4f}, max {e['weight_max']:.4f}, "
                  f"non vincolato {e['unconstrained_mean']:+.4f})")
            print(f"    campione {e['scores']['n']}/{e['scores']['n_available']} "
                  f"partite regolate (le prime settimane non hanno ancora un peso)")
            for name, a in e["scores"]["arms"].items():
                print(f"    {name:14} n={a['n']:4} Brier {a['brier']:.5f}  "
                      f"LogLoss {a['logloss']:.5f}  RPS {a['rps']:.5f}  "
                      f"[LogLoss M5 {a['logloss_selection']:.5f}]")
            for name in ("MODEL", "MARKET+MODEL"):
                a = e["scores"]["arms"][name]
                print(f"      {name:12} vs MARKET  LogLoss "
                      f"{_fmt_ci(a.get('logloss_vs_market'))}")
        print("  BETTING (solo deployable, CLV contro la chiusura)")
        for name, b in r["betting"].items():
            clv = "   n/d " if b["clv_ev"] is None else f"{b['clv_ev']:+.4f}"
            tstat = "  n/d " if b["clv_t"] is None else f"{b['clv_t']:+6.1f}"
            beat = " n/d " if b["beat_close_rate"] is None else f"{b['beat_close_rate']:.3f}"
            thin = "  <- campione insufficiente" if b["n_settled"] < 30 else ""
            print(f"    {name:17} bets={b['n_bets']:4} yield={b['yield']:+.4f} "
                  f"CLV={clv} t={tstat} beat_close={beat}{thin}")
        for failure in r["gate_failures"]:
            print(f"    !! {failure}")

    if not results:
        return 1

    print("\n" + "=" * 78)
    total_failures = sum(len(r["gate_failures"]) for r in results)
    print(f"{len(results)} dataset")
    print(f"  GATE FAILURES : {total_failures}  "
          f"({'tutti puliti' if total_failures == 0 else 'BUG'})")

    for experiment in EXPERIMENTS:
        usable = [r for r in results if r[experiment]["scores"]]
        if not usable:
            continue
        print(f"\n  {experiment.upper()}")
        ws = [r[experiment]["weight_mean"] for r in usable]
        us = [r[experiment]["unconstrained_mean"] for r in usable]
        print(f"    peso medio del modello : {statistics.mean(ws):.4f}  "
              f"[{min(ws):.4f}, {max(ws):.4f}]")
        print(f"    non vincolato          : {statistics.mean(us):+.4f}  "
              f"[{min(us):+.4f}, {max(us):+.4f}]")
        for name in ("MODEL", "MARKET+MODEL"):
            beats = sum(1 for r in usable
                        if r[experiment]["scores"]["arms"][name].get("logloss_beats_market"))
            diffs = [r[experiment]["scores"]["arms"][name]["logloss_vs_market"][0]
                     for r in usable]
            print(f"    {name:12} batte MARKET su LogLoss in "
                  f"{beats}/{len(usable)} dataset "
                  f"(differenza media {statistics.mean(diffs):+.5f})")

    print("\n  BETTING")
    arms = [f"{a}@{int(t * 100)}" for t in BET_THRESHOLDS
            for a in ("MARKET", "MODEL", "MARKET+MODEL")]
    for arm in arms:
        usable = [r for r in results if r["betting"][arm]["n_settled"] >= 30
                  and r["betting"][arm]["clv_ev"] is not None]
        cs = [r["betting"][arm]["clv_ev"] for r in usable]
        ys = [r["betting"][arm]["yield"] for r in usable]
        if not cs:
            print(f"    {arm:17} nessun dataset con almeno 30 scommesse regolate")
            continue
        print(f"    {arm:17} CLV medio {statistics.mean(cs):+.4f}  "
              f"positivo in {sum(1 for c in cs if c > 0)}/{len(cs)}   "
              f"yield medio {statistics.mean(ys):+.4f}  "
              f"positivo in {sum(1 for y in ys if y > 0)}/{len(ys)}")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(results, indent=2, default=str))
        print(f"\nscritto {args.json}")
    return 0 if total_failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
