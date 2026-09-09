#!/usr/bin/env python3
"""
Quale prezzo batte la chiusura? Misurato su piu' stagioni.

L'IDEA
------
I file di stagione di Football-Data portano, sulla stessa riga, la quota
PREMATCH di ogni book e la quota di CHIUSURA. Quindi per ogni singola
combinazione partita-book-esito si puo' calcolare direttamente:

    CLV = prob_equa_di_chiusura x prezzo_prematch - 1

Non serve nessun modello, nessuna previsione e nessuna scommessa simulata. E'
una misura di quanto quel prezzo valeva rispetto a dove il mercato e' finito, e
il CLV e' l'unica metrica che in questo progetto abbia mai deciso qualcosa: M4
l'ha visto corretto 30 volte su 30 mentre il rendimento sbagliava 7 volte su 30.

Con tre stagioni e venti divisioni sono decine di migliaia di osservazioni, che
e' il primo campione di questo progetto in cui un effetto piccolo possa
emergere.

LA DISCIPLINA, PERCHE' QUI E' FACILE INGANNARSI
-----------------------------------------------
Si stanno per testare decine di celle. Con abbastanza celle qualcosa risulta
significativo per costruzione, ed e' esattamente come si trova un edge che non
esiste. Quindi:

  - le ipotesi sono fissate PRIMA, non scelte guardando i risultati;
  - Benjamini-Hochberg controlla il tasso di falsi positivi sulla famiglia;
  - una cella deve REPLICARE su piu' stagioni, non solo essere significativa;
  - i valori estremi vengono contati e riportati, non tenuti: un CLV oltre il
    50% non e' un'occasione, e' un prezzo sbagliato nel file, e quattro righe
    del genere hanno gia' spiegato il 90% di un risultato apparente.

    python scripts/clv_lab.py [--seasons 2627 2526 2425]
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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fiorino.odds.devig import devig  # noqa: E402

UA = "fiorino-quant/1.0 (+research)"
SELECTIONS = ("HOME", "DRAW", "AWAY")

DIVISIONS = ("E0", "E1", "E2", "E3", "EC", "SC0", "SC1", "SC2", "D1", "D2",
             "I1", "I2", "SP1", "SP2", "F1", "F2", "N1", "B1", "P1", "T1", "G1")
LOWER = {"E1", "E2", "E3", "EC", "SC1", "SC2", "D2", "I2", "SP2", "F2"}

BOOKS = (("BET365", ("B365H", "B365D", "B365A")),
         ("BETFAIR_SB", ("BFDH", "BFDD", "BFDA")),
         ("BETVICTOR", ("BVH", "BVD", "BVA")),
         ("BWIN", ("BWH", "BWD", "BWA")),
         ("PADDY_POWER", ("PPH", "PPD", "PPA")),
         ("SKYBET", ("SKBH", "SKBD", "SKBA")),
         ("BETFAIR_EX", ("BFEH", "BFED", "BFEA")),
         ("MARKET_MAX", ("MaxH", "MaxD", "MaxA")),
         ("MARKET_AVG", ("AvgH", "AvgD", "AvgA")))
CLOSING = ("AvgCH", "AvgCD", "AvgCA")

#: Oltre questo un CLV non e' un'occasione: e' un prezzo sbagliato. Quattro
#: righe sopra questa soglia hanno gia' spiegato il 90% di un risultato
#: apparentemente positivo su una stagione.
ABSURD_CLV = 0.50
BANDS = ((1.0, 1.6), (1.6, 2.2), (2.2, 3.2), (3.2, 5.0), (5.0, 9.0), (9.0, 1e9))


def fetch(season: str, division: str) -> str | None:
    url = f"https://football-data.co.uk/mmz4281/{season}/{division}.csv"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError):
        return None


def band_of(price: float) -> str:
    for lo, hi in BANDS:
        if lo <= price < hi:
            return f"{lo:.1f}-{hi:.1f}" if hi < 1e8 else f"{lo:.1f}+"
    return "?"


def collect(seasons):
    """Una riga per (partita, book, esito) con il suo CLV."""
    rows, absurd, no_close, files = [], 0, 0, 0
    for season in seasons:
        for division in DIVISIONS:
            text = fetch(season, division)
            if not text:
                continue
            files += 1
            for raw in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
                if raw.get("FTR") not in ("H", "D", "A"):
                    continue
                try:
                    close_prices = [float(raw[c]) for c in CLOSING]
                except (KeyError, TypeError, ValueError):
                    no_close += 1
                    continue
                if min(close_prices) <= 1.0:
                    no_close += 1
                    continue
                try:
                    close_fair = devig(list(SELECTIONS), close_prices, "SHIN").fair_probs
                except ValueError:
                    no_close += 1
                    continue

                outcome = {"H": 0, "D": 1, "A": 2}[raw["FTR"]]
                for book, cols in BOOKS:
                    try:
                        prices = [float(raw[c]) for c in cols]
                    except (KeyError, TypeError, ValueError):
                        continue
                    if min(prices) <= 1.0:
                        continue
                    for i, price in enumerate(prices):
                        clv = close_fair[i] * price - 1.0
                        if abs(clv) > ABSURD_CLV:
                            absurd += 1
                            continue
                        rows.append({
                            "season": season, "div": division, "book": book,
                            "sel": SELECTIONS[i], "price": price, "clv": clv,
                            "won": i == outcome, "band": band_of(price),
                            "tier": "LOWER" if division in LOWER else "TOP",
                        })
    return rows, absurd, no_close, files


def cell(rows, label):
    """Media, errore standard, t e p normale a due code."""
    values = [r["clv"] for r in rows]
    n = len(values)
    if n < 200:
        return None
    mean = st.mean(values)
    se = st.stdev(values) / (n ** 0.5)
    t = mean / se if se else 0.0
    # p a due code dalla normale: con n nell'ordine delle migliaia la
    # differenza dalla t di Student e' irrilevante.
    p = 2 * (1 - 0.5 * (1 + _erf(abs(t) / (2 ** 0.5))))
    return {"label": label, "n": n, "mean": mean, "se": se, "t": t, "p": p,
            "won": sum(r["won"] for r in rows) / n}


def benjamini_hochberg(pvalues, q=0.10):
    """FDR sulla famiglia. Scritto qui su una lista di p perche' quello in
    fiorino.research.scan lavora sugli oggetti dello scanner: importarlo
    avrebbe legato questo script alla forma di quelli.

    Con decine di celle testate, qualcosa risulta significativo per
    costruzione. Questa correzione e' cio' che separa una scoperta dal numero
    di celle guardate.
    """
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    m = len(pvalues)
    out = [1.0] * m
    running = 1.0
    for rank, i in reversed(list(enumerate(order, start=1))):
        running = min(running, pvalues[i] * m / rank)
        out[i] = running
    return out


def _erf(x: float) -> float:
    import math
    return math.erf(x)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", nargs="+", default=["2627", "2526", "2425"])
    args = parser.parse_args()

    rows, absurd, no_close, files = collect(args.seasons)
    print(f"FILE LETTI={files}   OSSERVAZIONI={len(rows):,}")
    print(f"SCARTATE: CLV assurdo (>{ABSURD_CLV:.0%})={absurd:,}   "
          f"senza chiusura utilizzabile={no_close:,}")
    print(f"CLV medio su TUTTO                      {st.mean(r['clv'] for r in rows):+.4f}")
    print("  (negativo per costruzione: e' il margine. Cio che conta e quali\n"
          "   celle si staccano da questa base, non il segno della base.)\n")

    # Ipotesi fissate PRIMA di guardare i risultati.
    families = []
    for book, _ in BOOKS:
        families.append((f"book={book}", [r for r in rows if r["book"] == book]))
    for lo, hi in BANDS:
        label = f"{lo:.1f}-{hi:.1f}" if hi < 1e8 else f"{lo:.1f}+"
        families.append((f"banda={label}", [r for r in rows if r["band"] == label]))
    for selection in SELECTIONS:
        families.append((f"esito={selection}", [r for r in rows if r["sel"] == selection]))
    for tier in ("TOP", "LOWER"):
        families.append((f"serie={tier}", [r for r in rows if r["tier"] == tier]))

    cells = [c for c in (cell(subset, label) for label, subset in families) if c]
    q = benjamini_hochberg([c["p"] for c in cells], 0.10)
    for c, value in zip(cells, q):
        c["q"] = value

    cells.sort(key=lambda c: -c["mean"])
    header = (f"{'CELLA':22} {'N':>8} {'CLV':>9} {'SE':>8} {'t':>7} "
              f"{'q':>8} {'VINTE':>7}")
    print(header)
    print("-" * len(header))
    for c in cells:
        flag = "  <<<" if c["q"] < 0.10 and c["mean"] > 0 else ""
        print(f"{c['label']:22} {c['n']:8,} {c['mean']:+9.4f} {c['se']:8.4f} "
              f"{c['t']:+7.2f} {c['q']:8.4f} {c['won']:7.1%}{flag}")

    survivors = [c for c in cells if c["q"] < 0.10 and c["mean"] > 0]
    print(f"\nCELLE CON CLV POSITIVO CHE SUPERANO BH a q=0.10: {len(survivors)}")

    if survivors:
        print("\nREPLICA PER STAGIONE — una cella che non tiene il segno su ogni")
        print("stagione non e' un effetto, e' un anno fortunato.")
        for c in survivors:
            key, value = c["label"].split("=")
            field = {"book": "book", "banda": "band",
                     "esito": "sel", "serie": "tier"}[key]
            line = []
            for season in args.seasons:
                subset = [r["clv"] for r in rows
                          if r[field] == value and r["season"] == season]
                line.append(f"{season}: {st.mean(subset):+.4f} (n={len(subset):,})"
                            if len(subset) > 100 else f"{season}: -")
            print(f"  {c['label']:22} " + "   ".join(line))
    else:
        print("\nNessuna cella con CLV positivo sopravvive alla correzione.")
        print("Non e' un fallimento della misura: e' la misura che dice che con")
        print("questi prezzi, presi cosi', non si batte la chiusura.")

    print("\nNESSUNA SCOMMESSA. Questo script misura, non propone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
