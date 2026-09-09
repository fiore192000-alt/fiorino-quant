"""
The odds recorder: the same discipline as the lineup recorder, applied to price.

WHY IT IS SEPARATE FROM THE HISTORICAL INGEST
---------------------------------------------
`sources/footballdata.py` reads seasons that have already finished. Every price
in them is delivered after the result, so `capture_precision` is PREMATCH or
CLOSING and `captured_at` is NULL — there is no instant to record, and M2
refused to invent one.

This path is the opposite. It reads a file of matches that have NOT been played
and it reads it at a moment we can name. That makes `captured_at` a real
instant, and these are therefore the **first TIMESTAMPED prices in the
project** — the ones the four `v_market_*` views have been waiting for while
returning zero rows.

WHAT observed_at MEANS, PRECISELY
---------------------------------
The instant OUR fetch read that price. Not when the bookmaker set it, which
the file does not say and we cannot audit. As with lineups this is an upper
bound — the price was on offer at or before this instant — and the bound is
only safe if its width travels with it.

THE FILE MOVES SLOWER THAN THE POLLS
------------------------------------
Football-Data collects odds for weekend fixtures on Fridays and for midweek
fixtures on Tuesdays. So most polls will read a file that has not changed, and
recording every one as a fresh price would fill `v_market_path` with flat
segments that look like a market standing still when in truth nobody looked.

Hence the split kept here and in the archive:

    every poll        is recorded  — it is what makes the next gap measurable
    only a CHANGE     becomes an observation of a new price

That is the same shape as `fold_sightings`: the poll stream is the evidence,
the folded result is the fact.

WHAT THIS SOURCE CANNOT DO
--------------------------
It gives one or two prematch points per match, not a path. It cannot answer
anything about micro-structure, about how fast a market moved, or about who
moved first. Those need a real feed. What it can do is put a genuine Pinnacle
prematch price, with a real instant, next to a match that has not been played.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

__all__ = ["Quote", "OddsPoll", "PriceObservation", "fold_prices",
           "serialise", "deserialise", "utcnow"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Quote:
    """One bookmaker's 1X2 prices for one unplayed match, as one poll read it."""

    match_key: str
    bookmaker: str
    home: float
    draw: float
    away: float

    def digest(self) -> str:
        payload = json.dumps(
            [self.match_key, self.bookmaker,
             round(self.home, 4), round(self.draw, 4), round(self.away, 4)],
            separators=(",", ":"),
        )
        return hashlib.blake2b(payload.encode(), digest_size=12).hexdigest()


@dataclass(frozen=True)
class OddsPoll:
    source: str
    observed_at: datetime
    scope: tuple[str, ...]
    quotes: tuple[Quote, ...] = ()
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass
class PriceObservation:
    """A price, and the instant we can prove we saw it."""

    match_key: str
    bookmaker: str
    home: float
    draw: float
    away: float
    source: str
    observed_at: datetime
    #: How far back the previous successful poll covering this match was. None
    #: means no earlier poll covered it, so this price may have stood for a
    #: long time before anyone looked — never zero, which would be the most
    #: confident possible claim from the least evidence.
    since_previous_poll_seconds: float | None
    #: True for the first time we ever saw this match priced; False for a
    #: subsequent change. The distinction matters because only the second kind
    #: is a market MOVE — the first is just the moment we arrived.
    is_first_sighting: bool


def fold_prices(polls) -> list[PriceObservation]:
    """Reduce a poll stream to the moments a price actually changed.

    A poll that reads an unchanged file is not a new price. It is evidence that
    the price still stood, which matters for the NEXT gap and for nothing else.
    Recording it as an observation would manufacture a market that never moved
    out of a collector that merely kept looking.
    """
    ordered = sorted(polls, key=lambda p: p.observed_at)
    last_success: dict[str, datetime] = {}
    last_digest: dict[tuple[str, str], str] = {}
    out: list[PriceObservation] = []

    for poll in ordered:
        for quote in poll.quotes:
            key = (quote.match_key, quote.bookmaker)
            digest = quote.digest()
            if last_digest.get(key) == digest:
                continue
            previous = last_success.get(quote.match_key)
            out.append(PriceObservation(
                match_key=quote.match_key, bookmaker=quote.bookmaker,
                home=quote.home, draw=quote.draw, away=quote.away,
                source=poll.source, observed_at=poll.observed_at,
                since_previous_poll_seconds=(
                    (poll.observed_at - previous).total_seconds()
                    if previous is not None else None
                ),
                is_first_sighting=key not in last_digest,
            ))
            last_digest[key] = digest

        if poll.succeeded:
            for match_key in poll.scope:
                last_success[match_key] = poll.observed_at

    return out


def serialise(poll: OddsPoll) -> str:
    return json.dumps({
        "source": poll.source,
        "observed_at": poll.observed_at.astimezone(timezone.utc).isoformat(),
        "scope": list(poll.scope),
        "error": poll.error,
        "quotes": [asdict(q) for q in poll.quotes],
    }, sort_keys=True, separators=(",", ":"))


def deserialise(line: str) -> OddsPoll:
    raw = json.loads(line)
    return OddsPoll(
        source=raw["source"],
        observed_at=datetime.fromisoformat(raw["observed_at"]),
        scope=tuple(raw.get("scope", ())),
        quotes=tuple(Quote(**q) for q in raw.get("quotes", ())),
        error=raw.get("error"),
    )
