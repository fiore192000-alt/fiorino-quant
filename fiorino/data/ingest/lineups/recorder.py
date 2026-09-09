"""
The lineup recorder: the one asset in this project that grows by waiting.

WHY THIS EXISTS
---------------
Every other input Fiorino Quant needs can be bought, downloaded or scraped
after the fact. The instant a starting eleven became public cannot. The audit
of free sources found no dataset, paid or free, that carries it: the lineup
datasets that exist (StatsBomb, schochastics, the WhoScored and SofaScore
scrapers) all record WHAT the eleven was, never WHEN it became knowable.

So it exists only if someone writes it down while it happens. Starting six
months late costs six months that never come back.

WHAT `known_at` IS, AND WHAT IT IS NOT
--------------------------------------
A poller cannot observe a publication. It observes its own successful read.
So `known_at` here means, always and only:

    the instant OUR poll first saw a CONFIRMED eleven for this match

It is never the source's claimed publication time, which is a number the
source can compute however it likes and which this project has no way to
audit. Taking it would be the same error as reading `from_date` off a
Transfermarkt injury row: a fact backdated by someone else, adopted as if we
had known it then.

Being a first SIGHTING rather than a publication makes it an UPPER BOUND: the
eleven was public at or before this instant. That is the safe direction — a
fact stamped later than it truly became knowable can never leak information
backwards — but it is only safe if the size of the bound travels with it.

THE UNCERTAINTY IS PART OF THE MEASUREMENT
------------------------------------------
If the previous poll for a match ran 15 minutes before the sighting, then all
that is known is "somewhere in those 15 minutes". Record that, because the
question this dataset is being collected for — what did the market do in the
minutes after the eleven appeared — cannot be asked at all when the
uncertainty is as wide as the window being measured.

That is why `known_at_uncertainty_seconds` is computed from the ACTUAL gap
between consecutive polls and never from the intended schedule. Scheduled
GitHub Actions runs are delayed under load, sometimes by many minutes; a
cadence declared in a cron expression is an intention, not an observation.

A poll that finds nothing is therefore evidence and is recorded too: it is
what makes the previous gap measurable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

__all__ = [
    "Sighting", "Poll", "Lineup", "CONFIRMED", "PREDICTED",
    "fold_sightings", "serialise", "deserialise", "utcnow",
]

#: The official eleven. Only this can set known_at.
CONFIRMED = "CONFIRMED"
#: A forecast OF the official eleven. A different fact, published earlier by
#: different people for different reasons, and never a substitute.
PREDICTED = "PREDICTED"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Lineup:
    """One team's eleven as a single source reported it at one moment."""

    match_key: str
    team: str
    status: str
    players: tuple[str, ...]

    def digest(self) -> str:
        """Stable identity of the CONTENT, so a re-publication with a changed
        eleven is a new fact rather than a duplicate of the old one."""
        payload = json.dumps(
            {"match": self.match_key, "team": self.team,
             "status": self.status, "players": sorted(self.players)},
            sort_keys=True, separators=(",", ":"),
        )
        return hashlib.blake2b(payload.encode(), digest_size=12).hexdigest()


@dataclass(frozen=True)
class Poll:
    """One execution of the collector against one source.

    `scope` says what the poll actually looked at. A poll that covered only
    today's fixtures says nothing about tomorrow's, and treating it as a gap
    closer for a match it never requested would understate the uncertainty on
    that match.
    """

    source: str
    observed_at: datetime
    scope: tuple[str, ...]
    lineups: tuple[Lineup, ...] = ()
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass
class Sighting:
    """The recorder's output for one (match, team): when we first saw it."""

    match_key: str
    team: str
    source: str
    known_at: datetime
    known_at_uncertainty_seconds: float | None
    status: str
    players: tuple[str, ...] = ()
    digest: str = ""
    superseded_by: list[dict] = field(default_factory=list)

    def usable_for_window(self, seconds: float) -> bool:
        """Whether this sighting can support a question about a window of the
        given length. An unknown uncertainty is never usable: it is the case
        where no earlier poll covered this match, so the eleven may have been
        public for hours before the collector ever looked."""
        if self.known_at_uncertainty_seconds is None:
            return False
        return self.known_at_uncertainty_seconds <= seconds


def fold_sightings(polls) -> list[Sighting]:
    """Reduce a stream of polls into one first-CONFIRMED-sighting per team.

    Rules, each of which exists because its absence produces a plausible and
    wrong number:

    - Only CONFIRMED sets `known_at`. A PREDICTED eleven seen at 14:00 for a
      match whose real eleven appears at 18:59 would otherwise move the instant
      five hours earlier and turn a market move into a non-event.
    - The uncertainty is the gap back to the previous SUCCESSFUL poll whose
      scope included this match. A failed poll closes no gap: not looking and
      looking without success are the same amount of evidence, which is none.
    - A later CONFIRMED eleven with different content does not overwrite the
      first. Teams do republish — a late withdrawal in the warm-up — and the
      first sighting stays the answer to "when did this become knowable",
      while the revision is kept beside it rather than thrown away.
    """
    ordered = sorted(polls, key=lambda p: p.observed_at)
    last_success: dict[str, datetime] = {}
    out: dict[tuple[str, str], Sighting] = {}

    for poll in ordered:
        seen_now = {(l.match_key, l.team) for l in poll.lineups
                    if l.status == CONFIRMED}

        for lineup in poll.lineups:
            if lineup.status != CONFIRMED:
                continue
            key = (lineup.match_key, lineup.team)
            if key in out:
                existing = out[key]
                if lineup.digest() != existing.digest:
                    existing.superseded_by.append({
                        "observed_at": poll.observed_at.isoformat(),
                        "digest": lineup.digest(),
                        "players": list(lineup.players),
                    })
                continue

            previous = last_success.get(lineup.match_key)
            uncertainty = (
                (poll.observed_at - previous).total_seconds()
                if previous is not None else None
            )
            out[key] = Sighting(
                match_key=lineup.match_key, team=lineup.team, source=poll.source,
                known_at=poll.observed_at,
                known_at_uncertainty_seconds=uncertainty,
                status=CONFIRMED, players=tuple(lineup.players),
                digest=lineup.digest(),
            )

        # Recorded AFTER the sightings above, so a match first seen in this
        # very poll measures its gap back to the previous one, not to itself.
        if poll.succeeded:
            for match_key in poll.scope:
                last_success[match_key] = poll.observed_at
            for match_key, _ in seen_now:
                last_success[match_key] = poll.observed_at

    return sorted(out.values(), key=lambda s: (s.known_at, s.match_key, s.team))


def serialise(poll: Poll) -> str:
    """One JSON object per line. The archive is append-only by construction:
    a poll is a fact about a moment and is never edited afterwards."""
    return json.dumps({
        "source": poll.source,
        "observed_at": poll.observed_at.astimezone(timezone.utc).isoformat(),
        "scope": list(poll.scope),
        "error": poll.error,
        "lineups": [asdict(l) | {"players": list(l.players)} for l in poll.lineups],
    }, sort_keys=True, separators=(",", ":"))


def deserialise(line: str) -> Poll:
    raw = json.loads(line)
    return Poll(
        source=raw["source"],
        observed_at=datetime.fromisoformat(raw["observed_at"]),
        scope=tuple(raw.get("scope", ())),
        lineups=tuple(
            Lineup(match_key=l["match_key"], team=l["team"], status=l["status"],
                   players=tuple(l["players"]))
            for l in raw.get("lineups", ())
        ),
        error=raw.get("error"),
    )
