#!/usr/bin/env python3
"""
Un pronostico onesto sulle ultime N partite, e quanto vale contro il mercato.

LA REGOLA CHE DECIDE TUTTO
--------------------------
La previsione per la partita N usa SOLO le partite precedenti la N. I rating
si aggiornano dopo che il risultato e' noto, mai prima. Non e' una precauzione
di stile: ieri una selezione che toccava il futuro ha prodotto +0.0440 di CLV
apparente dove il vero valore era -0.0442, e la stessa selezione su rumore
puro dava +0.0702.

Qui la tentazione e' piu' sottile. Basta stimare i rating su tutta la stagione
e poi "valutare" sulle ultime cento partite: quei rating conterrebbero gia' i
risultati che si sta cercando di prevedere, e il modello sembrerebbe ottimo.

IL MODELLO
----------
Attacco e difesa per squadra, aggiornati partita per partita come un Elo sui
gol, piu' un vantaggio casalingo stimato sulle partite gia' viste. Da li' due
tassi di Poisson e la matrice dei punteggi, che si somma in 1X2.

E' deliberatamente semplice. M5 ha gia' misurato che modelli piu' ricchi non
battono il mercato, e un modello complicato qui aggiungerebbe solo modi di
sbagliare senza aggiungere informazione.

I DUE METRI
-----------
Non "il modello e' buono". Il modello CONTRO il mercato, sulle stesse partite:

    chiusura de-viggata   il benchmark vero, cio' che il mercato sapeva alla fine
    apertura de-viggata   cio' che il mercato sapeva quando si poteva scommettere

Un modello che batte il caso ma perde contro l'apertura non ha dimostrato
niente di utilizzabile.

    python scripts/forecast_lab.py --last 100
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
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fiorino.odds.devig import devig  # noqa: E402

UA = "fiorino-quant/1.0 (+research)"
DIVISIONS = ("E0", "E1", "E2", "E3", "SC0", "D1", "D2", "I1", "I2",
             "SP1", "SP2", "F1", "F2", "N1", "B1", "P1", "T1", "G1")
SELECTIONS = ("HOME", "DRAW", "AWAY")
OPEN_COLS = ("AvgH", "AvgD", "AvgA")
CLOSE_COLS = ("AvgCH", "AvgCD", "AvgCA")

#: Quanto un risultato sposta i rating. Basso di proposito: un valore alto
#: insegue il rumore, e con una stagione di dati non c'e' margine per inseguire.
LEARNING_RATE = 0.045
#: Media gol di partenza per una squadra senza storia.
BASE_RATE = 1.35
MAX_GOALS = 8


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
        return None
    if min(prices) <= 1.0:
        return None
    try:
        return tuple(devig(list(SELECTIONS), prices, "SHIN").fair_probs)
    except ValueError:
        return None


def load(seasons):
    """Tutte le partite, ordinate nel tempo. L'ordine e' il punto."""
    out = []
    for season in seasons:
        for division in DIVISIONS:
            text = fetch(season, division)
            if not text:
                continue
            for raw in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
                if raw.get("FTR") not in ("H", "D", "A"):
                    continue
                try:
                    when = datetime.strptime(raw["Date"].strip(), "%d/%m/%Y")
                    hg, ag = int(raw["FTHG"]), int(raw["FTAG"])
                except (KeyError, TypeError, ValueError):
                    continue
                out.append({
                    "when": when, "div": division, "season": season,
                    "home": raw["HomeTeam"], "away": raw["AwayTeam"],
                    "hg": hg, "ag": ag,
                    "outcome": {"H": 0, "D": 1, "A": 2}[raw["FTR"]],
                    "open": fair(raw, OPEN_COLS),
                    "close": fair(raw, CLOSE_COLS),
                })
    out.sort(key=lambda r: (r["when"], r["div"], r["home"]))
    return out


def poisson_1x2(mu_home: float, mu_away: float) -> tuple[float, float, float]:
    """Matrice dei punteggi sommata in 1X2, indipendenza fra i due tassi."""
    ph = [math.exp(-mu_home) * mu_home ** k / math.factorial(k)
          for k in range(MAX_GOALS + 1)]
    pa = [math.exp(-mu_away) * mu_away ** k / math.factorial(k)
          for k in range(MAX_GOALS + 1)]
    home = draw = away = 0.0
    for i, a in enumerate(ph):
        for j, b in enumerate(pa):
            p = a * b
            if i > j:
                home += p
            elif i == j:
                draw += p
            else:
                away += p
    total = home + draw + away
    return home / total, draw / total, away / total


def walk_forward(matches):
    """Una previsione per partita, con rating che NON hanno mai visto quella
    partita ne' alcuna successiva."""
    attack: dict[str, float] = {}
    defence: dict[str, float] = {}
    seen_home_goals, seen_away_goals, seen = 0.0, 0.0, 0

    for m in matches:
        home, away = m["home"], m["away"]
        for team in (home, away):
            attack.setdefault(team, 0.0)
            defence.setdefault(team, 0.0)

        # Vantaggio casalingo dalle sole partite gia' viste.
        if seen >= 50:
            home_rate = seen_home_goals / seen
            away_rate = seen_away_goals / seen
        else:
            home_rate = away_rate = BASE_RATE

        mu_home = max(0.15, home_rate * math.exp(attack[home] - defence[away]))
        mu_away = max(0.15, away_rate * math.exp(attack[away] - defence[home]))
        m["model"] = poisson_1x2(mu_home, mu_away)
        m["n_prior"] = seen

        # SOLO ORA il risultato entra nei rating.
        err_home = m["hg"] - mu_home
        err_away = m["ag"] - mu_away
        attack[home] += LEARNING_RATE * err_home / max(mu_home, 0.5)
        defence[away] -= LEARNING_RATE * err_home / max(mu_home, 0.5)
        attack[away] += LEARNING_RATE * err_away / max(mu_away, 0.5)
        defence[home] -= LEARNING_RATE * err_away / max(mu_away, 0.5)
        seen_home_goals += m["hg"]
        seen_away_goals += m["ag"]
        seen += 1
    return matches


def brier(probs, outcome):
    return sum((p - (1.0 if i == outcome else 0.0)) ** 2
               for i, p in enumerate(probs)) / 3


def logloss(probs, outcome):
    return -math.log(max(probs[outcome], 1e-9))


def score(rows, key):
    usable = [r for r in rows if r.get(key)]
    if not usable:
        return None
    return {
        "n": len(usable),
        "brier": st.mean(brier(r[key], r["outcome"]) for r in usable),
        "logloss": st.mean(logloss(r[key], r["outcome"]) for r in usable),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--last", type=int, default=100)
    parser.add_argument("--seasons", nargs="+", default=["2526", "2627"])
    args = parser.parse_args()

    matches = walk_forward(load(args.seasons))
    print(f"PARTITE CARICATE={len(matches):,}  stagioni={' '.join(args.seasons)}")

    # Le ultime N con TUTTI e tre i numeri, altrimenti il confronto e' sbilenco.
    complete = [m for m in matches if m["model"] and m["open"] and m["close"]]
    tail = complete[-args.last:]
    print(f"VALUTATE={len(tail)}  dal {tail[0]['when']:%d/%m/%Y} "
          f"al {tail[-1]['when']:%d/%m/%Y}")
    print(f"partite viste dal modello prima della prima valutata: "
          f"{tail[0]['n_prior']:,}\n")

    header = f"{'PREVISORE':24} {'N':>5} {'BRIER':>9} {'LOG LOSS':>10}"
    print(header)
    print("-" * len(header))
    rows = []
    for label, key in (("modello (walk-forward)", "model"),
                       ("mercato, apertura", "open"),
                       ("mercato, chiusura", "close")):
        s = score(tail, key)
        rows.append((label, s))
        print(f"{label:24} {s['n']:5} {s['brier']:9.5f} {s['logloss']:10.5f}")

    model, open_, close = (r[1] for r in rows)
    print(f"\nMODELLO - APERTURA   Brier {model['brier'] - open_['brier']:+.5f}"
          f"   log loss {model['logloss'] - open_['logloss']:+.5f}")
    print(f"MODELLO - CHIUSURA   Brier {model['brier'] - close['brier']:+.5f}"
          f"   log loss {model['logloss'] - close['logloss']:+.5f}")
    print("(positivo = il modello e PEGGIO: il Brier basso e meglio)")

    # L'andamento: blocchi da 20, per vedere se migliora o e' piatto.
    print(f"\nANDAMENTO, blocchi da 20")
    print(f"{'blocco':10} {'modello':>10} {'apertura':>10} {'divario':>10}")
    block = 20
    for start in range(0, len(tail), block):
        chunk = tail[start:start + block]
        if len(chunk) < block // 2:
            continue
        m = score(chunk, "model")
        o = score(chunk, "open")
        print(f"{start+1:3}-{start+len(chunk):<6} {m['brier']:10.5f} "
              f"{o['brier']:10.5f} {m['brier']-o['brier']:+10.5f}")

    better = sum(1 for m in tail
                 if brier(m["model"], m["outcome"]) < brier(m["open"], m["outcome"]))
    print(f"\npartite in cui il modello batte l'apertura: {better}/{len(tail)} "
          f"({better/len(tail):.0%})")
    print("\nNESSUNA SCOMMESSA. Un modello che perde contro l'apertura non")
    print("produce un pronostico utilizzabile, per quanto sia bello guardarlo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
