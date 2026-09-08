"""
Deterministic and surrogate identifiers.

Two kinds, and the difference matters:

* ``team_id`` is an OPAQUE SURROGATE. It is minted once and never derived from
  anything that can change. Deriving it from the name would break on the first
  rename and take every historical foreign key with it.

* ``match_id`` is DETERMINISTIC, so that the same match ingested from four
  sources converges on one row without a reconciliation step.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date

__all__ = ["new_team_id", "match_id", "run_id", "proposal_id", "override_id", "quarantine_id"]


def _digest(*parts: str, size: int = 12) -> str:
    joined = "|".join(parts)
    return hashlib.blake2b(joined.encode("utf-8"), digest_size=size).hexdigest()


def new_team_id() -> str:
    """Mint an opaque team identifier. Random by design, never derived."""
    return "t_" + uuid.uuid4().hex[:12]


def match_id(
    competition_id: str, season_id: str, match_date_utc: date, home_team_id: str, away_team_id: str
) -> str:
    """Deterministic match identifier.

    Built from the match DATE, not the kickoff instant. Sources correct kickoff
    times routinely — a 15:00 listing becomes 15:15, or a local time is later
    fixed to UTC — and hashing the instant would mint a fresh match every time
    that happened. The date is the stable component; the exact kickoff is a
    mutable attribute of the row.

    Corrections that cross a date boundary (a genuine postponement) do produce
    a new id, and are reconciled through ``match_merges`` rather than silently.
    """
    if not isinstance(match_date_utc, date):
        raise TypeError(f"match_date_utc must be a date, got {type(match_date_utc)}")
    return "m_" + _digest(
        competition_id, season_id, match_date_utc.isoformat(), home_team_id, away_team_id
    )


def run_id(source: str, competition_id: str, season_id: str, started_at: str) -> str:
    return "r_" + _digest(source, competition_id, season_id, started_at, size=8)


def proposal_id(alias_raw: str, source: str, country: str, candidate_team_id: str) -> str:
    return "p_" + _digest(alias_raw, source, country, candidate_team_id, size=8)


def override_id(alias_raw: str, source: str, country: str) -> str:
    return "o_" + _digest(alias_raw, source, country, size=8)


def quarantine_id(source: str, source_id: str, home: str, away: str) -> str:
    return "q_" + _digest(source, str(source_id), home, away, size=8)
