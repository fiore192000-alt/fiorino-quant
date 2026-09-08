"""
Source protocol and the bronze -> silver transform.

An adapter's only job is to turn whatever a source emits into `RawMatch`
records and land them in bronze. Everything downstream — identity, canonical
ids, quarantine, merging — happens once, here, so a new source cannot invent
its own rules.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Iterable, Protocol

__all__ = ["RawMatch", "Source", "SOURCE_FIELDS"]


@dataclass(frozen=True)
class RawMatch:
    """One match as a source describes it, before any interpretation.

    Team names are raw strings on purpose: resolving them is not the adapter's
    business, and storing the raw form is what makes a rebuild able to correct
    an identity mistake without re-fetching.
    """

    source: str
    source_id: str
    competition: str
    season: str
    match_date: str          # ISO date, UTC
    kickoff_utc: str | None  # ISO timestamp when the source provides one
    home_name_raw: str
    away_name_raw: str
    goals_home: str | None
    goals_away: str | None
    goals_home_ht: str | None = None
    goals_away_ht: str | None = None
    home_source_id: str | None = None
    away_source_id: str | None = None
    neutral_venue: str | None = None
    result_settled_at: str | None = None
    ingested_at: str | None = None

    def as_row(self) -> dict:
        row = asdict(self)
        if row["ingested_at"] is None:
            row["ingested_at"] = datetime.now(timezone.utc).isoformat()
        return row


SOURCE_FIELDS = tuple(RawMatch.__dataclass_fields__.keys())


class Source(Protocol):
    """What every ingestion adapter must provide."""

    name: str
    country_of: dict          # competition_id -> country
    supports: frozenset       # competition_ids this source actually covers

    def fetch(self, competition_id: str, season_id: str) -> Iterable[RawMatch]:
        """Yield raw matches. May hit the network; never called in tests."""
        ...


def parse_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def parse_ts(value, fallback_date: date) -> datetime:
    """Kickoff instant, defaulting to 15:00 UTC when a source omits the time."""
    if value in (None, "", "None"):
        return datetime.combine(fallback_date, datetime.min.time()).replace(
            hour=15, tzinfo=timezone.utc
        )
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
