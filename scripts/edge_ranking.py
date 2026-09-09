#!/usr/bin/env python3
"""
Ranking per edge teorico. Nessuna scommessa, solo metriche.

Tre book nominati — bet365, il Betfair Exchange e la media di mercato — e per
ciascuno l'EV del suo prezzo sotto il consenso de-viggato DEGLI ALTRI.

PERCHE' NOMINATI E NON "IL MIGLIORE"
------------------------------------
La prima versione di questo motore classificava cinque partite su diciotto
come classe A prendendo il miglior prezzo fra sette book. Misurato sul dato
vero — consenso 0.163, dispersione 0.024, zero inefficienza per costruzione —
il massimo di sette prezzi mostra un edge mediano del +4.0% e supera il +4%
nella meta' dei casi. Quel +5.74% non era un segnale: era la dispersione,
riscritta.

Nominare il book toglie la selezione: non c'e' un massimo da scegliere, quindi
non c'e' nulla da cui essere maledetti. E ogni edge e' confrontato con la
banda nulla calcolata dalla dispersione di QUELLA partita, non con una soglia
fissa decisa a tavolino.

IL BETFAIR EXCHANGE NON E' UN BOOKMAKER
---------------------------------------
E' un mercato fra scommettitori, quindi il suo margine e' molto piu' basso e
la sua probabilita' de-viggata e' il riferimento piu' vicino al prezzo "vero"
che questa fonte offra — il ruolo che avrebbe avuto Pinnacle, che nel file non
c'e'. Ma il prezzo esposto e' al LORDO della commissione: incassarlo significa
prendere meno. La commissione e' applicata qui sotto, perche' un edge del 2%
misurato su un prezzo che ne perde 5 e' un edge negativo.

    python scripts/edge_ranking.py
"""

from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fiorino.market.consensus import SELECTIONS, build_consensus  # noqa: E402
from fiorino.data.ingest.odds_feed.sources import footballdata_fixtures as source  # noqa: E402

#: I tre richiesti. MARKET_AVG e' un aggregato e non vota nel consenso, ma il
#: suo prezzo puo' essere valutato come chiunque altro.
RANKED = ("BET365", "BETFAIR_EX", "MARKET_AVG")

#: Commissione standard dell'exchange sulle vincite nette. Non e' un dettaglio:
#: sposta ogni edge dell'exchange di diversi punti.
EXCHANGE_COMMISSION = 0.05


def net_price(bookmaker: str, price: float) -> float:
    """Prezzo effettivamente incassabile."""
    if bookmaker != "BETFAIR_EX":
        return price
    return 1.0 + (price - 1.0) * (1.0 - EXCHANGE_COMMISSION)


def main() -> int:
    poll = source.fetch()
    if not poll.succeeded:
        print(f"DATA_GAP: {poll.error}")
        return 1

    today = datetime.now(timezone.utc).date()
    by_match: dict[str, list] = {}
    for quote in poll.quotes:
        by_match.setdefault(quote.match_key, []).append(quote)

    rows = []
    skipped_past = 0
    for match_key, quotes in by_match.items():
        div, date, home, away = (match_key.split("|") + ["", "", "", ""])[:4]
        try:
            if datetime.strptime(date, "%d/%m/%Y").date() < today:
                skipped_past += 1
                continue
        except ValueError:
            pass

        consensus = build_consensus(match_key, quotes)
        if consensus is None or consensus.n_books < 5:
            continue
        priced = {q.bookmaker: q for q in quotes}

        for book in RANKED:
            quote = priced.get(book)
            if quote is None:
                continue
            for i, selection in enumerate(SELECTIONS):
                gross = (quote.home, quote.draw, quote.away)[i]
                edge = consensus.edge_leave_one_out(book, i)
                if edge is None:
                    # MARKET_AVG is not in the consensus, so leave-one-out has
                    # nothing to remove: score it against the full consensus.
                    edge = consensus.fair[i] * gross - 1.0
                net = net_price(book, gross)
                edge_net = (edge + 1.0) * (net / gross) - 1.0
                null = consensus.null_edge(i)
                rows.append({
                    "match": f"{home} - {away}", "div": div, "sel": selection,
                    "book": book, "price": gross, "net": net,
                    "edge": edge_net, "null": null,
                    "excess": edge_net - null,
                    "books": consensus.n_books,
                    "disp": consensus.dispersion[i],
                    "margin": consensus.mean_overround,
                })

    rows.sort(key=lambda r: r["excess"], reverse=True)

    print(f"OSSERVATO_ALLE={poll.observed_at.isoformat()}")
    print(f"PARTITE_VALUTATE={len({r['match'] for r in rows})}  "
          f"SCARTATE_GIA_GIOCATE={skipped_past}")
    print(f"COMMISSIONE_EXCHANGE={EXCHANGE_COMMISSION:.0%}\n")
    header = (f"{'PARTITA':34} {'SEL':5} {'BOOK':11} {'QUOTA':>6} {'NETTA':>6} "
              f"{'EDGE':>7} {'NULLO':>7} {'ECCESSO':>8} {'DISP':>6}")
    print(header)
    print("-" * len(header))
    for r in rows[:25]:
        print(f"{r['match'][:34]:34} {r['sel']:5} {r['book']:11} "
              f"{r['price']:6.2f} {r['net']:6.2f} {r['edge']:+7.2%} "
              f"{r['null']:+7.2%} {r['excess']:+8.2%} {r['disp']:6.3f}")

    above = [r for r in rows if r["excess"] > 0]
    print(f"\nRIGHE={len(rows)}   SOPRA_LA_BANDA_NULLA={len(above)} "
          f"({len(above)/len(rows):.0%})" if rows else "\nNESSUNA RIGA")
    print("\nEDGE = EV del prezzo di QUEL book sotto il consenso de-viggato degli")
    print("altri. NULLO = quanto edge produce da sola la dispersione di quella")
    print("partita, al 95mo percentile, con zero inefficienza. ECCESSO e' la")
    print("differenza, ed e' l'unica colonna che significhi qualcosa.")
    print("\nNESSUNA SCOMMESSA. Un eccesso positivo non e' un profitto: e' un")
    print("candidato il cui CLV non e' mai stato misurato. PROMOTED e' vuoto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
