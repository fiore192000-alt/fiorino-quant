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
import json
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


def verify(token: str, date: str) -> int:
    """Diagnostics only. Writes nothing, archives nothing, and shares no code
    path with the collection: what is printed here can never become a record.

    The output is machine-greppable KEY=VALUE on purpose, so it can be pasted
    whole and read without interpretation.
    """
    from fiorino.data.ingest.lineups.sources import sportmonks

    result = sportmonks.probe(token, date)
    body = result["body"] or {}
    fixtures = body.get("data") or []

    print("VERIFY — nessuna scrittura, nessun archivio.")
    # The endpoint takes a DATE, not a list of fixtures. There is no
    # "requested" count to print, and printing one would invent it.
    print(f"REQUEST=fixtures/date/{date}?include=lineups")
    print(f"HTTP_STATUS={result['status']}")

    if result["error"]:
        print(f"ERROR={sportmonks.redact(str(result['error']), token)}")
        print("NOTA=una chiamata fallita non dice che la fonte sia inadatta, "
              "dice che la richiesta non e riuscita. Sono fatti diversi.")
        return 1

    mapped = {}
    for fixture in fixtures:
        lineups = sportmonks._lineups_from_fixture(fixture)
        if lineups:
            mapped[str(fixture.get("id"))] = lineups

    confirmed = sum(len(v) for v in mapped.values())
    print(f"FIXTURES_FOUND={len(fixtures)}")
    print(f"FIXTURES_WITHOUT_CONFIRMED_LINEUP={len(fixtures) - len(mapped)}")
    print(f"CONFIRMED={confirmed}")
    # Never 0. Zero would claim the adapter looked and found none; it does not
    # look. Absence of evidence is not evidence of absence, which is the same
    # rule SOURCES.json enforces on timestamp quality.
    print("PREDICTED=UNSUPPORTED_BY_ADAPTER")
    # Not simulated, on purpose. The first sighting of all has no previous
    # successful poll to measure back to, so None is the true value and any
    # number here would be invented. It becomes real on the second poll.
    print("KNOWN_AT_UNCERTAINTY_SECONDS=None  # richiede due poll riusciti")

    first = next(iter(mapped.values()), None)
    if first:
        print(f"FIRST_TEAM_ID={first[0].team}")
        print(f"FIRST_PLAYER_IDS={list(first[0].players)[:11]}")
    else:
        print("FIRST_TEAM_ID=  # nessun undici confermato mappato")
        print("FIRST_PLAYER_IDS=[]")

    # The point of the whole exercise: the payload as it really is, so the
    # mapping above can be checked against it instead of trusted.
    if fixtures:
        raw = json.dumps(fixtures[0], indent=2, ensure_ascii=False, sort_keys=True)
        raw = sportmonks.redact(raw, token)
        truncated = len(raw) > 6000
        print("FIRST_RAW_FIXTURE_PAYLOAD=" + raw[:6000])
        if truncated:
            print(f"# payload troncato a 6000 caratteri su {len(raw)}")
    else:
        print("FIRST_RAW_FIXTURE_PAYLOAD={}")
        print("# nessuna fixture per questa data: puo essere fuori stagione, "
              "oppure il piano non copre nessuna competizione oggi. "
              "Non e la stessa cosa di una fonte che non funziona.")
    return 0


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

    if args.verify:
        return verify(token, date)

    poll = sportmonks.fetch(token, date)
    print(f"poll {poll.observed_at.isoformat()}  data={date}  "
          f"fixture={len(poll.scope)}  undici confermati={len(poll.lineups)}  "
          f"errore={poll.error or 'nessuno'}")

    path = archive_path(poll.observed_at)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(serialise(poll) + "\n")
    print(f"scritto in {path.relative_to(pathlib.Path.cwd())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
