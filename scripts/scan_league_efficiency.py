#!/usr/bin/env python3
"""
League efficiency, measured — not searched for.

Tests the registered claim C-106, "minor leagues are less efficiently priced".
The question is deliberately NOT "where is the edge" but "where does the
closing line track reality least well". A market can be poorly calibrated and
still unbeatable; a market that is well calibrated is beatable by nobody, and
that is worth knowing before spending a season collecting data in it.

WHAT THIS CANNOT ANSWER
-----------------------
The datasets available here are ten league-seasons from seven TOP divisions.
Serie C, youth, women's and Scandinavian football are not among them, and those
are exactly the markets C-106 is about. So this measures the spread of
efficiency ACROSS MAJOR LEAGUES, which bounds the question without settling it:
if the top divisions already differ by more than noise, the hypothesis has a
mechanism; if they do not, the claim rests entirely on markets never observed.

    python scripts/scan_league_efficiency.py [--json out.json]

Not part of the test suite: it fetches from the network.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import random
import statistics as st
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fiorino.models.scoring import score_forecasts  # noqa: E402
from scripts.validate_backtest import prepare  # noqa: E402
from scripts.validate_clv import DATASETS, fetch  # noqa: E402

BOOTSTRAP = 1500
BANDS = ((0, .10), (.10, .20), (.20, .35), (.35, .55), (.55, .80), (.80, 1.01))


def collect(con, competition_id, precision):
    rows = con.execute(
        """
        SELECT m.match_id,
               max(f.fair_prob) FILTER (WHERE f.selection='HOME'),
               max(f.fair_prob) FILTER (WHERE f.selection='DRAW'),
               max(f.fair_prob) FILTER (WHERE f.selection='AWAY'),
               max(f.overround),
               max(CASE WHEN r.goals_home > r.goals_away THEN 0
                        WHEN r.goals_home = r.goals_away THEN 1 ELSE 2 END)
        FROM v_analytic_matches m
        JOIN match_results r ON r.match_id = m.match_id
        JOIN fair_probabilities f
          ON f.match_id = m.match_id AND f.market_type='ONE_X_TWO'
         AND f.capture_precision = ?
         AND f.bookmaker_id IN (SELECT bookmaker_id FROM bookmakers WHERE is_reference)
        WHERE (? IS NULL OR m.competition_id = ?)
        GROUP BY m.match_id
        """,
        [precision, competition_id, competition_id],
    ).fetchall()
    forecasts, outcomes, overrounds = [], [], []
    for _, h, d, a, ov, outcome in rows:
        if None in (h, d, a, outcome):
            continue
        forecasts.append((h, d, a))
        outcomes.append(outcome)
        if ov is not None:
            overrounds.append(ov)
    return forecasts, outcomes, overrounds


def calibration_error(forecasts, outcomes):
    """Mean absolute gap between price and realised frequency, by band.

    A single number for "how well does the price track reality". Weighted by
    band size so a band with nine selections cannot dominate.
    """
    rows = []
    for probs, outcome in zip(forecasts, outcomes):
        for k, p in enumerate(probs):
            rows.append((p, 1.0 if k == outcome else 0.0))
    total_n, weighted = 0, 0.0
    worst = 0.0
    for lo, hi in BANDS:
        band = [r for r in rows if lo <= r[0] < hi]
        if len(band) < 30:
            continue
        predicted = sum(r[0] for r in band) / len(band)
        realised = sum(r[1] for r in band) / len(band)
        gap = abs(predicted - realised)
        weighted += gap * len(band)
        total_n += len(band)
        worst = max(worst, gap)
    return (weighted / total_n if total_n else None), worst


def bootstrap_ci(forecasts, outcomes, metric, draws=BOOTSTRAP, seed=20260909):
    rng = random.Random(seed)
    n = len(outcomes)
    values = []
    for _ in range(draws):
        idx = [rng.randrange(n) for _ in range(n)]
        values.append(metric(score_forecasts([forecasts[i] for i in idx],
                                             [outcomes[i] for i in idx])))
    values.sort()
    return values[int(0.025 * draws)], values[int(0.975 * draws)]


def run_dataset(label, competition_id, season_id, text) -> dict:
    con = prepare(competition_id, season_id, text)
    close_f, close_o, overrounds = collect(con, competition_id, "CLOSING")
    pre_f, pre_o, _ = collect(con, competition_id, "PREMATCH")
    con.close()
    if len(close_o) < 100:
        raise RuntimeError(f"only {len(close_o)} usable matches")

    closing = score_forecasts(close_f, close_o)
    prematch = score_forecasts(pre_f, pre_o) if len(pre_o) == len(close_o) else None
    mean_gap, worst_gap = calibration_error(close_f, close_o)
    lo, hi = bootstrap_ci(close_f, close_o, lambda s: s.brier)

    return {
        "label": label,
        "competition_id": competition_id,
        "n": closing.n,
        "closing_brier": closing.brier,
        "closing_brier_ci": [lo, hi],
        "closing_logloss": closing.logloss,
        "closing_rps": closing.rps,
        "mean_calibration_gap": mean_gap,
        "worst_band_gap": worst_gap,
        "mean_overround": st.mean(overrounds) if overrounds else None,
        # How much the market itself learns between the two observations. A
        # market that learns a lot late is one where being early could matter.
        "prematch_to_close_brier_gain": (
            prematch.brier - closing.brier if prematch else None),
    }


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
        print(f"{r['label']:16} n={r['n']:4}  Brier {r['closing_brier']:.5f} "
              f"[{r['closing_brier_ci'][0]:.5f}, {r['closing_brier_ci'][1]:.5f}]  "
              f"scarto medio {r['mean_calibration_gap']:.4f}  "
              f"peggior banda {r['worst_band_gap']:.4f}  "
              f"margine {r['mean_overround']:.4f}")

    if not results:
        return 1

    print("\n" + "=" * 92)
    print("EFFICIENZA DELLA CHIUSURA, PER CAMPIONATO-STAGIONE")
    print(f"\n{'':16} {'Brier':>9} {'scarto cal.':>12} {'peggior banda':>14} "
          f"{'margine':>9} {'guadagno pre→close':>19}")
    for r in sorted(results, key=lambda x: -x["mean_calibration_gap"]):
        gain = r["prematch_to_close_brier_gain"]
        print(f"{r['label']:16} {r['closing_brier']:9.5f} "
              f"{r['mean_calibration_gap']:12.4f} {r['worst_band_gap']:14.4f} "
              f"{r['mean_overround']:9.4f} "
              f"{(f'{gain:+.5f}' if gain is not None else 'n/d'):>19}")

    gaps = [r["mean_calibration_gap"] for r in results]
    briers = [r["closing_brier"] for r in results]
    print(f"\n  scarto di calibrazione: media {st.mean(gaps):.4f}, "
          f"intervallo [{min(gaps):.4f}, {max(gaps):.4f}]")

    # The decisive question: is the spread between leagues bigger than the
    # uncertainty within one? If not, the ranking above is noise with an order.
    widths = [r["closing_brier_ci"][1] - r["closing_brier_ci"][0] for r in results]
    spread = max(briers) - min(briers)
    print(f"  dispersione del Brier fra campionati : {spread:.5f}")
    print(f"  ampiezza media del CI dentro un campionato : {st.mean(widths):.5f}")
    if spread < st.mean(widths):
        print("\n  -> LA DIFFERENZA FRA CAMPIONATI E PIU PICCOLA DELL'INCERTEZZA")
        print("     DENTRO UN SINGOLO CAMPIONATO. La classifica sopra e un")
        print("     ordinamento del rumore: nessuna di queste leghe e")
        print("     distinguibile dalle altre con questo campione.")
    else:
        print("\n  -> la dispersione supera l'incertezza interna: la differenza")
        print("     fra campionati e potenzialmente reale e va indagata.")

    print("\n  ATTENZIONE: sono dieci stagioni di SETTE PRIME DIVISIONI. Serie C,")
    print("  settore giovanile, calcio femminile e campionati scandinavi non ci")
    print("  sono, e sono esattamente i mercati di cui parla C-106. Questa misura")
    print("  delimita la domanda, non la chiude.")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(results, indent=2, default=str))
        print(f"\nscritto {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
