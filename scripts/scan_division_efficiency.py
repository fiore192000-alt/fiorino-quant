#!/usr/bin/env python3
"""
C-106, finally testable: are lower divisions priced less efficiently?

The claim has sat as UNTESTED because the ten league-seasons in this project
are all TOP divisions, and those turned out indistinguishable from one another.
The markets the hypothesis is actually about — second, third, fourth tiers —
were simply absent.

`xgabora/Club-Football-Match-Data-2000-2025` supplies them: 38 division codes,
211,067 matches carrying odds, free and reachable. Including England down to
the fifth tier (EC) and the Scottish lower divisions.

WHAT THE BENCHMARK IS, AND IS NOT
---------------------------------
`OddHome/Draw/Away` are **bet365 prematch** prices, not the de-vigged Pinnacle
CLOSING line this project usually measures against. That makes the absolute
numbers NOT comparable with the M5/M6 figures: a soft book's prematch line
carries a wider margin and is a weaker forecast by construction.

It does not weaken the comparison ACROSS divisions, which is the question:
same book, same collection convention, 38 markets. Whether bet365 prices the
fourth tier worse than the first is answerable exactly because the benchmark is
held constant.

No timestamps. This says nothing about market microstructure.

    curl -L -o matches.csv \
      https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data/main/data/Matches.csv
    python scripts/scan_division_efficiency.py --csv matches.csv [--json out.json]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import random
import statistics as st
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fiorino.odds.devig import devig  # noqa: E402

BANDS = ((0, .10), (.10, .20), (.20, .35), (.35, .55), (.55, .80), (.80, 1.01))
MIN_MATCHES = 800
BOOTSTRAP = 400

#: Tier assignment, from the Football-Data division codes. Single-division
#: countries are top tier by definition of what the source publishes.
LOWER = {"E1", "E2", "E3", "EC", "D2", "F2", "I2", "SP2", "SC1", "SC2", "SC3"}
#: Countries that publish BOTH a top and a lower division here. The tier
#: comparison across all 38 markets is partly a comparison of countries —
#: every LOWER division is European, while TOP includes Argentina, China,
#: Japan, Mexico and the USA. Pairing inside a country removes that.
PAIRS = {"England": ("E0", ["E1", "E2", "E3", "EC"]),
         "Scotland": ("SC0", ["SC1", "SC2", "SC3"]),
         "Germany": ("D1", ["D2"]),
         "France": ("F1", ["F2"]),
         "Italy": ("I1", ["I2"]),
         "Spain": ("SP1", ["SP2"])}

TIER_NAMES = {"E1": "England 2", "E2": "England 3", "E3": "England 4",
              "EC": "England 5", "D2": "Germany 2", "F2": "France 2",
              "I2": "Italy 2", "SP2": "Spain 2", "SC1": "Scotland 2",
              "SC2": "Scotland 3", "SC3": "Scotland 4"}


def load(path):
    """One row per match with a complete 1X2 price and a result."""
    out = []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            try:
                prices = [float(row["OddHome"]), float(row["OddDraw"]), float(row["OddAway"])]
            except (TypeError, ValueError):
                continue
            if any(p <= 1.0 for p in prices):
                continue
            result = row.get("FTResult")
            if result not in ("H", "D", "A"):
                continue
            out.append((row["Division"], prices, {"H": 0, "D": 1, "A": 2}[result]))
    return out


def prepare(rows):
    """De-vig once per row, and count what the guard refuses.

    fiorino.odds.devig raises on a market whose implied probabilities sum below
    one: that is an arbitrage or a corrupt row, not a normal market. Silently
    dropping those would hide a data-quality fact about this source, so they
    are counted and reported per division.
    """
    prepared, refused = [], 0
    for _, prices, outcome in rows:
        try:
            result = devig(["HOME", "DRAW", "AWAY"], prices, "SHIN")
        except ValueError:
            refused += 1
            continue
        prepared.append((tuple(result.fair_probs), result.overround, outcome))
    return prepared, refused


def score(prepared):
    """Brier per selection row (M5 convention) and the mean overround."""
    brier = 0.0
    for fair, _, outcome in prepared:
        for k, p in enumerate(fair):
            brier += (p - (1.0 if k == outcome else 0.0)) ** 2
    return (brier / (3 * len(prepared)),
            st.mean(o for _, o, _ in prepared),
            len(prepared))


def calibration_gap(prepared):
    points = []
    for fair, _, outcome in prepared:
        for k, p in enumerate(fair):
            points.append((p, 1.0 if k == outcome else 0.0))
    weighted, total, worst = 0.0, 0, 0.0
    for lo, hi in BANDS:
        band = [pt for pt in points if lo <= pt[0] < hi]
        if len(band) < 200:
            continue
        gap = abs(sum(p for p, _ in band) / len(band)
                  - sum(y for _, y in band) / len(band))
        weighted += gap * len(band)
        total += len(band)
        worst = max(worst, gap)
    return (weighted / total if total else None), worst


def skill(prepared):
    """Brier skill against the division's OWN base rate.

    Raw Brier is not comparable across divisions and using it as an efficiency
    measure is the trap this test exists to avoid. A league where results are
    closer to a coin flip scores a worse Brier no matter how well it is priced:
    the entropy of the outcome, not the quality of the pricing, moves the
    number. The climatological forecast — this division's own long-run H/D/A
    frequencies — carries exactly that entropy and nothing else, so the ratio
    is what the market adds ON TOP of knowing the division.

    Returns 1 - brier/brier_climatology. Higher is a better-informed market.

    The base rate is taken in-sample, which hands the climatological forecast a
    small unearned advantage and therefore makes the skill figure slightly
    conservative. At a few thousand matches per division it is worth about 3/n
    and cannot carry a difference of 0.045; it is noted because a reader is
    entitled to know which way the thumb is on the scale.
    """
    n = len(prepared)
    base = [0.0, 0.0, 0.0]
    for _, _, outcome in prepared:
        base[outcome] += 1.0 / n
    clim = 0.0
    for _, _, outcome in prepared:
        for k, p in enumerate(base):
            clim += (p - (1.0 if k == outcome else 0.0)) ** 2
    clim /= 3 * n
    return 1.0 - score(prepared)[0] / clim, clim


def permutation(top, low, key, draws=20000, seed=20260909):
    """Two-sided permutation p for mean(LOWER) - mean(TOP) on a per-division stat.

    38 divisions, not 38 independent matches: the unit of the C-106 claim is
    the market, so the test shuffles the tier LABEL across markets. A raw
    difference reported without this says nothing about whether eleven lower
    divisions differ from twenty-seven top ones by more than the assignment.
    """
    values = [r[key] for r in top] + [r[key] for r in low]
    n_low = len(low)
    observed = st.mean(values[len(top):]) - st.mean(values[:len(top)])
    rng = random.Random(seed)
    hits = 0
    for _ in range(draws):
        shuffled = values[:]
        rng.shuffle(shuffled)
        delta = st.mean(shuffled[:n_low]) - st.mean(shuffled[n_low:])
        if abs(delta) >= abs(observed) - 1e-12:
            hits += 1
    return observed, (hits + 1) / (draws + 1)


def ci(prepared, draws=BOOTSTRAP, seed=20260909):
    rng = random.Random(seed)
    n = len(prepared)
    values = []
    for _ in range(draws):
        sample = [prepared[rng.randrange(n)] for _ in range(n)]
        values.append(score(sample)[0])
    values.sort()
    return values[int(0.025 * draws)], values[int(0.975 * draws)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--json", default=None)
    parser.add_argument("--bootstrap", type=int, default=BOOTSTRAP)
    args = parser.parse_args()

    rows = load(args.csv)
    by_division: dict[str, list] = {}
    for row in rows:
        by_division.setdefault(row[0], []).append(row)
    print(f"{len(rows):,} partite con quote complete, {len(by_division)} divisioni\n")

    results = []
    for division, group in sorted(by_division.items()):
        if len(group) < MIN_MATCHES:
            continue
        prepared, refused = prepare(group)
        if len(prepared) < MIN_MATCHES:
            continue
        brier, overround, n = score(prepared)
        gap, worst = calibration_gap(prepared)
        lo, hi = ci(prepared, draws=args.bootstrap)
        skill_score, climatology = skill(prepared)
        results.append({
            "division": division, "tier": "LOWER" if division in LOWER else "TOP",
            "name": TIER_NAMES.get(division, division),
            "n": n, "brier": brier, "brier_ci": [lo, hi],
            "brier_climatology": climatology, "brier_skill": skill_score,
            "calibration_gap": gap, "worst_band_gap": worst,
            "mean_overround": overround,
            "refused_rows": refused,
            "refused_fraction": refused / len(group),
        })
        flag = f"  scartate {refused}" if refused else ""
        print(f"  {division:5} {results[-1]['tier']:6} n={n:6,}  Brier {brier:.5f} "
              f"[{lo:.5f}, {hi:.5f}]  skill {skill_score:+.4f}  scarto {gap:.4f}  "
              f"margine {overround:.4f}{flag}")

    top = [r for r in results if r["tier"] == "TOP"]
    low = [r for r in results if r["tier"] == "LOWER"]

    print("\n" + "=" * 88)
    print("C-106 — LE DIVISIONI INFERIORI SONO PREZZATE PEGGIO?\n")
    for label, group in (("prime divisioni", top), ("divisioni inferiori", low)):
        if not group:
            continue
        print(f"  {label:22} n={len(group):2} mercati, {sum(g['n'] for g in group):7,} partite")
        print(f"    Brier              media {st.mean(g['brier'] for g in group):.5f}  "
              f"[{min(g['brier'] for g in group):.5f}, {max(g['brier'] for g in group):.5f}]")
        print(f"    skill vs climatologia media {st.mean(g['brier_skill'] for g in group):+.4f}  "
              f"[{min(g['brier_skill'] for g in group):+.4f}, "
              f"{max(g['brier_skill'] for g in group):+.4f}]")
        print(f"    scarto calibrazione media {st.mean(g['calibration_gap'] for g in group):.4f}  "
              f"[{min(g['calibration_gap'] for g in group):.4f}, "
              f"{max(g['calibration_gap'] for g in group):.4f}]")
        print(f"    margine             media {st.mean(g['mean_overround'] for g in group):.4f}")

    summary = {}
    if top and low:
        widths = [r["brier_ci"][1] - r["brier_ci"][0] for r in results]
        print("\n  differenza inferiori - prime, con test di permutazione sull'etichetta:")
        for label, key in (("scarto di calibrazione", "calibration_gap"),
                           ("skill vs climatologia", "brier_skill"),
                           ("Brier grezzo         ", "brier"),
                           ("margine              ", "mean_overround")):
            delta, pval = permutation(top, low, key)
            summary[key] = {"delta_lower_minus_top": delta, "p_permutation": pval}
            verdict = "distinguibile" if pval < 0.05 else "NON distinguibile"
            print(f"    {label} : {delta:+.4f}   p={pval:.4f}   {verdict}")

        spread = max(r["brier"] for r in results) - min(r["brier"] for r in results)
        skill_spread = (max(r["brier_skill"] for r in results)
                        - min(r["brier_skill"] for r in results))
        summary["mean_brier_ci_width"] = st.mean(widths)
        summary["brier_spread"] = spread
        summary["brier_skill_spread"] = skill_spread
        print(f"\n  ampiezza media del CI del Brier dentro un mercato : {st.mean(widths):.5f}")
        print(f"  dispersione del Brier grezzo fra mercati         : {spread:.5f}")
        print(f"  dispersione dello skill fra mercati              : {skill_spread:.5f}")

        index = {r["division"]: r for r in results}
        paired = []
        print("\n  CONFRONTO APPAIATO DENTRO IL PAESE (stesso book, stesso paese):")
        print(f"    {'paese':10} {'skill 1a':>9} {'skill inf':>9} {'delta':>8} "
              f"{'scarto 1a':>9} {'scarto inf':>10} {'margine':>8}")
        for country, (top_code, low_codes) in sorted(PAIRS.items()):
            if top_code not in index:
                continue
            lows = [index[c] for c in low_codes if c in index]
            if not lows:
                continue
            t = index[top_code]
            d_skill = st.mean(g["brier_skill"] for g in lows) - t["brier_skill"]
            d_gap_c = st.mean(g["calibration_gap"] for g in lows) - t["calibration_gap"]
            d_ov_c = st.mean(g["mean_overround"] for g in lows) - t["mean_overround"]
            paired.append({"country": country, "top": top_code,
                           "lower": [g["division"] for g in lows],
                           "delta_skill": d_skill, "delta_calibration_gap": d_gap_c,
                           "delta_overround": d_ov_c})
            print(f"    {country:10} {t['brier_skill']:+9.4f} "
                  f"{st.mean(g['brier_skill'] for g in lows):+9.4f} {d_skill:+8.4f} "
                  f"{t['calibration_gap']:9.4f} "
                  f"{st.mean(g['calibration_gap'] for g in lows):10.4f} {d_ov_c:+8.4f}")
        summary["paired_within_country"] = paired
        if paired:
            n_neg = sum(1 for x in paired if x["delta_skill"] < 0)
            n_gap = sum(1 for x in paired if x["delta_calibration_gap"] > 0)
            summary["paired_skill_negative"] = [n_neg, len(paired)]
            summary["paired_gap_positive"] = [n_gap, len(paired)]
            print(f"\n    skill piu basso nella divisione inferiore : {n_neg}/{len(paired)} paesi")
            print(f"    scarto di calibrazione piu alto           : {n_gap}/{len(paired)} paesi")
            print("    (con 6 paesi, 6/6 nella stessa direzione ha p=0.031 sotto il segno)")

        gap_p = summary["calibration_gap"]["p_permutation"]
        skill_p = summary["brier_skill"]["p_permutation"]
        ov_p = summary["mean_overround"]["p_permutation"]
        print("\n  LETTURA. Il Brier grezzo delle divisioni inferiori e piu alto, ma il")
        print("  Brier grezzo non misura l'efficienza: misura anche quanto e incerto")
        print("  il campionato. Lo skill contro la climatologia toglie quell'entropia")
        print("  ed e la statistica su cui va letto C-106.")
        if gap_p >= 0.05 and skill_p >= 0.05:
            print("\n  -> C-106 NON e' sostenuta: ne lo scarto di calibrazione ne lo")
            print("     skill distinguono le divisioni inferiori dalle prime.")
            if ov_p < 0.05:
                print("     L'unica differenza che si distingue e' il margine, e va nella")
                print("     direzione sfavorevole: nelle divisioni inferiori si paga di piu.")
            else:
                print("     Neanche il margine le distingue.")
        else:
            print("\n  -> almeno una statistica distingue i due gruppi: vedere sopra quale.")

    total_refused = sum(r["refused_rows"] for r in results)
    if total_refused:
        worst = max(results, key=lambda r: r["refused_fraction"])
        print(f"\n  QUALITA DEL DATO: {total_refused:,} righe rifiutate dal de-vig "
              f"(somma implicita < 1: arbitraggio o riga corrotta).")
        print(f"  Peggior mercato: {worst['division']} con {worst['refused_fraction']:.2%}. "
              f"Contate, non nascoste.")

    print("\n  NOTA: il benchmark e la quota PREMATCH di bet365, non la chiusura")
    print("  Pinnacle de-viggata. I numeri assoluti NON sono confrontabili con M5/M6.")
    print("  Il confronto FRA divisioni resta valido: stesso book, stessa convenzione.")
    print("  Nessun timestamp: non dice nulla sulla microstruttura.")

    if args.json:
        payload = {
            "source": "xgabora/Club-Football-Match-Data-2000-2025",
            "benchmark": "bet365 prematch 1X2, de-vig SHIN",
            "timestamps": None,
            "divisions": results,
            "summary": summary,
        }
        pathlib.Path(args.json).write_text(json.dumps(payload, indent=2, default=str))
        print(f"\nscritto {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
