"""
openfootball/football.json adapter.

Free, public domain, no API key, updated daily, and it carries the current
season. It has NO odds — it is the calendar and result backbone, and the
corroborating second opinion on what was actually played.

Two properties matter for how it is modelled here:

* Team names are formal and long ("FC Internazionale Milano"), where
  Football-Data uses terse ones ("Inter"). Reconciling them is precisely the
  identity layer's job, and this source is the reason it exists.

* The `time` field is a LOCAL wall clock with no zone. It is therefore ingested
  as LOCAL_APPROX, and settlement is widened accordingly rather than pretending
  the instant is UTC.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, time, timezone

from fiorino.data.ingest.base import RawMatch

__all__ = ["OpenFootball", "LEAGUE_CODES", "BASE_URL"]

BASE_URL = "https://raw.githubusercontent.com/openfootball/football.json/master"

#: fiorino competition_id -> openfootball league code.
LEAGUE_CODES: dict[str, str] = {
    "ENG_PL": "en.1",
    "ENG_CH": "en.2",
    "ESP_LL": "es.1",
    "ITA_SA": "it.1",
    "DEU_BL1": "de.1",
    "FRA_L1": "fr.1",
    "NLD_ED": "nl.1",
    "PRT_L1": "pt.1",
}


def to_openfootball_season(season_id: str) -> str:
    """'2026-2027' -> '2026-27', the layout openfootball uses on disk."""
    start, end = season_id.split("-")
    return f"{start}-{end[-2:]}"


class OpenFootball:
    name = "openfootball"
    supports = frozenset(LEAGUE_CODES)

    def __init__(self, base_url: str = BASE_URL, opener=None):
        self.base_url = base_url
        # Injectable so tests read a local file and never touch the network.
        self._open = opener or self._urlopen

    @staticmethod
    def _urlopen(url: str) -> str:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.read().decode("utf-8")

    def url_for(self, competition_id: str, season_id: str) -> str:
        return (
            f"{self.base_url}/{to_openfootball_season(season_id)}/"
            f"{LEAGUE_CODES[competition_id]}.json"
        )

    def fetch(self, competition_id: str, season_id: str) -> list[RawMatch]:
        if competition_id not in LEAGUE_CODES:
            raise ValueError(f"openfootball does not cover {competition_id}")
        payload = json.loads(self._open(self.url_for(competition_id, season_id)))
        return self.parse(payload, competition_id, season_id)

    def parse(self, payload: dict, competition_id: str, season_id: str) -> list[RawMatch]:
        rows: list[RawMatch] = []
        for match in payload.get("matches", []):
            home, away = match.get("team1"), match.get("team2")
            match_date = match.get("date")
            if not (home and away and match_date):
                continue  # a fixture too provisional to identify

            ft, ht = self._parse_score(match.get("score"))

            kickoff = self._kickoff(match_date, match.get("time"))
            rows.append(
                RawMatch(
                    source=self.name,
                    # openfootball has no per-match id, so derive a stable one.
                    source_id=f"openfootball:{competition_id}:{season_id}:{match_date}:{home}:{away}",
                    competition=competition_id,
                    season=season_id,
                    match_date=match_date,
                    kickoff_utc=kickoff,
                    home_name_raw=home,
                    away_name_raw=away,
                    goals_home=_opt(ft[0]),
                    goals_away=_opt(ft[1]),
                    goals_home_ht=_opt(ht[0]),
                    goals_away_ht=_opt(ht[1]),
                    neutral_venue="false",
                    # The published time is a local wall clock with no zone.
                    kickoff_precision="LOCAL_APPROX" if match.get("time") else "DATE_ONLY",
                )
            )
        return rows

    @staticmethod
    def _parse_score(score) -> tuple[list, list]:
        """Normalise the five score shapes openfootball actually emits.

        Observed live across three seasons, not assumed:

            {"ft": [a, b], "ht": [c, d]}   full
            {"ft": [a, b]}                 no half-time
            {}                             played, nothing recorded
            [a, b]                         bare list, full time
            absent                         not played

        A parser that only knows the first shape crashes on the second-largest
        league in the set, so all five are handled and anything unrecognised
        is treated as "no result" rather than guessed at.
        """
        empty = [None, None]
        if score is None:
            return empty, empty
        if isinstance(score, list):
            return (list(score[:2]) if len(score) >= 2 else empty), empty
        if isinstance(score, dict):
            ft = score.get("ft") or empty
            ht = score.get("ht") or empty
            ft = list(ft[:2]) if isinstance(ft, list) and len(ft) >= 2 else empty
            ht = list(ht[:2]) if isinstance(ht, list) and len(ht) >= 2 else empty
            return ft, ht
        return empty, empty

    @staticmethod
    def _kickoff(match_date: str, match_time: str | None) -> str:
        parsed_date = datetime.fromisoformat(match_date).date()
        if match_time:
            hour, minute = (int(p) for p in str(match_time).split(":")[:2])
            clock = time(hour, minute)
        else:
            clock = time(15, 0)
        return datetime.combine(parsed_date, clock, tzinfo=timezone.utc).isoformat()


def _opt(value):
    return None if value is None else str(value)
