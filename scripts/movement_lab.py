#!/usr/bin/env python3
"""
Il libro lento: esiste un book che si muove dopo gli altri, e conviene?

CHE COSA MI ERO PERSO
---------------------
Ho scritto che il movimento del prezzo richiede il collector e un secondo
poll. Falso per i dati storici: i file di stagione portano per OGNI book sia
l'apertura sia la chiusura — B365H accanto a B365CH, BFEH accanto a BFECH — e
due punti sono un movimento. Quattro stagioni di percorsi di prezzo erano gia'
li' e non le avevo guardate.

L'IPOTESI, FISSATA PRIMA
------------------------
Il laboratorio CLV ha misurato che prendere un prezzo qualunque e tenerlo fino
alla chiusura perde in ogni cella. Ma quel test era MARGINALE: una dimensione
alla volta, mai condizionato su cosa il mercato ha fatto dopo.

L'unico posto dove un vantaggio puo' esistere e' dove un prezzo NON ha ancora
recepito un'informazione che altri hanno gia'. Con apertura e chiusura per
ogni book, quella situazione e' identificabile:

    un book quota un esito PIU' LUNGO del consenso all'apertura,
    e il mercato poi si muove VERSO quell'esito.

Se i book si aggiornassero tutti insieme, questo non produrrebbe niente. Se
qualcuno e' sistematicamente lento, la sua quota resta comprabile mentre il
resto del mercato l'ha gia' corretta — ed e' l'unica forma di vantaggio che
questi dati possano contenere, perche' non richiede di sapere niente di
calcio.

CONTROLLO NEGATIVO
------------------
La stessa misura sul caso opposto — book piu' CORTO del consenso, mercato che
si muove verso l'esito — deve dare il risultato peggiore. Se entrambi i lati
risultassero positivi, la misura sta catturando qualcosa che non e' il
segnale, e va buttata.

    python scripts/movement_lab.py --seasons 2627 2526 2425 2324
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

from fiorino.odds.devig import banner, devig  # noqa: E402

UA = "fiorino-quant/1.0 (+research)"
SELECTIONS = ("HOME", "DRAW", "AWAY")
DIVISIONS = ("E0", "E1", "E2", "E3", "EC", "SC0", "SC1", "SC2", "D1", "D2",
             "I1", "I2", "SP1", "SP2", "F1", "F2", "N1", "B1", "P1", "T1", "G1")

#: (nome, colonne apertura, colonne chiusura). Gli aggregati Max e Avg restano
#: fuori dal consenso — sono fatti dei book stessi e li farebbero votare due
#: volte — ma il loro prezzo resta valutabile come quello di chiunque altro.
BOOKS = (
    ("BET365", ("B365H", "B365D", "B365A"), ("B365CH", "B365CD", "B365CA")),
    ("BETFAIR_SB", ("BFDH", "BFDD", "BFDA"), ("BFDCH", "BFDCD", "BFDCA")),
    ("BETVICTOR", ("BVH", "BVD", "BVA"), ("BVCH", "BVCD", "BVCA")),
    ("BWIN", ("BWH", "BWD", "BWA"), ("BWCH", "BWCD", "BWCA")),
    ("PADDY_POWER", ("PPH", "PPD", "PPA"), ("PPCH", "PPCD", "PPCA")),
    ("SKYBET", ("SKBH", "SKBD", "SKBA"), ("SKBCH", "SKBCD", "SKBCA")),
    ("BETFAIR_EX", ("BFEH", "BFED", "BFEA"), ("BFECH", "BFECD", "BFECA")),
)
AGGREGATES = (("MARKET_MAX", ("MaxH", "MaxD", "MaxA")),
              ("MARKET_AVG", ("AvgH", "AvgD", "AvgA")))
CLOSING_CONSENSUS = ("AvgCH", "AvgCD", "AvgCA")

ABSURD_CLV = 0.50
MIN_BOOKS = 4
#: Sotto questo il mercato non si e' mosso: la differenza e' arrotondamento.
MOVED = 0.010


def fetch(season, division):
    url = f"https://football-data.co.uk/mmz4281/{season}/{division}.csv"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError):
        return None


def fair(row, cols):
    try:
        prices = [float(row[c]) for c in cols]
    except (KeyError, TypeError, ValueError):
        return None, None
    if min(prices) <= 1.0:
        return None, None
    try:
        return tuple(devig(list(SELECTIONS), prices, "SHIN").fair_probs), prices
    except ValueError:
        return None, None


def collect(seasons):
    rows, matches, absurd = [], 0, 0
    for season in seasons:
        for division in DIVISIONS:
            text = fetch(season, division)
            if not text:
                continue
            for raw in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
                if raw.get("FTR") not in ("H", "D", "A"):
                    continue
                close_fair, _ = fair(raw, CLOSING_CONSENSUS)
                if close_fair is None:
                    continue

                opens = {}
                for book, open_cols, close_cols in BOOKS:
                    o_fair, o_prices = fair(raw, open_cols)
                    c_fair, _ = fair(raw, close_cols)
                    if o_fair is None:
                        continue
                    opens[book] = (o_fair, o_prices, c_fair)
                if len(opens) < MIN_BOOKS:
                    continue
                matches += 1

                consensus_open = tuple(
                    st.median(v[0][i] for v in opens.values()) for i in range(3))
                # Il movimento del MERCATO: dove e' finito meno dove era.
                movement = tuple(close_fair[i] - consensus_open[i] for i in range(3))

                for book, (o_fair, o_prices, c_fair) in opens.items():
                    # Consenso senza il book in esame: un book confrontato con
                    # un consenso che lo contiene e' in parte confrontato con
                    # se stesso.
                    others = [v[0] for b, v in opens.items() if b != book]
                    if len(others) < 2:
                        continue
                    for i in range(3):
                        reference = st.median(o[i] for o in others)
                        clv = close_fair[i] * o_prices[i] - 1.0
                        if abs(clv) > ABSURD_CLV:
                            absurd += 1
                            continue
                        # Negativo = il book prezza l'esito meno probabile
                        # degli altri, cioe' offre una quota piu' LUNGA.
                        deviation = o_fair[i] - reference
                        own_move = (c_fair[i] - o_fair[i]) if c_fair else None
                        rows.append({
                            "season": season, "div": division, "book": book,
                            "sel": SELECTIONS[i], "clv": clv,
                            "deviation": deviation, "movement": movement[i],
                            "own_move": own_move, "price": o_prices[i],
                        })
    return rows, matches, absurd


def cell(values, label, minimum=300):
    n = len(values)
    if n < minimum:
        return None
    mean = st.mean(values)
    se = st.stdev(values) / (n ** 0.5) if n > 1 else 0.0
    t = mean / se if se else 0.0
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(t) / (2 ** 0.5))))
    return {"label": label, "n": n, "mean": mean, "se": se, "t": t, "p": p}


def bh(pvalues, q=0.10):
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    m, out, running = len(pvalues), [1.0] * len(pvalues), 1.0
    for rank, i in reversed(list(enumerate(order, start=1))):
        running = min(running, pvalues[i] * m / rank)
        out[i] = running
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", nargs="+", default=["2627", "2526", "2425", "2324"])
    args = parser.parse_args()

    # Quale de-vig ha DAVVERO prodotto i numeri sotto.
    print(banner("SHIN"))

    rows, matches, absurd = collect(args.seasons)
    print(f"PARTITE={matches:,}   OSSERVAZIONI={len(rows):,}   "
          f"CLV assurdi scartati={absurd:,}")
    print(f"CLV medio su tutto  {st.mean(r['clv'] for r in rows):+.4f}  "
          f"(e il margine: la base da cui staccarsi)\n")

    # SOLO condizioni note AL MOMENTO DELLA SCOMMESSA.
    #
    # La prima versione condizionava su `movement`, che e'
    # close_fair - consensus_open, e poi segnava con
    # clv = close_fair * prezzo - 1. La stessa chiusura da entrambe le parti:
    # selezionare i casi in cui close_fair e' salito alza meccanicamente il
    # prodotto close_fair * prezzo. Non era un segnale, era una tautologia — e
    # al momento in cui la scommessa andrebbe piazzata, all'apertura, quel
    # movimento NON e' noto perche' e' definito da un prezzo che non esiste
    # ancora.
    #
    # Misurato: su un mercato simulato con zero segnale per costruzione, la
    # stessa selezione produce +0.0702 contro il +0.0440 osservato sui dati
    # veri. L'artefatto e' PIU' GRANDE dell'"effetto". Dose-risposta, controllo
    # negativo che si comporta bene e replica per stagione si riproducono tutti
    # dove non c'e' niente da trovare.
    #
    # E' la stessa classe di errore gia' trovata in M6, dove il braccio MARKET
    # mostrava +0.0234 di CLV per pura definizione. Ci sono ricascato.
    tests = []
    for lo, hi in ((-1.0, -0.020), (-0.020, -0.005), (-0.005, 0.005),
                   (0.005, 0.020), (0.020, 1.0)):
        subset = [r["clv"] for r in rows if lo <= r["deviation"] < hi]
        tests.append((f"scostamento dal consenso {lo:+.3f}/{hi:+.3f}", subset))
    for book, _, _ in BOOKS:
        subset = [r["clv"] for r in rows
                  if r["book"] == book and r["deviation"] < -0.005]
        tests.append((f"  piu' lungo del consenso: {book}", subset))

    cells = [c for c in (cell(v, k) for k, v in tests) if c]
    for c, q in zip(cells, bh([c["p"] for c in cells])):
        c["q"] = q

    header = f"{'CELLA':40} {'N':>9} {'CLV':>9} {'t':>8} {'q':>8}"
    print(header)
    print("-" * len(header))
    for c in cells:
        mark = "  <<< POSITIVO" if c["q"] < 0.10 and c["mean"] > 0 else ""
        print(f"{c['label']:40} {c['n']:9,} {c['mean']:+9.4f} "
              f"{c['t']:+8.2f} {c['q']:8.4f}{mark}")

    survivors = [c for c in cells if c["q"] < 0.10 and c["mean"] > 0]
    print(f"\nCELLE POSITIVE CHE SUPERANO BH: {len(survivors)}")
    if survivors:
        print("\nREPLICA PER STAGIONE — senza questa non e' un effetto.")
        for cell_survived in survivors:
            book = cell_survived["label"].strip().split()[-1]
            for season in args.seasons:
                subset = [r["clv"] for r in rows if r["season"] == season
                          and r["deviation"] < -0.005 and r["book"] == book]
                if len(subset) > 100:
                    print(f"  {cell_survived['label']:32} {season}: "
                          f"{st.mean(subset):+.4f}  (n={len(subset):,})")

    # Per confronto, e SOLO come promemoria: la cella circolare.
    circolare = [r["clv"] for r in rows
                 if r["deviation"] < -0.005 and r["movement"] > MOVED]
    print(f"\nPER CONFRONTO, LA CELLA CIRCOLARE: {st.mean(circolare):+.4f} "
          f"su {len(circolare):,}")
    print("Condiziona sul movimento verso la chiusura e poi segna contro la")
    print("chiusura. Un mercato simulato con zero segnale produce +0.0702 con")
    print("la stessa selezione. NON e' un risultato, ed e' qui solo perche'")
    print("cancellarlo avrebbe cancellato anche la ragione per cui e' sbagliato.")
    print("\nNESSUNA SCOMMESSA. Questo script misura.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
