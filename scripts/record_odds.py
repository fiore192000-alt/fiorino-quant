#!/usr/bin/env python3
"""
One poll of the odds recorder. Appends one line to the archive and exits.

    python scripts/record_odds.py            # collect
    python scripts/record_odds.py --verify   # report, write nothing

No token, no account, no secret. The only thing standing between this and a
running collection is the merge onto the default branch, because GitHub lists
workflow_dispatch and fires schedule only for workflows present there.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fiorino.data.ingest.odds_feed.recorder import fold_prices, serialise  # noqa: E402
from fiorino.data.ingest.odds_feed.sources import footballdata_fixtures as source  # noqa: E402

ARCHIVE = pathlib.Path(__file__).resolve().parent.parent / "archive" / "odds"


def verify() -> int:
    """Diagnostics only. Writes nothing and shares no code path with collection."""
    result = source.probe()
    print("VERIFY — nessuna scrittura, nessun archivio.")
    print(f"REQUEST={source.URL}")
    print(f"HTTP_STATUS={result['status']}")

    if result["error"] is not None or result["text"] is None:
        print(f"ERROR={result['error']}")
        print("NOTA=una chiamata fallita non dice che la fonte sia inadatta, "
              "dice che la richiesta non e riuscita. Sono fatti diversi.")
        return 1

    text = result["text"]
    header = text.splitlines()[0] if text else ""
    columns = [c.strip() for c in header.split(",")]
    scope, quotes = source.parse(text)

    by_book: dict[str, int] = {}
    for quote in quotes:
        by_book[quote.bookmaker] = by_book.get(quote.bookmaker, 0) + 1

    print(f"BYTES={len(text)}")
    print(f"COLUMNS={columns}")
    # The first real payload came back dated 08/09/2026 while the poll ran on
    # the 9th: the file is NOT guaranteed to hold only unplayed matches. That
    # matters, because the whole point-in-time claim of this collector rests on
    # observing a price BEFORE kickoff. A price read after kickoff is a stale
    # row, not a prematch observation, and counting them is the difference
    # between knowing that and finding out later.
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date()
    past = 0
    for line in text.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 2 or not parts[1].strip():
            continue
        try:
            when = datetime.strptime(parts[1].strip(), "%d/%m/%Y").date()
        except ValueError:
            continue
        if when < today:
            past += 1

    print(f"FIXTURES_FOUND={len(scope)}")
    print(f"FIXTURES_DATED_BEFORE_TODAY={past}  "
          f"# non sono prematch: il file non contiene solo partite da giocare")
    print(f"FIXTURES_WITH_ANY_PRICE={len({q.match_key for q in quotes})}")
    print(f"FIXTURES_WITHOUT_ANY_PRICE={len(set(scope)) - len({q.match_key for q in quotes})}")
    for book, _ in source.BOOKS:
        # Every configured book is printed, including the absent ones. A book
        # missing from the output would read as "not offered"; a zero here says
        # the column was looked for and was not there.
        print(f"BOOK_{book}={by_book.get(book, 0)}")
    print("SINCE_PREVIOUS_POLL_SECONDS=None  # richiede due poll riusciti")

    if quotes:
        first = quotes[0]
        print(f"FIRST_MATCH_KEY={first.match_key}")
        print(f"FIRST_QUOTE={first.bookmaker} {first.home}/{first.draw}/{first.away}")
    else:
        print("FIRST_MATCH_KEY=")
        print("FIRST_QUOTE=  # nessuna quota completa mappata")

    raw = "\n".join(text.splitlines()[:3])
    print("FIRST_RAW_ROWS=" + raw[:4000])
    if not scope:
        print("# nessuna fixture nel file: puo essere una pausa del calendario. "
              "Non e la stessa cosa di una fonte che non funziona.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    if args.verify:
        return verify()

    poll = source.fetch()
    print(f"poll {poll.observed_at.isoformat()}  fixture={len(poll.scope)}  "
          f"quote={len(poll.quotes)}  errore={poll.error or 'nessuno'}")

    when = poll.observed_at.astimezone(timezone.utc)
    path = ARCHIVE / f"{when:%Y}" / f"{when:%m}" / f"{when:%d}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)

    # Only a CHANGE is a new price. Everything already in today's archive is
    # replayed so an unchanged file appends nothing but the poll itself, which
    # is what keeps the next gap measurable without inventing a flat market.
    previous = []
    if path.exists():
        from fiorino.data.ingest.odds_feed.recorder import deserialise
        previous = [deserialise(line) for line in path.read_text().splitlines() if line]
    before = len(fold_prices(previous))
    after = len(fold_prices(previous + [poll]))

    with path.open("a", encoding="utf-8") as handle:
        handle.write(serialise(poll) + "\n")
    print(f"scritto in {path}  prezzi nuovi in questo poll={after - before}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
