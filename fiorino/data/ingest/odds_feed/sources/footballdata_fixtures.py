"""
football-data.co.uk/fixtures.csv — matches that have not been played yet.

WHY THIS SOURCE AND NOT A SCRAPER
---------------------------------
It is a file the site publishes for download, not a page anyone has to scrape,
so it raises none of the questions that keep OddsPortal classified as
unverified. It is free, it has been published the same way for two decades, and
it carries the column convention the rest of this project already reads.

And it carries **Pinnacle** (`PSH/PSD/PSA`) alongside bet365, which matters
more than it looks: Pinnacle's de-vigged close is the benchmark M3, M5 and M6
are all measured against. A prematch Pinnacle price with a real instant on an
unplayed match is the first row of the dataset that was missing.

WHAT IS NOT VERIFIED
--------------------
The column list below comes from Football-Data's own published notes, read from
a mirror, and from the fact that its client libraries parse the fixtures file
with the same names. **No request has ever been made to fixtures.csv from
here** — the domain is blocked by this environment's egress policy — so it is
possible the fixtures file carries fewer columns than a season file.

That is exactly what `scripts/record_odds.py --verify` is for, and why the
first scheduled run should be a verification. Nothing here guesses a price: a
row whose 1X2 is incomplete is skipped and counted, never normalised.
"""

from __future__ import annotations

import csv
import io
import urllib.error
import urllib.request

from fiorino.data.ingest.odds_feed.recorder import OddsPoll, Quote, utcnow

URL = "https://www.football-data.co.uk/fixtures.csv"
TIMEOUT = 60

#: Bookmaker column triples, in the order we prefer them. Pinnacle first: it is
#: the book the rest of the project benchmarks against, and the only one whose
#: prematch price is worth much on its own.
BOOKS = (
    ("PINNACLE", ("PSH", "PSD", "PSA")),
    ("BET365", ("B365H", "B365D", "B365A")),
    ("WILLIAM_HILL", ("WHH", "WHD", "WHA")),
    ("MARKET_MAX", ("MaxH", "MaxD", "MaxA")),
    ("MARKET_AVG", ("AvgH", "AvgD", "AvgA")),
)


def match_key(row: dict) -> str:
    """Identity from the fields the file actually guarantees.

    Deliberately NOT a fuzzy team match. Rule 9 holds here too: this key is
    used to group polls of the same fixture over time, and resolving it to a
    canonical match happens later, through the same adjudicated path every
    other source uses, or not at all.
    """
    return "|".join(str(row.get(f, "")).strip()
                    for f in ("Div", "Date", "HomeTeam", "AwayTeam"))


def quotes_from_row(row: dict) -> list[Quote]:
    """Every complete 1X2 in one fixture row. An incomplete one is skipped."""
    key = match_key(row)
    if not row.get("HomeTeam") or not row.get("AwayTeam"):
        return []
    found = []
    for book, (h, d, a) in BOOKS:
        try:
            home, draw, away = float(row[h]), float(row[d]), float(row[a])
        except (KeyError, TypeError, ValueError):
            continue
        # A price at or below evens on all three, or any non-positive price, is
        # not a market. Normalising it would produce a confident number that
        # nothing downstream could tell from a real one.
        if min(home, draw, away) <= 1.0:
            continue
        found.append(Quote(match_key=key, bookmaker=book,
                           home=home, draw=draw, away=away))
    return found


def parse(text: str) -> tuple[tuple[str, ...], list[Quote]]:
    reader = csv.DictReader(io.StringIO(text))
    scope, quotes = [], []
    for row in reader:
        if not row.get("HomeTeam"):
            continue
        scope.append(match_key(row))
        quotes.extend(quotes_from_row(row))
    return tuple(scope), quotes


def probe() -> dict:
    """A raw read whose only purpose is to be looked at. No collection path."""
    request = urllib.request.Request(
        URL, headers={"User-Agent": "fiorino-quant/1.0 (+research)"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {"status": response.status, "text": body, "error": None}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "text": None,
                "error": exc.read().decode(errors="replace")[:2000]}
    except Exception as exc:  # noqa: BLE001
        return {"status": None, "text": None,
                "error": f"{type(exc).__name__}: {exc}"}


def fetch() -> OddsPoll:
    """One poll. A failure is captured, not raised: an unwritten failed poll
    would silently narrow the next observation's gap."""
    observed_at = utcnow()
    result = probe()
    if result["error"] is not None or result["text"] is None:
        return OddsPoll(source="footballdata-fixtures", observed_at=observed_at,
                        scope=(), error=str(result["error"]))
    scope, quotes = parse(result["text"])
    return OddsPoll(source="footballdata-fixtures", observed_at=observed_at,
                    scope=scope, quotes=tuple(quotes))


__all__ = ["URL", "BOOKS", "fetch", "probe", "parse", "quotes_from_row", "match_key"]
