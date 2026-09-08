"""
The competitions Fiorino Quant tracks, and which sources actually cover them.

`SOURCE_COVERAGE` is load-bearing, not documentation. The "zero unresolved
identities" acceptance criterion is scoped to the source-competition pairs
listed here. Understat does not publish the Championship; demanding resolution
there would make the criterion unsatisfiable by construction rather than by
failure, which is a worse outcome than an honest gap.
"""

from __future__ import annotations

from datetime import date

__all__ = [
    "COMPETITIONS",
    "SOURCE_COVERAGE",
    "SEASONS",
    "all_seasons",
    "current_season",
    "FIRST_SEASON_YEAR",
    "country_of",
    "covered_competitions",
    "season_bounds",
]

#: competition_id -> (name, country, tier, is_cup)
COMPETITIONS: dict[str, tuple[str, str, int, bool]] = {
    "ENG_PL":  ("Premier League",  "ENG", 1, False),
    "ENG_CH":  ("Championship",    "ENG", 2, False),
    "ESP_LL":  ("La Liga",         "ESP", 1, False),
    "ITA_SA":  ("Serie A",         "ITA", 1, False),
    "DEU_BL1": ("Bundesliga",      "DEU", 1, False),
    "FRA_L1":  ("Ligue 1",         "FRA", 1, False),
    "NLD_ED":  ("Eredivisie",      "NLD", 1, False),
    "PRT_L1":  ("Liga Portugal",   "PRT", 1, False),
}

#: source -> {competition_id: supports_xg}
SOURCE_COVERAGE: dict[str, dict[str, bool]] = {
    "footballdata": {c: False for c in COMPETITIONS},
    "fbref": {c: True for c in COMPETITIONS},
    # Understat covers the big five only. The two second-tier and two smaller
    # first-tier leagues are genuinely absent, not merely unconfigured.
    "understat": {
        "ENG_PL": True, "ESP_LL": True, "ITA_SA": True,
        "DEU_BL1": True, "FRA_L1": True,
    },
    # ClubElo is club-level ratings, not match rows: it contributes team
    # identity and nothing else.
    "clubelo": {c: False for c in COMPETITIONS},
}

#: First season Fiorino Quant tracks.
FIRST_SEASON_YEAR = 2015


def current_season(today: date | None = None) -> str:
    """The season in progress on ``today``.

    European seasons straddle the calendar year and start in July, so anything
    from July onwards belongs to the season named for that year.
    """
    today = today or date.today()
    start_year = today.year if today.month >= 7 else today.year - 1
    return f"{start_year}-{start_year + 1}"


def all_seasons(today: date | None = None) -> tuple[str, ...]:
    """Every season from the first tracked one through the current one.

    Derived, never frozen: a hardcoded list silently stops ingesting the moment
    a new season starts, which is the least visible way for a data system to
    go stale.
    """
    last_year = int(current_season(today).split("-")[0])
    return tuple(f"{y}-{y + 1}" for y in range(FIRST_SEASON_YEAR, last_year + 1))


#: Seasons known at import time. Call `all_seasons()` in long-running processes
#: so a season rollover is picked up without a restart.
SEASONS: tuple[str, ...] = all_seasons()


def country_of(competition_id: str | None = None):
    """Country for one competition, or the whole mapping."""
    mapping = {cid: meta[1] for cid, meta in COMPETITIONS.items()}
    return mapping if competition_id is None else mapping[competition_id]


def covered_competitions(source: str) -> frozenset[str]:
    return frozenset(SOURCE_COVERAGE.get(source, {}))


def season_bounds(season_id: str) -> tuple[str, str]:
    """European season runs roughly July to June."""
    start_year = int(season_id.split("-")[0])
    return f"{start_year}-07-01", f"{start_year + 1}-06-30"
