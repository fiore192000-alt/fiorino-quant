#!/usr/bin/env python3
"""
The evidence engine: one card per match, and a refusal wherever the evidence
does not reach.

The card answers the nine questions it can answer and says DATA_GAP on the rest.
A DATA_GAP is not a weak answer, it is a different kind of statement: "I could
not evaluate this" is not "I evaluated this and found nothing", and putting the
two on one scale is how a missing price comes to read as a measured absence of
edge.

    python scripts/evidence_cards.py
"""

from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fiorino.decision.signal import PROMOTED  # noqa: E402
from fiorino.market.consensus import SELECTIONS, build_consensus  # noqa: E402
from fiorino.data.ingest.odds_feed.sources import footballdata_fixtures as source  # noqa: E402

#: Below this, the best price does not stand meaningfully away from the rest of
#: the market and the difference is inside what rounding and stale lines
#: explain. Configurable on purpose: it is a threshold, not a discovery.
EDGE_THRESHOLD = 0.02
#: Fewer books than this is not a consensus worth disagreeing with.
MIN_BOOKS = 5


def classify(consensus, best_edge, kicked_off) -> tuple[str, str]:
    """A, B, C or D, and the reason in one line.

    D wins over everything. A card missing an input is not a card with a weak
    signal, and the ordering here is the whole point of the classification.
    """
    if consensus is None:
        return "D", "meno di due book quotati: nessun consenso da cui dissentire"
    if kicked_off:
        return "D", "partita gia iniziata: un prezzo letto dopo il fischio non e prematch"
    if consensus.n_books < MIN_BOOKS:
        return "D", f"solo {consensus.n_books} book: consenso troppo sottile"
    if best_edge is None:
        return "D", "nessun prezzo valutabile"
    if best_edge < EDGE_THRESHOLD:
        return "C", (f"il miglior prezzo non si stacca dal consenso "
                     f"({best_edge:+.2%} < {EDGE_THRESHOLD:.0%})")
    # Above the threshold. It is still not a bet: no signal family in this
    # project has ever shown replicated positive CLV, and PROMOTED is the
    # register that would say otherwise.
    level = "A" if best_edge >= 2 * EDGE_THRESHOLD else "B"
    return level, (f"il miglior prezzo paga {best_edge:+.2%} sopra il consenso "
                   f"di {consensus.n_books} book")


def main() -> int:
    poll = source.fetch()
    if not poll.succeeded:
        print(f"DATA_GAP: {poll.error}")
        return 1

    today = datetime.now(timezone.utc).date()
    by_match: dict[str, list] = {}
    for quote in poll.quotes:
        by_match.setdefault(quote.match_key, []).append(quote)

    print(f"OSSERVATO_ALLE={poll.observed_at.isoformat()}  # istante di lettura, "
          f"non di fissazione del prezzo")
    print(f"PARTITE={len(by_match)}   FONTE={poll.source}\n")

    buckets = {"A": 0, "B": 0, "C": 0, "D": 0}

    for match_key, quotes in sorted(by_match.items()):
        div, date, home, away = (match_key.split("|") + ["", "", "", ""])[:4]
        try:
            kicked_off = datetime.strptime(date, "%d/%m/%Y").date() < today
        except ValueError:
            kicked_off = False

        consensus = build_consensus(match_key, quotes)
        best_edge, best_sel = None, None
        if consensus is not None:
            edges = [consensus.edge_vs_consensus(i) for i in range(3)]
            best_edge = max(edges)
            best_sel = SELECTIONS[edges.index(best_edge)]

        grade, reason = classify(consensus, best_edge, kicked_off)
        buckets[grade] += 1

        print("=" * 74)
        print(f"MATCH                 {home} - {away}   [{div or '?'} {date}]")
        print("MERCATO               1X2")
        if consensus is None:
            print("PROBABILITA MERCATO   DATA_GAP")
            print("CONSENSO BOOKMAKER    DATA_GAP")
        else:
            print("PROBABILITA MERCATO   " + "  ".join(
                f"{s} {p:.3f}" for s, p in zip(SELECTIONS, consensus.fair)))
            print(f"CONSENSO BOOKMAKER    {consensus.n_books} book, "
                  f"dispersione " + " ".join(f"{d:.3f}" for d in consensus.dispersion))
            print(f"MARGINE MEDIO         {consensus.mean_overround:.4f}")
            print(f"MIGLIOR PREZZO        " + "  ".join(
                f"{s} {p:.2f} ({b})" for s, p, b
                in zip(SELECTIONS, consensus.best_price, consensus.best_book)))
        # The model is not consulted. It loses to the market in ten datasets
        # out of ten and adds nothing incremental in any of them, so printing
        # its probability beside the market's would invite the exact comparison
        # M6 showed to be worthless.
        print("PROBABILITA MODELLO   DATA_GAP  # il modello non e usato: M6 dice "
              "che non aggiunge informazione")
        if best_edge is None:
            print("EDGE %                DATA_GAP")
        else:
            print(f"EDGE %                {best_edge:+.2%} su {best_sel}  "
                  f"# miglior prezzo contro il consenso, NON contro un modello")
        print("MOVIMENTO QUOTE       DATA_GAP  # serve un secondo poll")
        print("CLV ATTESO            DATA_GAP  # nessuna linea di chiusura per "
              "una partita non giocata")
        gaps = []
        if consensus and consensus.refused:
            gaps.append(f"{len(consensus.refused)} book rifiutati dal de-vig")
        if kicked_off:
            gaps.append("data precedente a oggi")
        print(f"QUALITA DATI          {'; '.join(gaps) if gaps else 'nessun buco rilevato'}")
        print(f"RISCHIO               nessuna famiglia di segnale promossa "
              f"(PROMOTED vuoto): CLV storico ignoto")
        print(f"MOTIVO DEL SEGNALE    {reason}")
        print(f"CLASSE                {grade}")

    print("\n" + "=" * 74)
    print(f"A={buckets['A']}  B={buckets['B']}  C={buckets['C']}  D={buckets['D']}")
    print(f"FAMIGLIE PROMOSSE={len(PROMOTED)}")
    print("\nNESSUNA SCOMMESSA PROPOSTA. Una classe A dice che il miglior prezzo")
    print("si stacca dal consenso, non che sia redditizio: il CLV di questo")
    print("segnale non e mai stato misurato, e finche PROMOTED e vuoto il")
    print("motore non puo restituire niente sopra WATCH.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
