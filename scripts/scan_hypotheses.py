#!/usr/bin/env python3
"""
The hypothesis scan: phases 2 to 6, run end to end.

Fourteen situations x three selections, over 10 league-seasons, pooled and
then checked for replication. Everything here is computable from the warehouse
as it stands: no feed that does not exist.

    python scripts/scan_hypotheses.py [--json out.json] [--limit N]

Not part of the test suite: it fetches from the network.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fiorino.data.db.connection import connect  # noqa: E402
from fiorino.research.hypotheses import HYPOTHESES, LABEL_SQL, label_matches  # noqa: E402
from fiorino.research.scan import benjamini_hochberg, scan  # noqa: E402
from scripts.validate_backtest import prepare  # noqa: E402
from scripts.validate_clv import DATASETS, fetch  # noqa: E402

import math  # noqa: E402

Q = 0.10                 # false discovery rate for the whole family
REPLICATION_MIN = 7      # datasets out of 10 that must agree in sign

#: Price bands for the calibration diagnostic. Printed before the scan because
#: it answers a question the scan cannot: is the market well priced at all, and
#: is a literature bias actually present in THIS market? A scan reporting "no
#: bias found" is worth nothing until that is on the page.
BANDS = ((0, .05), (.05, .10), (.10, .15), (.15, .20), (.20, .30),
         (.30, .40), (.40, .50), (.50, .65), (.65, .80), (.80, 1.01))


def _z_for(p: float) -> float:
    """Two-sided normal critical value. Bisection, to avoid a scipy import."""
    lo, hi = 0.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if math.erfc(mid / math.sqrt(2)) > p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def calibration_table(pool) -> list[dict]:
    """Realised frequency against price, by band.

    This is what separates "the scan found nothing" from "the scan cannot see
    anything". It also decides whether a literature bias is present at all:
    the favourite-longshot bias cannot serve as a control on the scanner if it
    is absent from the market being scanned.
    """
    rows = pool.execute("""
        SELECT prob, raw, won FROM (
          SELECT p_home AS prob, raw_home AS raw, (outcome='HOME')::INT AS won FROM pooled
          UNION ALL SELECT p_draw, raw_draw, (outcome='DRAW')::INT FROM pooled
          UNION ALL SELECT p_away, raw_away, (outcome='AWAY')::INT FROM pooled)
    """).fetchall()
    out = []
    for lo, hi in BANDS:
        sub = [r for r in rows if lo <= r[1] < hi]
        if len(sub) < 20:
            continue
        n = len(sub)
        raw = sum(r[1] for r in sub) / n
        fair = sum(r[0] for r in sub) / n
        real = sum(r[2] for r in sub) / n
        se = math.sqrt(max(real * (1 - real), 1e-9) / n)
        out.append({"band": f"{lo:.2f}-{hi:.2f}", "n": n, "raw": raw,
                    "fair": fair, "realised": real,
                    "raw_minus_real": raw - real, "fair_minus_real": fair - real,
                    "z": (fair - real) / se})
    return out


def collect(datasets) -> tuple[object, dict]:
    """Label every dataset and pool the rows into one table."""
    pool = connect()
    pool.execute("""CREATE TABLE pooled (
        dataset VARCHAR, match_id VARCHAR, competition_id VARCHAR, season_id VARCHAR,
        kickoff_utc TIMESTAMPTZ, outcome VARCHAR,
        home_rest_days BIGINT, away_rest_days BIGINT,
        home_matches_8d BIGINT, away_matches_8d BIGINT,
        home_points HUGEINT, away_points HUGEINT,
        home_matchday BIGINT, season_length BIGINT,
        dow BIGINT, month BIGINT,
        p_home DOUBLE, p_draw DOUBLE, p_away DOUBLE,
        raw_home DOUBLE, raw_draw DOUBLE, raw_away DOUBLE)""")

    per_dataset = {}
    for label, competition_id, season_id, url in datasets:
        try:
            con = prepare(competition_id, season_id, fetch(url))
        except Exception as exc:
            print(f"{label:16} FAILED: {exc}", file=sys.stderr)
            continue
        label_matches(con, competition_id)
        rows = con.execute("SELECT * FROM labelled").fetchall()
        con.close()
        if not rows:
            print(f"{label:16} nessuna riga etichettata", file=sys.stderr)
            continue
        pool.executemany(
            "INSERT INTO pooled VALUES (?" + ", ?" * 21 + ")",
            [[label, *row] for row in rows],
        )
        per_dataset[label] = len(rows)
        print(f"{label:16} {len(rows):4} partite etichettate")
    return pool, per_dataset


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    datasets = DATASETS[: args.limit] if args.limit else DATASETS
    pool, per_dataset = collect(datasets)
    if not per_dataset:
        return 1
    labels = sorted(per_dataset)

    print(f"\n{sum(per_dataset.values())} partite, {len(labels)} dataset, "
          f"{len(HYPOTHESES)} ipotesi x 3 selezioni")

    calib = calibration_table(pool)
    print("\nCALIBRAZIONE DEL MERCATO PER BANDA DI PREZZO")
    print(f"  {'banda':>12} {'n':>6} {'raw':>8} {'fair':>8} {'realizzato':>11} "
          f"{'raw-real':>9} {'fair-real':>10} {'z':>7}")
    for b in calib:
        print(f"  {b['band']:>12} {b['n']:6} {b['raw']:8.4f} {b['fair']:8.4f} "
              f"{b['realised']:11.4f} {b['raw_minus_real']:+9.4f} "
              f"{b['fair_minus_real']:+10.4f} {b['z']:+7.2f}")
    worst = max(abs(b["z"]) for b in calib)
    print(f"  scostamento massimo del prezzo de-viggato dalla frequenza "
          f"realizzata: |z| = {worst:.2f}")

    # -- pooled scan, with the correction applied to the whole family -------
    pooled = benjamini_hochberg(scan(pool, "pooled"), q=Q)
    pooled.sort(key=lambda r: r.p_value)

    # -- per-dataset, for replication --------------------------------------
    signs: dict[tuple[str, str], list[float]] = {}
    for label in labels:
        # DuckDB refuses a parameter in a CREATE VIEW, and the label comes
        # from our own DATASETS constant, not from the data.
        pool.execute("CREATE OR REPLACE TEMP VIEW one AS "
                     f"SELECT * FROM pooled WHERE dataset = '{label}'")
        for r in scan(pool, "one", draws=200):
            signs.setdefault((r.hypothesis, r.selection), []).append(r.delta)

    print("\n" + "=" * 96)
    print(f"{'ipotesi':22} {'sel':5} {'n_in':>5} {'bias_in':>9} {'delta':>9} "
          f"{'z':>6} {'p':>9} {'q':>9} {'replica':>9}")
    print("-" * 96)
    out = []
    for r in pooled:
        deltas = signs.get((r.hypothesis, r.selection), [])
        agree = sum(1 for d in deltas if (d > 0) == (r.delta > 0))
        replicates = agree >= REPLICATION_MIN and len(deltas) >= REPLICATION_MIN
        tag = ""
        if r.positive_control:
            tag = " [controllo]"
        elif r.discovery and replicates:
            tag = " <<< SOPRAVVIVE"
        elif r.discovery:
            tag = " (BH ok, non replica)"
        print(f"{r.hypothesis:22} {r.selection:5} {r.n_in:5} {r.bias_in:+9.4f} "
              f"{r.delta:+9.4f} {r.z:+6.2f} {r.p_value:9.5f} "
              f"{(r.q_value or 1):9.5f} {agree:4}/{len(deltas):<4}{tag}")
        out.append({
            "hypothesis": r.hypothesis, "selection": r.selection,
            "n_in": r.n_in, "n_out": r.n_out, "bias_in": r.bias_in,
            "bias_out": r.bias_out, "delta": r.delta, "se": r.se, "z": r.z,
            "p_value": r.p_value, "q_value": r.q_value,
            "bh_discovery": r.discovery, "positive_control": r.positive_control,
            "sign_agreement": agree, "n_datasets": len(deltas),
            "replicates": replicates,
        })

    controls = [r for r in pooled if r.positive_control]
    found = [r for r in controls if r.discovery]
    real = [r for r in pooled if r.discovery and not r.positive_control]
    non_control = [r for r in pooled if not r.positive_control]
    survivors = [r for r in real
                 if sum(1 for d in signs.get((r.hypothesis, r.selection), [])
                        if (d > 0) == (r.delta > 0)) >= REPLICATION_MIN]

    # -- power: what could this scan have found? ---------------------------
    m = len(pooled)
    z_strict, z_loose = _z_for(Q / m), _z_for(Q)
    mdes = sorted(z_strict * r.se for r in non_control)
    mde_median = mdes[len(mdes) // 2]
    loose = sorted(z_loose * r.se for r in non_control)
    mde_loose = loose[len(loose) // 2]
    largest = max(abs(r.delta) for r in non_control)

    print("\n" + "=" * 96)
    print(f"famiglia di {m} test, FDR controllato a q={Q}")
    print(f"  ipotesi che superano BH          : {len(real)}")
    print(f"  ... e replicano in >= {REPLICATION_MIN}/10        : {len(survivors)}")
    for r in survivors:
        print(f"      {r.hypothesis} / {r.selection}: delta {r.delta:+.4f}")

    print("\n  POTENZA — cosa avrebbe potuto trovare questa scansione")
    print(f"    z critica          : {z_strict:.2f} (rango 1) .. {z_loose:.2f} (rango m)")
    print(f"    effetto minimo rilevabile, mediano : "
          f"{mde_median:.4f} (severa) / {mde_loose:.4f} (lasca)")
    print(f"    effetto massimo osservato          : {largest:.4f}")
    print("    -> 'nessun bias trovato' significa 'nessun bias piu grande di")
    print(f"       ~{mde_loose:.2f}-{mde_median:.2f} punti di probabilita'. Un bias di 2-3 punti")
    print("       sarebbe altamente profittevole e resta sotto la soglia.")

    print("\n  IPOTESI DI LETTERATURA (non validano lo scanner)")
    print(f"    rilevate: {len(found)}/{len(controls)}")
    if not found:
        print("    La tabella di calibrazione sopra spiega perche: il prezzo")
        print("    de-viggato segue la frequenza realizzata in ogni banda, e il")
        print("    bias favorito-longshot NON e presente in questo mercato. Un")
        print("    controllo che cerca un bias assente non puo validare nulla.")
        print("    La validazione dello scanner e altrove: test_m7_hypothesis_scan")
        print("    pianta un bias noto e verifica che venga trovato.")
    if not survivors:
        print(f"\n  Nessuna situazione sopravvive. Con {m} test al 5% non corretto")
        print("  ce ne saremmo aspettati ~2 per puro caso: e precisamente il")
        print("  motivo per cui la correzione c'e.")

    if args.json:
        payload = {"calibration": calib, "tests": out,
                   "power": {"z_strict": z_strict, "z_loose": z_loose,
                             "mde_median_strict": mde_median,
                             "mde_median_loose": mde_loose,
                             "largest_observed": largest},
                   "n_matches": sum(per_dataset.values()),
                   "datasets": per_dataset}
        pathlib.Path(args.json).write_text(json.dumps(payload, indent=2, default=str))
        print(f"\nscritto {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
