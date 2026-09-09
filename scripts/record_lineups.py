#!/usr/bin/env python3
"""
One poll of the lineup recorder. Appends one line to the archive and exits.

Designed to be run by a scheduler, not by a person: every run is independent,
appends exactly one record, and never rewrites what earlier runs wrote.

    python scripts/record_lineups.py --date 2026-09-10
    python scripts/record_lineups.py --verify        # report, write nothing

WHY THE ARCHIVE IS IN THE REPOSITORY
------------------------------------
The historical bronze dataset is deliberately kept out of git — it is large,
it is downloadable again, and committing it would bury the code. This archive
is the opposite on every count. It is a few kilobytes a day, it can NEVER be
downloaded again, and committing it buys a property no other storage gives:
the commit timestamp is an independent attestation of `observed_at`, made by
GitHub rather than by us. A first-sighting instant that only we vouch for is
worth noticeably less than one a third party dated.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fiorino.data.ingest.lineups.recorder import serialise  # noqa: E402

ARCHIVE = pathlib.Path(__file__).resolve().parent.parent / "archive" / "lineups"
TOKEN_VAR = "SPORTMONKS_TOKEN"


def archive_path(when: datetime) -> pathlib.Path:
    when = when.astimezone(timezone.utc)
    return ARCHIVE / f"{when:%Y}" / f"{when:%m}" / f"{when:%d}.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="YYYY-MM-DD, default today UTC")
    parser.add_argument("--verify", action="store_true",
                        help="report what the source returned; write nothing")
    args = parser.parse_args()

    token = os.environ.get(TOKEN_VAR, "").strip()
    if not token:
        # Not an error. A repository without the secret must stay green: the
        # collection starts the day the token exists, and until then every run
        # says so out loud rather than failing in a way people learn to ignore.
        print(f"{TOKEN_VAR} non impostato: nessuna raccolta. "
              f"Aggiungerlo come secret del repository per far partire l'archivio.")
        return 0

    from fiorino.data.ingest.lineups.sources import sportmonks

    date = args.date or f"{datetime.now(timezone.utc):%Y-%m-%d}"
    poll = sportmonks.fetch(token, date)

    confirmed = len(poll.lineups)
    print(f"poll {poll.observed_at.isoformat()}  data={date}  "
          f"fixture={len(poll.scope)}  undici confermati={confirmed}  "
          f"errore={poll.error or 'nessuno'}")

    if args.verify:
        # The run that does the job this environment could not: it reports the
        # shape the API really returned, so the adapter stops being a guess.
        print("\nVERIFICA — nessuna scrittura.")
        if poll.error:
            print(f"  la chiamata e fallita: {poll.error}")
            print("  questo non dice che la fonte sia inadatta, dice che la")
            print("  richiesta non e riuscita. Vanno distinte.")
            return 1
        print(f"  fixture nella risposta : {len(poll.scope)}")
        print(f"  undici con >= 11 titolari: {confirmed}")
        for lineup in poll.lineups[:4]:
            print(f"    {lineup.match_key} {lineup.team}: "
                  f"{len(lineup.players)} titolari")
        if not poll.scope:
            print("  nessuna fixture per questa data: normale fuori stagione,")
            print("  oppure il piano non copre alcuna competizione oggi.")
        return 0

    path = archive_path(poll.observed_at)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(serialise(poll) + "\n")
    print(f"scritto in {path.relative_to(pathlib.Path.cwd())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
