#!/usr/bin/env python3
"""
Cosa avrebbe detto il motore sulle partite degli ultimi giorni, e cosa e'
successo davvero.

I file di stagione di Football-Data portano tre cose insieme: le quote
PREMATCH, le quote di CHIUSURA (colonne con la C) e il RISULTATO. Su una
partita conclusa si puo' quindi chiudere il cerchio che su una partita futura
resta aperto: candidato -> chiusura -> esito.

CHE COSA E' E CHE COSA NON E'
-----------------------------
Non e' una simulazione di cio' che Fiorino avrebbe saputo in diretta. Queste
quote arrivano DOPO il risultato: il file viene pubblicato a partite giocate.
Sono pero' quote realmente prematch, raccolte prima del calcio d'inizio, quindi
valutarle a posteriori e' legittimo per la ricerca. Diventa illegittimo nel
momento in cui il rendimento che ne esce viene raccontato come se si fosse
potuto incassare: quella e' la differenza fra misurare e vantarsi.

Il CLV e' l'unica metrica che qui abbia un significato forte. Il rendimento su
poche decine di partite e' rumore: M4 ha misurato che il verdetto del CLV e'
corretto 30 volte su 30 mentre quello del rendimento sbaglia 7 volte su 30.

    python scripts/last_days.py [--days 3]
"""

from __future__ import annotations

import argparse
import csv
import io
import pathlib
import statistics as st
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fiorino.data.ingest.odds_feed.recorder import Quote  # noqa: E402
from fiorino.market.consensus import SELECTIONS, build_consensus  # noqa: E402
from fiorino.odds.devig import devig  # noqa: E402

BASE = "https://football-data.co.uk/mmz4281/2627"
UA = "fiorino-quant/1.0 (+research)"
DIVISIONS = ("E0", "E1", "E2", "E3", "EC", "SC0", "SC1", "D1", "D2", "I1", "I2",
             "SP1", "SP2", "F1", "F2", "N1", "B1", "P1", "T1", "G1")

#: Prematch. Gli stessi che il collector legge da fixtures.csv.
BOOKS = (("BET365", ("B365H", "B365D", "B365A")),
         ("BETFAIR_SB", ("BFDH", "BFDD", "BFDA")),
         ("BETVICTOR", ("BVH", "BVD", "BVA")),
         ("BWIN", ("BWH", "BWD", "BWA")),
         ("PADDY_POWER", ("PPH", "PPD", "PPA")),
         ("SKYBET", ("SKBH", "SKBD", "SKBA")),
         ("BETFAIR_EX", ("BFEH", "BFED", "BFEA")))
#: Chiusura: le stesse colonne con la C. Sono queste a rendere misurabile il CLV.
CLOSING = ("AvgCH", "AvgCD", "AvgCA")
EXCHANGE_COMMISSION = 0.05
MIN_BOOKS = 5


def fetch(division: str) -> str | None:
    url = f"{BASE}/{division}.csv"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=45) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError):
        return None


def quotes(row: dict, division: str, key: str) -> list[Quote]:
    out = []
    for book, cols in BOOKS:
        try:
            h, d, a = (float(row[c]) for c in cols)
        except (KeyError, TypeError, ValueError):
            continue
        if min(h, d, a) <= 1.0:
            continue
        out.append(Quote(match_key=key, bookmaker=book, home=h, draw=d, away=a))
    return out


def closing_fair(row: dict) -> tuple[float, float, float] | None:
    """Probabilita' de-viggate della CHIUSURA. Il metro del CLV."""
    try:
        prices = [float(row[c]) for c in CLOSING]
    except (KeyError, TypeError, ValueError):
        return None
    if min(prices) <= 1.0:
        return None
    try:
        return tuple(devig(list(SELECTIONS), prices, "SHIN").fair_probs)
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=3)
    args = parser.parse_args()

    cutoff = datetime.now(timezone.utc).date() - timedelta(days=args.days)
    played, candidates, no_closing = [], [], 0

    for division in DIVISIONS:
        text = fetch(division)
        if not text:
            continue
        for row in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
            date_text = (row.get("Date") or "").strip()
            try:
                when = datetime.strptime(date_text, "%d/%m/%Y").date()
            except ValueError:
                continue
            if when < cutoff:
                continue
            result = row.get("FTR")
            if result not in ("H", "D", "A"):
                continue

            key = f"{division}|{date_text}|{row['HomeTeam']}|{row['AwayTeam']}"
            consensus = build_consensus(key, quotes(row, division, key))
            if consensus is None or consensus.n_books < MIN_BOOKS:
                continue

            outcome = {"H": 0, "D": 1, "A": 2}[result]
            close = closing_fair(row)
            if close is None:
                no_closing += 1

            best = None
            for view in consensus.books:
                for i in range(3):
                    edge = consensus.edge_leave_one_out(view.bookmaker, i)
                    if edge is None:
                        continue
                    price = view.prices[i]
                    net = (1 + (price - 1) * (1 - EXCHANGE_COMMISSION)
                           if view.bookmaker == "BETFAIR_EX" else price)
                    edge_net = (edge + 1) * (net / price) - 1
                    excess = edge_net - consensus.null_edge(i)
                    if best is None or excess > best["excess"]:
                        best = {"book": view.bookmaker, "sel": i, "price": price,
                                "net": net, "edge": edge_net, "excess": excess}

            record = {
                "div": division, "date": when, "when": date_text,
                "home": row["HomeTeam"], "away": row["AwayTeam"],
                "result": result, "outcome": outcome,
                "fair": consensus.fair, "books": consensus.n_books,
                "margin": consensus.mean_overround, "best": best, "close": close,
            }
            played.append(record)
            if best and best["excess"] > 0:
                candidates.append(record)

    played.sort(key=lambda r: (r["date"], r["div"]))
    print(f"PARTITE CONCLUSE NEGLI ULTIMI {args.days} GIORNI: {len(played)}")
    print(f"con almeno {MIN_BOOKS} book quotati. Senza quota di chiusura: {no_closing}\n")

    header = (f"{'DATA':11} {'DIV':4} {'PARTITA':38} {'ES':3} "
              f"{'P.MERCATO H/D/A':22} {'MIGLIOR CANDIDATO':26} {'ECCESSO':>8}")
    print(header)
    print("-" * len(header))
    for r in played[:40]:
        b = r["best"]
        cand = (f"{SELECTIONS[b['sel']]:5}{b['book'][:10]:11}{b['price']:5.2f}"
                if b else "—")
        excess = f"{b['excess']:+8.2%}" if b else "       —"
        print(f"{r['when']:11} {r['div']:4} "
              f"{(r['home'] + ' - ' + r['away'])[:38]:38} {r['result']:3} "
              f"{' '.join(f'{p:.3f}' for p in r['fair']):22} {cand:26} {excess}")

    print("\n" + "=" * 78)
    print(f"CANDIDATI SOPRA LA BANDA NULLA: {len(candidates)} su {len(played)}")

    if not candidates:
        print("\nIl sistema non avrebbe suggerito NIENTE.")
        print("Non perche' non abbia guardato: ha valutato ogni partita, ogni")
        print("book e ogni esito. Nessun prezzo si stacca dal consenso piu' di")
        print("quanto faccia il solo disaccordo fra i book.")
    else:
        wins = sum(1 for r in candidates if r["best"]["sel"] == r["outcome"])
        staked = len(candidates)
        ret = sum((r["best"]["net"] - 1) if r["best"]["sel"] == r["outcome"] else -1
                  for r in candidates)
        clv = [r["close"][r["best"]["sel"]] * r["best"]["net"] - 1
               for r in candidates if r["close"]]
        print(f"  vincenti           {wins}/{staked}")
        print(f"  rendimento         {ret / staked:+.2%}  (su {staked} unita)")
        if clv:
            print(f"  CLV medio          {st.mean(clv):+.4f}  su {len(clv)} misurati")
            print(f"  CLV positivo       {sum(c > 0 for c in clv)}/{len(clv)}")
        print("\n  Il rendimento su questo campione e' rumore: M4 ha misurato che")
        print("  il verdetto del CLV e' corretto 30 volte su 30 mentre quello del")
        print("  rendimento sbaglia 7 volte su 30. Guardare il CLV.")

    print("\nQueste quote sono realmente prematch ma arrivano DOPO il risultato:")
    print("il file esce a partite giocate. Valutarle a posteriori e' legittimo")
    print("per la ricerca, non e' un rendimento che si sarebbe potuto incassare.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
