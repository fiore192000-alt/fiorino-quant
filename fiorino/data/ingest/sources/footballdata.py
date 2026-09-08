"""
Football-Data.co.uk adapter — results, statistics and ODDS.

This is the source that makes M2 possible: it publishes bookmaker prices,
including CLOSING prices, for free, with no key. The `C` infix marks closing
columns, so `PSCH/PSCD/PSCA` is the Pinnacle closing 1X2 — a sharp reference
close, which is exactly what CLV must be measured against.

STATUS — read this before trusting it
-------------------------------------
The column contract below is asserted at ingest, not assumed, because this
adapter could NOT be validated against the live site from the environment it
was written in: the network policy rejects www.football-data.co.uk at the
proxy (``gateway answered 403 to CONNECT``). The parsing logic is exercised
against a committed CSV fixture; the live column set for the current season is
unverified. `verify_columns` therefore fails loudly rather than silently
producing rows with missing odds.

WHAT THIS SOURCE IS AND IS NOT
------------------------------
It gives at most TWO observations per market: a pre-match price and a closing
price. That is enough for CLV, and not enough for a line history.

Critically, the pre-match columns carry NO capture timestamp. Football-Data
collects them at an unstated point before kickoff. So a backtest can say "we
would have got this price" but not "we bet three hours before kickoff", and
`captured_at` for those rows is a bound, not an observation — which is why
`OddsObservation` carries an explicit `capture_precision`. Fabricating a
precise timestamp there would put a lie inside the one rule (R1) the whole
system rests on.
"""

from __future__ import annotations

import csv
import io
import json
import urllib.request
from dataclasses import dataclass
from datetime import datetime, time, timezone

from fiorino.data.ingest.base import RawMatch

__all__ = [
    "FootballData",
    "LEAGUE_CODES",
    "REQUIRED_COLUMNS",
    "ODDS_COLUMNS",
    "OddsObservation",
    "MissingColumns",
]

BASE_URL = "https://www.football-data.co.uk/mmz4281"

#: fiorino competition_id -> Football-Data division code.
LEAGUE_CODES: dict[str, str] = {
    "ENG_PL": "E0",
    "ENG_CH": "E1",
    "ESP_LL": "SP1",
    "ITA_SA": "I1",
    "DEU_BL1": "D1",
    "FRA_L1": "F1",
    "NLD_ED": "N1",
    "PRT_L1": "P1",
}

#: Without these the file is not a Football-Data match file at all.
REQUIRED_COLUMNS = ("Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR")

#: (market_type, line, selection) -> (prematch column, closing column)
#:
#: Pinnacle is the reference book: PSCH/PSCD/PSCA is its closing 1X2, and the
#: de-vigged form of that is the denominator of every CLV number.
ODDS_COLUMNS: dict[tuple[str, float, str], tuple[str, str]] = {
    ("ONE_X_TWO", 0.0, "HOME"): ("PSH", "PSCH"),
    ("ONE_X_TWO", 0.0, "DRAW"): ("PSD", "PSCD"),
    ("ONE_X_TWO", 0.0, "AWAY"): ("PSA", "PSCA"),
}

#: Fallbacks when Pinnacle is absent for a division or season. Order matters:
#: the first book present wins, and the choice is recorded per row.
FALLBACK_BOOKS: tuple[tuple[str, dict], ...] = (
    ("bet365", {"HOME": ("B365H", "B365CH"), "DRAW": ("B365D", "B365CD"),
                "AWAY": ("B365A", "B365CA")}),
    ("market_max", {"HOME": ("MaxH", "MaxCH"), "DRAW": ("MaxD", "MaxCD"),
                    "AWAY": ("MaxA", "MaxCA")}),
    ("market_avg", {"HOME": ("AvgH", "AvgCH"), "DRAW": ("AvgD", "AvgCD"),
                    "AWAY": ("AvgA", "AvgCA")}),
)


class MissingColumns(RuntimeError):
    """The CSV does not carry the columns this adapter was written against."""


@dataclass(frozen=True)
class OddsObservation:
    """One price, with an honest statement of when it was observed."""

    bookmaker: str
    market_type: str
    line: float
    selection: str
    price_decimal: float
    #: CLOSING  — the last price before kickoff; a real, meaningful instant.
    #: PREMATCH — collected at an unstated time before kickoff; a bound only.
    capture_precision: str


class FootballData:
    name = "footballdata"
    supports = frozenset(LEAGUE_CODES)

    def __init__(self, base_url: str = BASE_URL, opener=None):
        self.base_url = base_url
        self._open = opener or self._urlopen

    @staticmethod
    def _urlopen(url: str) -> str:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read().decode("utf-8-sig", errors="replace")

    @staticmethod
    def to_season_code(season_id: str) -> str:
        """'2026-2027' -> '2627', the directory Football-Data uses."""
        start, end = season_id.split("-")
        return f"{start[-2:]}{end[-2:]}"

    def url_for(self, competition_id: str, season_id: str) -> str:
        return (
            f"{self.base_url}/{self.to_season_code(season_id)}/"
            f"{LEAGUE_CODES[competition_id]}.csv"
        )

    # -- contract -----------------------------------------------------
    @staticmethod
    def verify_columns(columns) -> None:
        """Fail loudly on a file that is not what this adapter expects.

        A silent partial parse is the worst outcome: it produces matches with
        no odds, and a CLV report that is quietly computed over a subset.
        """
        present = set(columns)
        missing = [c for c in REQUIRED_COLUMNS if c not in present]
        if missing:
            raise MissingColumns(
                f"not a Football-Data match file; missing {missing}. "
                f"Saw: {sorted(present)[:12]}..."
            )

    @staticmethod
    def closing_book(columns) -> str | None:
        """Which book supplies a usable CLOSING 1X2 in this file, if any."""
        present = set(columns)
        if {"PSCH", "PSCD", "PSCA"} <= present:
            return "pinnacle"
        for book, mapping in FALLBACK_BOOKS:
            if {mapping[s][1] for s in ("HOME", "DRAW", "AWAY")} <= present:
                return book
        return None

    # -- parsing ------------------------------------------------------
    def fetch(self, competition_id: str, season_id: str) -> list[RawMatch]:
        if competition_id not in LEAGUE_CODES:
            raise ValueError(f"Football-Data does not cover {competition_id}")
        return self.parse(self._open(self.url_for(competition_id, season_id)),
                          competition_id, season_id)

    def parse(self, text: str, competition_id: str, season_id: str) -> list[RawMatch]:
        reader = csv.DictReader(io.StringIO(text))
        columns = reader.fieldnames or []
        self.verify_columns(columns)
        book = self.closing_book(columns)

        rows: list[RawMatch] = []
        for index, record in enumerate(reader):
            home, away = record.get("HomeTeam"), record.get("AwayTeam")
            raw_date = record.get("Date")
            if not (home and away and raw_date):
                continue  # trailing blank rows are normal in these files

            match_date = self._parse_date(raw_date)
            raw_time = record.get("Time")
            kickoff = datetime.combine(
                match_date,
                self._parse_time(raw_time) if raw_time else time(15, 0),
                tzinfo=timezone.utc,
            )
            rows.append(
                RawMatch(
                    source=self.name,
                    source_id=f"footballdata:{competition_id}:{season_id}:{index:04d}",
                    competition=competition_id,
                    season=season_id,
                    match_date=match_date.isoformat(),
                    kickoff_utc=kickoff.isoformat(),
                    home_name_raw=home.strip(),
                    away_name_raw=away.strip(),
                    goals_home=_opt(record.get("FTHG")),
                    goals_away=_opt(record.get("FTAG")),
                    goals_home_ht=_opt(record.get("HTHG")),
                    goals_away_ht=_opt(record.get("HTAG")),
                    neutral_venue="false",
                    # Football-Data's Time is a local kickoff clock, not UTC.
                    kickoff_precision="LOCAL_APPROX" if raw_time else "DATE_ONLY",
                    odds_json=_dump_odds(self._row_odds(record, book)),
                )
            )
        return rows

    def _row_odds(self, record: dict, book: str | None) -> list[OddsObservation]:
        """Every price this row publishes, each labelled with its precision."""
        observations: list[OddsObservation] = []
        for (market, line, selection), (pre_col, close_col) in ODDS_COLUMNS.items():
            for column, precision in ((pre_col, "PREMATCH"), (close_col, "CLOSING")):
                price = _price(record.get(column))
                if price is not None:
                    observations.append(
                        OddsObservation("pinnacle", market, line, selection, price, precision)
                    )
        if book and book != "pinnacle":
            mapping = dict(FALLBACK_BOOKS)[book]
            for selection, (pre_col, close_col) in mapping.items():
                for column, precision in ((pre_col, "PREMATCH"), (close_col, "CLOSING")):
                    price = _price(record.get(column))
                    if price is not None:
                        observations.append(
                            OddsObservation(book, "ONE_X_TWO", 0.0, selection, price, precision)
                        )
        return observations

    def parse_odds(self, text: str) -> list[tuple[str, list[OddsObservation]]]:
        """Odds per row, paired with the row's source_id. Feeds M2, not M1."""
        reader = csv.DictReader(io.StringIO(text))
        columns = reader.fieldnames or []
        self.verify_columns(columns)
        book = self.closing_book(columns)

        out: list[tuple[str, list[OddsObservation]]] = []
        for index, record in enumerate(reader):
            if not record.get("HomeTeam"):
                continue
            out.append((f"{index:04d}", self._row_odds(record, book)))
        return out

    @staticmethod
    def _parse_date(value: str):
        """Football-Data has used both two- and four-digit years over the years."""
        text = value.strip()
        for fmt in ("%d/%m/%Y", "%d/%m/%y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"unrecognised Football-Data date: {value!r}")

    @staticmethod
    def _parse_time(value: str) -> time:
        hour, minute = (int(p) for p in value.strip().split(":")[:2])
        return time(hour, minute)


def _opt(value):
    text = (value or "").strip()
    return text or None


def _price(value):
    text = (value or "").strip()
    if not text:
        return None
    try:
        price = float(text)
    except ValueError:
        return None
    return price if price > 1.0 else None


def _dump_odds(observations: list[OddsObservation]) -> str | None:
    """Serialise observations for the bronze row. None when the row has none."""
    if not observations:
        return None
    return json.dumps([
        {
            "bookmaker": o.bookmaker,
            "market_type": o.market_type,
            "line": o.line,
            "selection": o.selection,
            "price_decimal": o.price_decimal,
            "capture_precision": o.capture_precision,
        }
        for o in observations
    ], sort_keys=True)
