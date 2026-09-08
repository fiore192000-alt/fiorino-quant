"""
Source protocol and the bronze -> silver transform.

An adapter's only job is to turn whatever a source emits into `RawMatch`
records and land them in bronze. Everything downstream — identity, canonical
ids, quarantine, merging — happens once, here, so a new source cannot invent
its own rules.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Protocol

__all__ = ["RawMatch", "Source", "SOURCE_FIELDS", "KICKOFF_PRECISION", "settle_instant"]

#: Sources disagree about what a kickoff timestamp means. Rather than pretend
#: otherwise, each adapter declares its precision and settlement is widened to
#: match. Erring late costs a little training data; erring early is leakage.
#:
#:   EXACT        a real UTC instant             -> kickoff + 2h
#:   LOCAL_APPROX local wall clock, zone unknown -> end of match day + 4h
#:   DATE_ONLY    no time at all                 -> end of match day + 4h
KICKOFF_PRECISION = frozenset({"EXACT", "LOCAL_APPROX", "DATE_ONLY"})


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
    #: How much the source's kickoff can be trusted. Not cosmetic: settled_at
    #: is derived from kickoff, and a kickoff that is two hours early makes a
    #: result visible two hours before it was knowable, which is a rule R1
    #: violation. See KICKOFF_PRECISION.
    kickoff_precision: str = "EXACT"

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


def settle_instant(kickoff: datetime, match_day: date, precision: str) -> datetime:
    """When a result becomes knowable, given how much the kickoff can be trusted.

    Deliberately conservative for imprecise sources: openfootball publishes a
    local wall-clock time with no zone, so a Lisbon 20:00 and a Berlin 20:00 are
    two different instants. Anchoring to the end of the match day plus a margin
    is provably non-leaking, at the cost of making some results visible a few
    hours later than they truly were.
    """
    if precision == "EXACT":
        return kickoff + timedelta(hours=2)
    if precision in ("LOCAL_APPROX", "DATE_ONLY"):
        end_of_day = datetime.combine(match_day, time(23, 59), tzinfo=timezone.utc)
        return end_of_day + timedelta(hours=4)
    raise ValueError(f"unknown kickoff precision: {precision!r}")
