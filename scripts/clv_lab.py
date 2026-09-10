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

from fiorino.odds.devig import banner, devig  # noqa: E402

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
    """Una riga per (partita, book, esito) con il suo CLV.

    Ogni riga porta la chiave della partita da cui viene. Serve a due cose che
    prima non erano possibili: raggruppare gli errori standard per partita (le
    27 righe di una partita non sono 27 osservazioni indipendenti) e sapere,
    al momento della decisione, se quel prezzo era il piu' lungo del mercato.
    """
    rows, absurd, no_close, files = [], 0, 0, 0
    scarti = {"alto": 0, "basso": 0}
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
                match_key = (f"{division}|{season}|{raw.get('Date','')}|"
                             f"{raw.get('HomeTeam','')}|{raw.get('AwayTeam','')}")

                # Il prezzo piu' lungo del mercato per ogni esito, contato solo
                # sui book veri: MARKET_MAX e MARKET_AVG sono statistiche sugli
                # altri, non quotazioni prendibili.
                best = [0.0, 0.0, 0.0]
                for book, cols in BOOKS:
                    if book in ("MARKET_MAX", "MARKET_AVG"):
                        continue
                    try:
                        candidate = [float(raw[c]) for c in cols]
                    except (KeyError, TypeError, ValueError):
                        continue
                    if min(candidate) <= 1.0:
                        continue
                    for i, price in enumerate(candidate):
                        best[i] = max(best[i], price)

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
                            scarti["alto" if clv > 0 else "basso"] += 1
                            continue
                        rows.append({
                            "season": season, "div": division, "book": book,
                            "sel": SELECTIONS[i], "price": price, "clv": clv,
                            "won": i == outcome, "band": band_of(price),
                            "tier": "LOWER" if division in LOWER else "TOP",
                            "match": match_key,
                            # Noto al momento della decisione: nessuna
                            # informazione di chiusura entra qui.
                            "is_best": best[i] > 0 and price >= best[i] - 1e-9,
                        })
    return rows, absurd, no_close, files, scarti


def cell(rows, label):
    """Media, errore standard RAGGRUPPATO PER PARTITA, t e p a due code.

    Una partita produce fino a 9 book x 3 esiti = 27 righe che condividono la
    stessa probabilita' equa di chiusura, e le 3 selezioni di un book sono
    legate per costruzione perche' le eque sommano a 1. Trattarle come
    indipendenti gonfia il t: il numero di partite, non di righe, e' cio' che
    porta informazione. Lo scarto fra i due errori standard e' stampato come
    `design effect`, perche' e' la misura di quanto era sovrastimata la
    precisione dichiarata finora.
    """
    values = [r["clv"] for r in rows]
    n = len(values)
    if n < 200:
        return None
    mean = st.mean(values)
    se_ingenuo = st.stdev(values) / (n ** 0.5)

    # Sandwich per medie raggruppate: la varianza della media e' quella delle
    # somme per partita, non quella delle singole righe.
    per_match: dict[str, list[float]] = {}
    for r in rows:
        per_match.setdefault(r["match"], []).append(r["clv"])
    residui = [sum(v - mean for v in group) for group in per_match.values()]
    g = len(residui)
    if g > 1:
        se = (sum(x * x for x in residui) / (n * n)) ** 0.5
        se = se * (g / (g - 1)) ** 0.5
    else:
        se = se_ingenuo
    se = max(se, 1e-12)
    t = mean / se if se else 0.0
    # p a due code dalla normale: con n nell'ordine delle migliaia la
    # differenza dalla t di Student e' irrilevante.
    p = 2 * (1 - 0.5 * (1 + _erf(abs(t) / (2 ** 0.5))))
    return {"label": label, "n": n, "mean": mean, "se": se, "t": t, "p": p,
            "partite": g, "deff": (se / se_ingenuo) ** 2 if se_ingenuo else 1.0,
            "won": sum(r["won"] for r in rows) / n}



def contrasto_dentro_il_book(rows, replicas=400, seed=20260910):
    """CLV(prezzo migliore del mercato) meno CLV(non migliore), DENTRO il book.

    Il perche' e' tutto qui. Il CLV in livello assoluto di un book e' il suo
    margine: l'identita' equa*prezzo = 1/(1+margine) lo rende vero per
    costruzione, non per misura. Una regola che spostasse Bet365 da -0.0630 a
    -0.0300 sarebbe informazione enorme, e il disegno per livelli assoluti la
    classificherebbe "cella negativa" perche' resta sotto zero.

    Prendendo la differenza fra due sottoinsiemi DELLO STESSO book il margine
    si cancella e resta solo cio' che la regola aggiunge. La regola qui e'
    "questo prezzo era il piu' lungo del mercato", che e' calcolabile al
    momento della decisione: nessuna informazione di chiusura entra nella
    selezione. Il prezzo di chiusura serve solo a valutare, mai a scegliere.

    L'errore standard viene da un bootstrap sulle PARTITE, non sulle righe:
    ricampionare righe tratterebbe 27 osservazioni della stessa partita come
    27 informazioni indipendenti.
    """
    import random

    # Somme per (partita, book, gruppo), cosi' ogni replica e' una somma di
    # partite gia' aggregate invece di una scansione di 370.000 righe.
    per_match: dict[str, dict[tuple[str, bool], tuple[float, int]]] = {}
    for r in rows:
        cell_key = (r["book"], r["is_best"])
        bucket = per_match.setdefault(r["match"], {})
        total, count = bucket.get(cell_key, (0.0, 0))
        bucket[cell_key] = (total + r["clv"], count + 1)

    matches = list(per_match)
    books = sorted({r["book"] for r in rows})

    def differenze(campione):
        somme: dict[tuple[str, bool], list[float]] = {}
        for key in campione:
            for cell_key, (total, count) in per_match[key].items():
                acc = somme.setdefault(cell_key, [0.0, 0])
                acc[0] += total
                acc[1] += count
        out = {}
        for book in books:
            migliore = somme.get((book, True), [0.0, 0])
            resto = somme.get((book, False), [0.0, 0])
            if migliore[1] < 200 or resto[1] < 200:
                continue
            out[book] = (migliore[0] / migliore[1]) - (resto[0] / resto[1])
        return out

    osservato = differenze(matches)
    rng = random.Random(seed)
    repliche: dict[str, list[float]] = {b: [] for b in osservato}
    for _ in range(replicas):
        campione = [rng.choice(matches) for _ in matches]
        for book, value in differenze(campione).items():
            if book in repliche:
                repliche[book].append(value)

    fuori = []
    for book, diff in osservato.items():
        draws = repliche[book]
        errore = st.stdev(draws) if len(draws) > 2 else float("nan")
        n_best = sum(1 for r in rows if r["book"] == book and r["is_best"])
        n_altri = sum(1 for r in rows if r["book"] == book and not r["is_best"])
        fuori.append({"book": book, "diff": diff, "se": errore,
                      "n_best": n_best, "n_altri": n_altri,
                      "t": diff / errore if errore and errore == errore else 0.0})
    fuori.sort(key=lambda d: -d["diff"])
    return fuori


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

    # Quale de-vig ha DAVVERO prodotto i numeri sotto.
    print(banner("SHIN"))

    rows, absurd, no_close, files, scarti = collect(args.seasons)
    partite = len({r["match"] for r in rows})
    print(f"FILE LETTI={files}   OSSERVAZIONI={len(rows):,}   PARTITE={partite:,}")
    print(f"SCARTATE: CLV assurdo (>{ABSURD_CLV:.0%})={absurd:,}   "
          f"senza chiusura utilizzabile={no_close:,}")
    # Il filtro e' simmetrico in unita' di CLV, ma il CLV non lo e': e'
    # limitato in basso a prezzo_equo-1 e illimitato in alto. In termini di
    # prezzo/prezzo_equo la banda +-0.50 e' [0.5, 1.5], in log [-0.69, +0.41]:
    # il lato perdita e' il 70% piu' largo. Stampare lo split e' l'unico modo
    # perche' quell'asimmetria non resti invisibile dall'output.
    print(f"   di cui sopra +{ABSURD_CLV:.2f}: {scarti['alto']:,}   "
          f"sotto -{ABSURD_CLV:.2f}: {scarti['basso']:,}"
          + (f"   rapporto {scarti['alto'] / scarti['basso']:.1f}:1"
             if scarti["basso"] else ""))
    print(f"CLV medio su TUTTO                      {st.mean(r['clv'] for r in rows):+.4f}")
    print("  (negativo per costruzione: sotto de-vig moltiplicativo vale\n"
          "   l'identita' equa*prezzo = 1/(1+margine), quindi il CLV medio di\n"
          "   un book E' il margine di quel book. Questo numero non misura\n"
          "   efficienza: misura quanto carica il banco.)\n")

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
    header = (f"{'CELLA':22} {'N':>8} {'PARTITE':>8} {'CLV':>9} {'SE':>8} "
              f"{'DEFF':>6} {'t':>7} {'q':>8} {'VINTE':>7}")
    print(header)
    print("-" * len(header))
    for c in cells:
        flag = "  <<<" if c["q"] < 0.10 and c["mean"] > 0 else ""
        print(f"{c['label']:22} {c['n']:8,} {c['partite']:8,} {c['mean']:+9.4f} "
              f"{c['se']:8.4f} {c['deff']:6.1f} {c['t']:+7.2f} {c['q']:8.4f} "
              f"{c['won']:7.1%}{flag}")
    print("\nDEFF = di quanto l'errore standard raggruppato per partita e' piu'")
    print("grande di quello ingenuo, al quadrato. Un DEFF di 9 significa che i t")
    print("dichiarati finora erano gonfiati di tre volte.")

    print("\n" + "=" * 78)
    print("CONTRASTO DENTRO IL BOOK — il margine si cancella, resta la regola.")
    print("Regola: 'questo prezzo era il piu' lungo del mercato', nota al")
    print("momento della decisione. La chiusura valuta, non seleziona.")
    print("=" * 78)
    contrasti = contrasto_dentro_il_book(rows)
    intestazione = (f"{'BOOK':13} {'N MIGLIORE':>11} {'N ALTRI':>9} "
                    f"{'DIFFERENZA':>11} {'SE':>8} {'t':>7}")
    print(intestazione)
    print("-" * len(intestazione))
    for d in contrasti:
        print(f"{d['book']:13} {d['n_best']:11,} {d['n_altri']:9,} "
              f"{d['diff']:+11.4f} {d['se']:8.4f} {d['t']:+7.2f}")
    print("\nUna differenza positiva NON e' un profitto: e' un candidato il cui")
    print("CLV fuori campione non e' mai stato misurato. PROMOTED resta 0.")

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
