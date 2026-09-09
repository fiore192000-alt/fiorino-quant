#!/usr/bin/env python3
"""
Over/Under e handicap asiatico: i due mercati su cui la chiusura non aveva
guardato.

PERCHE' ESISTE
--------------
docs/FINDINGS.md dichiara chiusa la ricerca ex-post su 369.662 osservazioni.
Tutte 1X2. Gli stessi file contengono anche Over/Under 2.5 e handicap
asiatico, con apertura E chiusura per gli stessi book, e non erano mai stati
guardati. Una chiusura basata su un mercato su tre e' piu' debole di come era
stata scritta, e questo script serve a chiuderla davvero o a riaprirla.

Sono mercati diversi, non varianti dello stesso. Hanno due esiti invece di
tre, margini piu' bassi, e — nel caso dei totali — un legame con qualcosa di
fisico e prevedibile, il meteo, che l'1X2 non ha.

LA TRAPPOLA DELL'HANDICAP
-------------------------
La linea si muove. Un handicap aperto a -0.5 e chiuso a -0.75 non e' lo stesso
scommessa: confrontarne i prezzi darebbe un CLV che misura lo spostamento
della linea e non il valore del prezzo. Le righe dove AHh != AHCh vengono
quindi ESCLUSE e contate. Senza questo filtro il mercato dell'handicap
produrrebbe numeri spettacolari e privi di senso — la stessa famiglia di
errore del look-ahead, con un meccanismo diverso.

    python scripts/other_markets_lab.py --seasons 2627 2526 2425 2324
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import pathlib
import statistics as st
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fiorino.odds.devig import devig  # noqa: E402

UA = "fiorino-quant/1.0 (+research)"
DIVISIONS = ("E0", "E1", "E2", "E3", "EC", "SC0", "SC1", "D1", "D2", "I1", "I2",
             "SP1", "SP2", "F1", "F2", "N1", "B1", "P1", "T1", "G1")
ABSURD_CLV = 0.50

#: Over/Under 2.5. Due esiti: il de-vig e piu' semplice e il margine piu' basso.
OU_BOOKS = (("BET365", ("B365>2.5", "B365<2.5")),
            ("MARKET_MAX", ("Max>2.5", "Max<2.5")),
            ("MARKET_AVG", ("Avg>2.5", "Avg<2.5")),
            ("BETFAIR_EX", ("BFE>2.5", "BFE<2.5")))
OU_CLOSE = ("AvgC>2.5", "AvgC<2.5")

#: Handicap asiatico sulla linea principale.
AH_BOOKS = (("BET365", ("B365AHH", "B365AHA")),
            ("MARKET_MAX", ("MaxAHH", "MaxAHA")),
            ("MARKET_AVG", ("AvgAHH", "AvgAHA")),
            ("BETFAIR_EX", ("BFEAHH", "BFEAHA")))
AH_CLOSE = ("AvgCAHH", "AvgCAHA")


def fetch(season, division):
    url = f"https://football-data.co.uk/mmz4281/{season}/{division}.csv"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError):
        return None


def two_way(row, cols):
    try:
        prices = [float(row[c]) for c in cols]
    except (KeyError, TypeError, ValueError):
        return None, None
    if min(prices) <= 1.0:
        return None, None
    try:
        return tuple(devig(["A", "B"], prices, "SHIN").fair_probs), prices
    except ValueError:
        return None, None


def collect(seasons):
    rows = []
    stats = {"partite": 0, "ou": 0, "ah": 0, "ah_linea_mossa": 0, "assurdi": 0}
    for season in seasons:
        for division in DIVISIONS:
            text = fetch(season, division)
            if not text:
                continue
            for raw in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
                if raw.get("FTR") not in ("H", "D", "A"):
                    continue
                stats["partite"] += 1

                # --- Over/Under 2.5 -------------------------------------
                close_ou, _ = two_way(raw, OU_CLOSE)
                if close_ou:
                    try:
                        goals = int(raw["FTHG"]) + int(raw["FTAG"])
                    except (KeyError, TypeError, ValueError):
                        goals = None
                    for book, cols in OU_BOOKS:
                        _, prices = two_way(raw, cols)
                        if not prices:
                            continue
                        for i in range(2):
                            clv = close_ou[i] * prices[i] - 1.0
                            if abs(clv) > ABSURD_CLV:
                                stats["assurdi"] += 1
                                continue
                            stats["ou"] += 1
                            rows.append({
                                "mercato": "OVER_UNDER_2.5", "season": season,
                                "book": book, "sel": "OVER" if i == 0 else "UNDER",
                                "clv": clv, "price": prices[i],
                                "won": None if goals is None
                                       else (goals > 2.5) == (i == 0),
                            })

                # --- Handicap asiatico ----------------------------------
                # La linea deve essere la STESSA all'apertura e alla chiusura:
                # altrimenti si confrontano due scommesse diverse.
                try:
                    line_open = float(raw["AHh"])
                    line_close = float(raw["AHCh"])
                except (KeyError, TypeError, ValueError):
                    continue
                if abs(line_open - line_close) > 1e-9:
                    stats["ah_linea_mossa"] += 1
                    continue
                close_ah, _ = two_way(raw, AH_CLOSE)
                if not close_ah:
                    continue
                for book, cols in AH_BOOKS:
                    _, prices = two_way(raw, cols)
                    if not prices:
                        continue
                    for i in range(2):
                        clv = close_ah[i] * prices[i] - 1.0
                        if abs(clv) > ABSURD_CLV:
                            stats["assurdi"] += 1
                            continue
                        stats["ah"] += 1
                        rows.append({
                            "mercato": "ASIAN_HANDICAP", "season": season,
                            "book": book, "sel": "HOME" if i == 0 else "AWAY",
                            "clv": clv, "price": prices[i], "won": None,
                        })
    return rows, stats


def cell(values, label, minimum=300):
    n = len(values)
    if n < minimum:
        return None
    mean = st.mean(values)
    se = st.stdev(values) / (n ** 0.5) if n > 1 else 0.0
    t = mean / se if se else 0.0
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(t) / (2 ** 0.5))))
    return {"label": label, "n": n, "mean": mean, "t": t, "p": p}


def bh(pvalues, q=0.10):
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    m, out, running = len(pvalues), [1.0] * len(pvalues), 1.0
    for rank, i in reversed(list(enumerate(order, start=1))):
        running = min(running, pvalues[i] * m / rank)
        out[i] = running
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", nargs="+",
                        default=["2627", "2526", "2425", "2324"])
    args = parser.parse_args()

    rows, stats = collect(args.seasons)
    print(f"PARTITE={stats['partite']:,}")
    print(f"OSSERVAZIONI  over/under={stats['ou']:,}  handicap={stats['ah']:,}")
    print(f"HANDICAP SCARTATI perche la linea si e mossa fra apertura e "
          f"chiusura: {stats['ah_linea_mossa']:,}")
    print(f"CLV assurdi scartati: {stats['assurdi']:,}\n")

    tests = []
    for mercato in ("OVER_UNDER_2.5", "ASIAN_HANDICAP"):
        subset = [r["clv"] for r in rows if r["mercato"] == mercato]
        tests.append((mercato, subset))
        for book, _ in OU_BOOKS:
            values = [r["clv"] for r in rows
                      if r["mercato"] == mercato and r["book"] == book]
            tests.append((f"  {mercato[:12]} {book}", values))
        for sel in sorted({r["sel"] for r in rows if r["mercato"] == mercato}):
            values = [r["clv"] for r in rows
                      if r["mercato"] == mercato and r["sel"] == sel]
            tests.append((f"  {mercato[:12]} {sel}", values))

    cells = [c for c in (cell(v, k) for k, v in tests) if c]
    for c, q in zip(cells, bh([c["p"] for c in cells])):
        c["q"] = q
    cells.sort(key=lambda c: -c["mean"])

    header = f"{'CELLA':34} {'N':>9} {'CLV':>9} {'t':>8} {'q':>8}"
    print(header)
    print("-" * len(header))
    for c in cells:
        mark = "  <<< POSITIVO" if c["q"] < 0.10 and c["mean"] > 0 else ""
        print(f"{c['label']:34} {c['n']:9,} {c['mean']:+9.4f} "
              f"{c['t']:+8.2f} {c['q']:8.4f}{mark}")

    survivors = [c for c in cells if c["q"] < 0.10 and c["mean"] > 0]
    print(f"\nCELLE POSITIVE CHE SUPERANO BH: {len(survivors)}")
    if survivors:
        print("\nREPLICA PER STAGIONE")
        for c in survivors:
            for season in args.seasons:
                key = c["label"].strip().split()
                values = [r["clv"] for r in rows if r["season"] == season
                          and (r["mercato"].startswith(key[0])
                               or r["book"] == key[-1])]
                if len(values) > 200:
                    print(f"  {c['label']:32} {season}: "
                          f"{st.mean(values):+.4f} (n={len(values):,})")
    print("\nNESSUNA SCOMMESSA. Questo script misura.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
