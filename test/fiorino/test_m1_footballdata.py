"""
Football-Data.co.uk adapter.

Scope note: the live site is unreachable from the environment this was written
in (the network policy rejects www.football-data.co.uk at the proxy with a 403
on CONNECT), so these tests exercise the parser against a committed CSV built
to the documented column layout. They prove the parsing contract; they do not
prove the live column set for the current season. `verify_columns` exists so
that a mismatch fails loudly at ingest rather than silently dropping odds.
"""

from pathlib import Path

import pytest

from fiorino.data.ingest.sources.footballdata import (
    LEAGUE_CODES,
    MissingColumns,
    FootballData,
)

SAMPLE = (Path(__file__).parent / "fixtures" / "footballdata_i1_sample.csv").read_text()


class TestUrlAndCoverage:
    @pytest.mark.parametrize(
        "season_id,code", [("2026-2027", "2627"), ("1999-2000", "9900"), ("2015-2016", "1516")]
    )
    def test_season_codes(self, season_id, code):
        assert FootballData.to_season_code(season_id) == code

    def test_all_eight_competitions_are_mapped(self):
        from fiorino.config.registries import COMPETITIONS

        assert set(LEAGUE_CODES) == set(COMPETITIONS)

    def test_url_layout(self):
        assert FootballData().url_for("ITA_SA", "2026-2027").endswith("/2627/I1.csv")


class TestColumnContract:
    """A partial parse is worse than a loud failure: it yields odds-less rows."""

    def test_a_file_missing_core_columns_is_refused(self):
        with pytest.raises(MissingColumns, match="not a Football-Data match file"):
            FootballData().parse("Foo,Bar\n1,2\n", "ITA_SA", "2026-2027")

    def test_the_sample_satisfies_the_contract(self):
        FootballData.verify_columns(SAMPLE.splitlines()[0].split(","))

    def test_pinnacle_is_detected_as_the_closing_book(self):
        assert FootballData.closing_book(SAMPLE.splitlines()[0].split(",")) == "pinnacle"

    def test_a_fallback_book_is_used_when_pinnacle_is_absent(self):
        columns = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR",
                   "B365CH", "B365CD", "B365CA"]
        assert FootballData.closing_book(columns) == "bet365"

    def test_no_closing_book_is_reported_as_none(self):
        columns = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR", "PSH", "PSD", "PSA"]
        assert FootballData.closing_book(columns) is None


class TestParsing:
    def test_rows_are_parsed_and_blank_trailers_dropped(self):
        rows = FootballData().parse(SAMPLE, "ITA_SA", "2026-2027")
        assert len(rows) == 4
        assert [r.home_name_raw for r in rows] == ["Udinese", "Inter", "Roma", "Milan"]

    def test_dates_are_read(self):
        rows = FootballData().parse(SAMPLE, "ITA_SA", "2026-2027")
        assert rows[0].match_date == "2026-08-22"

    def test_both_year_formats_are_accepted(self):
        """The archive mixes dd/mm/yy and dd/mm/yyyy across seasons."""
        assert FootballData._parse_date("22/08/26").year == 2026
        assert FootballData._parse_date("22/08/2026").year == 2026

    def test_an_unparseable_date_is_refused(self):
        with pytest.raises(ValueError, match="unrecognised"):
            FootballData._parse_date("2026-08-22")

    def test_an_unplayed_match_carries_no_result(self):
        rows = FootballData().parse(SAMPLE, "ITA_SA", "2026-2027")
        assert rows[3].goals_home is None and rows[3].goals_away is None

    def test_a_missing_time_is_date_only(self):
        rows = FootballData().parse(SAMPLE, "ITA_SA", "2026-2027")
        assert rows[2].kickoff_precision == "DATE_ONLY"
        assert rows[0].kickoff_precision == "LOCAL_APPROX"


class TestOdds:
    """What makes this the M2 source: prices, including the close."""

    def test_closing_and_prematch_are_distinguished(self):
        _, obs = FootballData().parse_odds(SAMPLE)[0]
        precisions = {o.capture_precision for o in obs}
        assert precisions == {"PREMATCH", "CLOSING"}

    def test_pinnacle_closing_1x2_is_extracted(self):
        _, obs = FootballData().parse_odds(SAMPLE)[0]
        closing = {
            o.selection: o.price_decimal
            for o in obs
            if o.bookmaker == "pinnacle" and o.capture_precision == "CLOSING"
        }
        assert closing == {"HOME": 2.40, "DRAW": 3.45, "AWAY": 3.05}

    def test_the_closing_market_carries_a_plausible_overround(self):
        _, obs = FootballData().parse_odds(SAMPLE)[0]
        closing = [o for o in obs if o.bookmaker == "pinnacle" and o.capture_precision == "CLOSING"]
        overround = sum(1 / o.price_decimal for o in closing) - 1
        assert 0.0 < overround < 0.10, f"implausible overround {overround:.4f}"

    def test_a_row_without_closing_odds_yields_prematch_only(self):
        """The current season's unplayed matches have no close yet."""
        _, obs = FootballData().parse_odds(SAMPLE)[3]
        assert {o.capture_precision for o in obs} == {"PREMATCH"}

    def test_junk_and_sub_evens_prices_are_dropped(self):
        from fiorino.data.ingest.sources.footballdata import _price

        assert _price("") is None and _price("n/a") is None
        assert _price("1.00") is None and _price("0.5") is None
        assert _price("2.40") == 2.40


class TestCapturePrecisionIsHonest:
    """The reason OddsObservation carries a precision at all."""

    def test_prematch_prices_are_not_claimed_to_have_a_timestamp(self):
        _, obs = FootballData().parse_odds(SAMPLE)[0]
        prematch = [o for o in obs if o.capture_precision == "PREMATCH"]
        assert prematch
        assert not any(hasattr(o, "captured_at") for o in prematch), (
            "Football-Data does not say when a pre-match price was collected; "
            "inventing an instant would put a falsehood inside rule R1"
        )
