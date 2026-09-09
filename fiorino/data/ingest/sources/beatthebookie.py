"""
BeatTheBookie — the timestamped odds series, from the SQL dump.

THE DUMP, NOT THE .txt EXPORT
-----------------------------
The same database ships two artefacts and only one of them is usable here.

    dump SQL      ohs.odds_datetime per observation, oh.bookmaker by name
    export .txt   72 hourly points relative to kickoff, bookmaker as a row index

The export is the one the paper uses and the one you find first. It resamples
the instant onto an hourly grid and throws the original away, which makes it
useless for the question this project needs to ask: an eleven published 60 to
75 minutes before kickoff falls inside a single hourly cell, together with the
control window it would have to be compared against.

So this adapter reads the dump's shape, verified from the project's own export
script (src/generate_odds_series_csv.php):

    SELECT oh.result, oh.disabled_date, ohs.odds, ohs.odds_datetime, oh.bookmaker
    FROM odds_history oh
    JOIN odds_history_series ohs ON oh.odds_history_id = ohs.odds_history_id
    WHERE bettype = '1x2'

NO DATA HAS BEEN INGESTED
-------------------------
The dump lives on Dropbox and Google Drive, both blocked by this environment's
egress policy. That is an environment access limitation, not a missing source:
the dataset demonstrably has the fields.

This adapter therefore exists before its data. That is deliberate — the schema
is documented and stable, so the transformation and its tests can be written
now and the ingest becomes one command later. What is NOT done is inventing an
instant: a row without `odds_datetime` is refused, never defaulted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

__all__ = ["BeatTheBookie", "SeriesRow", "SOURCE", "BOOKMAKERS", "RESULT_TO_SELECTION"]

SOURCE = "beatthebookie"

#: The 32 books the dataset covers, from the export script's own list. Names
#: are normalised to our bookmaker_id vocabulary by the caller through the
#: usual identity path — this module does not guess them.
BOOKMAKERS = (
    "10Bet", "12BET", "188BET", "bet-at-home", "bet365", "Betclic", "Betsafe",
    "Betsson", "BetVictor", "Betway", "ComeOn", "Coral", "DOXXbet", "Expekt",
    "Jetbull", "Ladbrokes", "myBet", "Paddy Power", "Pinnacle Sports", "SBOBET",
    "Sportingbet", "Stan James", "Tipico", "Unibet", "William Hill", "youwin",
    "888sport", "Interwetten", "Titanbet", "bwin", "Betadonis", "Betfair Sports",
)

#: oh.result in the dump. 1/2/3, not home/draw/away, and not in that order by
#: accident: the export script maps 1 -> home win, 2 -> draw, 3 -> away win.
RESULT_TO_SELECTION = {1: "HOME", 2: "DRAW", 3: "AWAY"}


class MissingInstant(ValueError):
    """A price row with no odds_datetime.

    Refused rather than defaulted. The whole reason to prefer the dump over the
    hourly export is that it carries a real instant; accepting a row without one
    would reintroduce exactly what was rejected.
    """


@dataclass(frozen=True)
class SeriesRow:
    """One observed price, from one book, at one instant."""

    match_source_id: str
    bookmaker_raw: str
    selection: str
    price_decimal: float
    captured_at: datetime
    #: Set when the book had pulled the market. Kept because a price that was
    #: withdrawn is a different fact from a price that merely stopped changing.
    disabled_at: datetime | None = None

    def as_row(self) -> dict:
        return {
            "source": SOURCE,
            "source_id": self.match_source_id,
            "bookmaker_raw": self.bookmaker_raw,
            "market_type": "ONE_X_TWO",
            "line": 0.0,
            "selection": self.selection,
            "price_decimal": self.price_decimal,
            # TIMESTAMPED, and only ever TIMESTAMPED. This adapter has no other
            # mode: a source without instants has no business coming through it.
            "capture_precision": "TIMESTAMPED",
            "captured_at": self.captured_at,
            "disabled_at": self.disabled_at,
        }


def _instant(value) -> datetime:
    if value is None or value == "":
        raise MissingInstant("odds_datetime is empty")
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace(" ", "T")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise MissingInstant(f"unparseable odds_datetime {value!r}") from exc
    # The export script sets date_default_timezone_set('UTC'), so a naive
    # instant from this dump is UTC. Stated here rather than assumed silently,
    # because attaching the wrong zone to a real instant is worse than having
    # no instant: it looks correct.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class BeatTheBookie:
    """Rows out of the dump's odds_history / odds_history_series join."""

    name = SOURCE

    def parse(self, rows) -> list[SeriesRow]:
        """Transform query rows into observations.

        ``rows`` are mappings with the dump's own column names. Rows whose
        result code is outside 1..3 are skipped: the dataset carries other
        bet types and this adapter claims only 1X2.
        """
        out: list[SeriesRow] = []
        for row in rows:
            selection = RESULT_TO_SELECTION.get(int(row["result"])) if row.get("result") else None
            if selection is None:
                continue
            price = row.get("odds")
            if price in (None, "", 0):
                continue
            price = float(price)
            if price <= 1.0:
                # A decimal price at or below evens returns less than the stake.
                # Real books do publish 1.01; anything at or under 1.0 is a
                # parsing artefact, not an offer.
                continue
            out.append(SeriesRow(
                match_source_id=str(row["ID"]),
                bookmaker_raw=str(row["bookmaker"]),
                selection=selection,
                price_decimal=price,
                captured_at=_instant(row.get("odds_datetime")),
                disabled_at=(_instant(row["disabled_date"])
                             if row.get("disabled_date") else None),
            ))
        return out

    @staticmethod
    def query(match_id: int) -> str:
        """The dump query this adapter consumes, kept beside the parser.

        Verified against src/generate_odds_series_csv.php in the upstream
        repository. Written out so the ingest is reproducible by someone who
        has the dump and not this code.
        """
        return (
            "SELECT m.ID, m.date, oh.result, oh.disabled_date, "
            "ohs.odds, ohs.odds_datetime, oh.bookmaker "
            "FROM matches m "
            "JOIN odds_history oh ON oh.ID = m.ID "
            "JOIN odds_history_series ohs "
            "  ON ohs.odds_history_id = oh.odds_history_id "
            f"WHERE m.ID = {int(match_id)} AND oh.bettype = '1x2' AND ohs.odds <> ''"
        )
