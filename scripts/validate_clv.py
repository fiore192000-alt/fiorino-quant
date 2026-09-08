#!/usr/bin/env python3
"""
Out-of-sample validation of the M1-M3 chain.

Runs the full pipeline — identity, market reconstruction, de-vig, CLV — over
several real league-seasons and reports whether the measurements replicate.

This is NOT part of the test suite: it fetches from the network, and the suite
is offline by design. It is the reproducibility harness for
docs/validation/clv-validation.md, and every number in that document comes
from running this file.

    python scripts/validate_clv.py            # all datasets
    python scripts/validate_clv.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import statistics
import sys
import tempfile
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fiorino.clv.compute import compute_clv                    # noqa: E402
from fiorino.clv.replay import take_prematch                   # noqa: E402
from fiorino.data.db.connection import connect                 # noqa: E402
from fiorino.data.db.migrate import migrate                    # noqa: E402
from fiorino.data.ingest.sources.footballdata import FootballData  # noqa: E402
from fiorino.data.lake import bronze_path, write_bronze        # noqa: E402
from fiorino.data.pipeline import bootstrap_reference, ingest_bronze  # noqa: E402

RAW = "https://raw.githubusercontent.com"

#: (label, competition_id, season_id, url)
#:
#: Real Football-Data.co.uk files mirrored on GitHub. The site itself is not
#: reachable from the development environment (egress policy), but these are
#: byte-identical archives of the same publisher.
DATASETS = [
    ("ENG_PL 2017-18", "ENG_PL", "2017-2018",
     f"{RAW}/octonion/puzzles/master/elo/E0.csv"),
    ("ENG_PL 2018-19", "ENG_PL", "2018-2019",
     f"{RAW}/pawelp0499/football-prediction-model/main/data/18_19.csv"),
    ("ENG_PL 2019-20", "ENG_PL", "2019-2020",
     f"{RAW}/pawelp0499/football-prediction-model/main/data/19_20.csv"),
    ("ENG_PL 2020-21", "ENG_PL", "2020-2021",
     f"{RAW}/pawelp0499/football-prediction-model/main/data/20_21.csv"),
    ("ESP_LL 2019-20", "ESP_LL", "2019-2020",
     f"{RAW}/yssefunc/sport_analytics/master/data/SP1.csv"),
    ("ITA_SA 2019-20", "ITA_SA", "2019-2020",
     f"{RAW}/yssefunc/sport_analytics/master/data/I1.csv"),
    ("DEU_BL1 2024-25", "DEU_BL1", "2024-2025",
     f"{RAW}/nemesistip-cloud/vit/main/data/raw/D1.csv"),
    ("FRA_L1 2024-25", "FRA_L1", "2024-2025",
     f"{RAW}/nemesistip-cloud/vit/main/data/raw/F1.csv"),
    ("NLD_ED 2024-25", "NLD_ED", "2024-2025",
     f"{RAW}/nemesistip-cloud/vit/main/data/raw/N1.csv"),
    ("PRT_L1 2024-25", "PRT_L1", "2024-2025",
     f"{RAW}/nemesistip-cloud/vit/main/data/raw/P1.csv"),
]


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read().decode("utf-8-sig", errors="replace")


def run_one(label, competition_id, season_id, text) -> dict:
    """Ingest one league-season and measure CLV over an indiscriminate replay."""
    con = connect()
    migrate(con)
    bootstrap_reference(con)

    root = pathlib.Path(tempfile.mkdtemp()) / "lake"
    rows = FootballData().parse(text, competition_id, season_id)
    write_bronze(con, [r.as_row() for r in rows],
                 bronze_path(root, "footballdata", competition_id, season_id, "val"))

    ingest_bronze(con, root, auto_register_unknown=True)
    # Adjudicate: every fuzzy proposal on real club names is a look-alike pair
    # that must stay separate (Manchester United vs Manchester City at 0.926).
    from fiorino.data.identity.resolver import IdentityResolver

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

    take_prematch(con)
    clv = compute_clv(con, "replay_prematch")

    summary = con.execute(
        """SELECT n_bets, mean_clv_ev, mean_clv_price, beat_close_rate, clv_t_stat
           FROM v_clv_summary WHERE run_id = 'replay_prematch'"""
    ).fetchone()
    by_selection = {
        sel: (n, ev, price)
        for sel, n, ev, price in con.execute(
            """SELECT selection, count(*), avg(clv_ev), avg(clv_price)
               FROM v_bet_clv WHERE run_id='replay_prematch' AND line_matched
               GROUP BY 1"""
        ).fetchall()
    }
    # Per BOOK and per precision. An earlier version took a median across all
    # books at once, which mixed a 2% Pinnacle close with a 5.5% bet365 one and
    # reported a number belonging to neither.
    margins = {
        (book, precision): median
        for book, precision, median in con.execute(
            """SELECT bookmaker_id, capture_precision, median(overround)
               FROM fair_probabilities GROUP BY 1, 2"""
        ).fetchall()
    }
    n_matches, = con.execute("SELECT count(*) FROM v_analytic_matches").fetchone()
    con.close()

    return {
        "label": label,
        "competition": competition_id,
        "season": season_id,
        "n_source_rows": len(rows),
        "n_matches": n_matches,
        "n_bets": summary[0] if summary else 0,
        "mean_clv_ev": summary[1] if summary else None,
        "mean_clv_price": summary[2] if summary else None,
        "beat_close_rate": summary[3] if summary else None,
        "clv_t_stat": summary[4] if summary else None,
        "pinnacle_close_overround": margins.get(("pinnacle", "CLOSING")),
        "pinnacle_prematch_overround": margins.get(("pinnacle", "PREMATCH")),
        "margin_gap": (
            margins.get(("pinnacle", "PREMATCH"), 0) - margins.get(("pinnacle", "CLOSING"), 0)
            if margins.get(("pinnacle", "PREMATCH")) is not None
            and margins.get(("pinnacle", "CLOSING")) is not None else None
        ),
        "best_price_close_overround": margins.get(("market_max", "CLOSING")),
        "excluded": clv.excluded,
        "home_clv_price": by_selection.get("HOME", (0, 0, None))[2],
        "draw_clv_price": by_selection.get("DRAW", (0, 0, None))[2],
        "away_clv_price": by_selection.get("AWAY", (0, 0, None))[2],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    results = []
    for label, competition_id, season_id, url in DATASETS:
        try:
            text = fetch(url)
        except Exception as exc:
            print(f"{label:16} FETCH FAILED: {exc}", file=sys.stderr)
            continue
        try:
            results.append(run_one(label, competition_id, season_id, text))
        except Exception as exc:
            print(f"{label:16} RUN FAILED: {exc}", file=sys.stderr)
            continue
        r = results[-1]
        gap = r["margin_gap"]
        print(f"{r['label']:16} m={r['n_matches']:4} bets={r['n_bets']:5} "
              f"close={r['pinnacle_close_overround']:.4f} pre={r['pinnacle_prematch_overround']:.4f} "
              f"gap={gap:+.4f} | CLV={r['mean_clv_ev']:+.5f} t={r['clv_t_stat']:+7.2f} "
              f"beat={r['beat_close_rate']:.3f}")

    if not results:
        print("no datasets ran", file=sys.stderr)
        return 1

    print("\n" + "=" * 78)
    evs = [r["mean_clv_ev"] for r in results if r["mean_clv_ev"] is not None]
    ovs = [r["pinnacle_close_overround"] for r in results
           if r["pinnacle_close_overround"] is not None]
    gaps = [r["margin_gap"] for r in results if r["margin_gap"] is not None]
    best = [r["best_price_close_overround"] for r in results
            if r["best_price_close_overround"] is not None]
    homes = [r["home_clv_price"] for r in results if r["home_clv_price"] is not None]
    aways = [r["away_clv_price"] for r in results if r["away_clv_price"] is not None]
    total_bets = sum(r["n_bets"] for r in results)

    print(f"{len(results)} league-seasons, {total_bets} bets")
    print(f"  Pinnacle closing margin  : {statistics.median(ovs):.4f} "
          f"[{min(ovs):.4f}, {max(ovs):.4f}]")
    print(f"  prematch minus closing   : {statistics.median(gaps):+.4f} "
          f"[{min(gaps):+.4f}, {max(gaps):+.4f}]   "
          f"({sum(1 for g in gaps if g > 0.01)}/{len(gaps)} are opening prices)")
    if best:
        print(f"  best-price closing margin: {statistics.median(best):.4f} "
              f"[{min(best):.4f}, {max(best):.4f}]")
    print(f"  mean CLV_ev              : {statistics.mean(evs):+.5f} "
          f"[{min(evs):+.5f}, {max(evs):+.5f}]")
    print(f"  negative in              : {sum(1 for e in evs if e < 0)}/{len(evs)} datasets")
    print(f"  HOME price drift negative: {sum(1 for h in homes if h < 0)}/{len(homes)}")
    print(f"  AWAY price drift positive: {sum(1 for a in aways if a > 0)}/{len(aways)}")
    print(f"  mean HOME drift          : {statistics.mean(homes):+.5f}")
    print(f"  mean AWAY drift          : {statistics.mean(aways):+.5f}")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(results, indent=2))
        print(f"\nwritten {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
