"""
The odds recorder, and the market it must not manufacture.

The distinctive risk here is the opposite of the lineup recorder's. Lineups
appear once; prices are read over and over. A collector that treats every read
as an observation produces a dense, confident time series out of a file nobody
changed — a flat market that looks measured and was merely watched.

So the tests are mostly about what does NOT get recorded.
"""

from datetime import datetime, timedelta, timezone

import pytest

from fiorino.data.ingest.odds_feed.recorder import (
    OddsPoll, Quote, deserialise, fold_prices, serialise,
)
from fiorino.data.ingest.odds_feed.sources import footballdata_fixtures as source

T0 = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def quote(home=2.10, draw=3.40, away=3.60, match="E0|09/09/26|Liverpool|Arsenal",
          book="PINNACLE"):
    return Quote(match_key=match, bookmaker=book, home=home, draw=draw, away=away)


def poll(minutes, quotes=(), scope=("E0|09/09/26|Liverpool|Arsenal",), error=None):
    return OddsPoll(source="test", observed_at=at(minutes), scope=tuple(scope),
                    quotes=tuple(quotes), error=error)


class TestOnlyAChangeIsAPrice:
    def test_the_first_sighting_is_recorded(self):
        [obs] = fold_prices([poll(0, [quote()])])
        assert obs.is_first_sighting
        assert obs.home == 2.10

    def test_an_unchanged_file_read_again_records_nothing(self):
        """The failure this recorder exists to avoid: a dense flat series out
        of a file nobody touched."""
        observations = fold_prices([poll(0, [quote()]), poll(30, [quote()]),
                                    poll(60, [quote()])])
        assert len(observations) == 1

    def test_a_changed_price_is_a_new_observation(self):
        observations = fold_prices([poll(0, [quote()]), poll(30, [quote(home=2.05)])])
        assert len(observations) == 2
        assert observations[1].home == 2.05
        assert not observations[1].is_first_sighting

    def test_a_price_that_returns_to_its_earlier_value_is_a_move(self):
        """Only the immediately preceding value is compared, so a round trip is
        two moves. Deduplicating against the whole history would erase the
        second one, and a market that moved and came back did move twice."""
        observations = fold_prices([
            poll(0, [quote()]), poll(30, [quote(home=2.05)]), poll(60, [quote()]),
        ])
        assert len(observations) == 3

    def test_two_bookmakers_are_tracked_apart(self):
        observations = fold_prices([
            poll(0, [quote(book="PINNACLE"), quote(book="BET365", home=2.15)]),
            poll(30, [quote(book="PINNACLE"), quote(book="BET365", home=2.20)]),
        ])
        assert len(observations) == 3


class TestTheGapIsMeasuredNotAssumed:
    def test_it_is_the_distance_to_the_previous_successful_poll(self):
        observations = fold_prices([poll(0, [quote()]), poll(30, [quote(home=2.05)])])
        assert observations[1].since_previous_poll_seconds == 30 * 60

    def test_a_failed_poll_closes_no_gap(self):
        observations = fold_prices([
            poll(0, [quote()]), poll(15, error="503"), poll(30, [quote(home=2.05)]),
        ])
        assert observations[1].since_previous_poll_seconds == 30 * 60

    def test_the_very_first_observation_has_no_gap(self):
        [obs] = fold_prices([poll(0, [quote()])])
        assert obs.since_previous_poll_seconds is None


class TestTheAdapterRefusesRatherThanNormalises:
    def test_a_complete_1x2_is_mapped(self):
        row = {"Div": "E0", "Date": "09/09/26", "HomeTeam": "Liverpool",
               "AwayTeam": "Arsenal", "PSH": "2.10", "PSD": "3.40", "PSA": "3.60"}
        [q] = source.quotes_from_row(row)
        assert q.bookmaker == "PINNACLE"
        assert (q.home, q.draw, q.away) == (2.10, 3.40, 3.60)

    def test_a_missing_leg_is_skipped_not_normalised(self):
        """Normalising two thirds of a market produces a confident number
        nothing downstream could tell from a real one."""
        row = {"Div": "E0", "Date": "09/09/26", "HomeTeam": "Liverpool",
               "AwayTeam": "Arsenal", "PSH": "2.10", "PSD": "", "PSA": "3.60"}
        assert source.quotes_from_row(row) == []

    def test_an_impossible_price_is_refused(self):
        row = {"Div": "E0", "Date": "09/09/26", "HomeTeam": "Liverpool",
               "AwayTeam": "Arsenal", "PSH": "1.00", "PSD": "3.40", "PSA": "3.60"}
        assert source.quotes_from_row(row) == []

    def test_a_row_without_teams_yields_nothing(self):
        assert source.quotes_from_row({"Div": "E0", "PSH": "2", "PSD": "3", "PSA": "4"}) == []

    def test_every_configured_book_is_read_from_one_row(self):
        row = {"Div": "E0", "Date": "09/09/26", "HomeTeam": "Liverpool",
               "AwayTeam": "Arsenal",
               "PSH": "2.10", "PSD": "3.40", "PSA": "3.60",
               "B365H": "2.05", "B365D": "3.45", "B365A": "3.70"}
        books = {q.bookmaker for q in source.quotes_from_row(row)}
        assert books == {"PINNACLE", "BET365"}

    def test_the_match_key_is_not_a_fuzzy_match(self):
        """Rule 9 holds here too: the key groups polls of the same fixture and
        is never a similarity score."""
        a = source.match_key({"Div": "E0", "Date": "09/09/26",
                              "HomeTeam": "Man United", "AwayTeam": "Arsenal"})
        b = source.match_key({"Div": "E0", "Date": "09/09/26",
                              "HomeTeam": "Manchester United", "AwayTeam": "Arsenal"})
        assert a != b


class TestTheArchiveRoundTrips:
    @pytest.mark.parametrize("original", [
        poll(0), poll(5, error="timeout"), poll(30, [quote(), quote(book="BET365")]),
    ])
    def test_a_poll_survives_a_write_and_a_read(self, original):
        assert deserialise(serialise(original)) == original


class TestTheCollectionCanActuallyStart:
    """The operational half. A collector that cannot start, or that fails in a
    way people learn to ignore, produces the same outcome as no collector."""

    import subprocess as _sp
    import sys as _sys
    from pathlib import Path as _P

    REPO = _P(__file__).resolve().parents[2]
    WORKFLOW = REPO / ".github/workflows/record-odds.yml"

    def test_it_needs_no_token(self):
        """The whole point of this source over SportMonks and OddsPortal: the
        file is published for download, so nothing has to be configured."""
        import ast

        # Asserted on the code, not on the prose: the docstring is allowed to
        # discuss tokens, the code is not allowed to read one.
        tree = ast.parse((self.REPO / "scripts/record_odds.py").read_text())
        reads_env = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv"}
        ]
        assert not reads_env, "the odds collector must need no configuration"

    def test_a_blocked_network_is_reported_not_disguised(self):
        """'Source unavailable' would be a claim about the data. The data is
        fine; the network is not, and the two must stay distinguishable."""
        import subprocess
        import sys

        done = subprocess.run(
            [sys.executable, str(self.REPO / "scripts/record_odds.py"), "--verify"],
            capture_output=True, text=True, cwd=self.REPO, timeout=180)
        assert "HTTP_STATUS=" in done.stdout
        if done.returncode != 0:
            assert "NOTA=una chiamata fallita non dice che la fonte sia inadatta" in done.stdout

    def test_the_archive_is_tracked_by_git(self):
        import subprocess

        probe = self.REPO / "archive/odds/2026/01/01.jsonl"
        done = subprocess.run(["git", "check-ignore", "-q", str(probe)],
                              cwd=self.REPO, capture_output=True)
        assert done.returncode != 0

    def test_runs_are_queued_and_never_cancelled(self):
        assert "cancel-in-progress: false" in self.WORKFLOW.read_text()

    def test_it_rebases_instead_of_forcing(self):
        text = self.WORKFLOW.read_text()
        assert "--rebase" in text and "--force" not in text

    def test_the_verify_reports_every_configured_book_including_absent_ones(self):
        """A book missing from the output would read as 'not offered'. A zero
        says the column was looked for and was not there."""
        runner = (self.REPO / "scripts/record_odds.py").read_text()
        assert "for book, _ in source.BOOKS" in runner

class TestAgainstTheRealHeader:
    """Written from the header the source actually returned on 2026-09-09,
    not from one imagined for the test. The previous version of this adapter
    passed every synthetic test and would have mapped nothing at all."""

    #: Verbatim from the probe: STATUS=200, BYTES=5609.
    HEADER = ("\ufeffDiv,Date,Time,HomeTeam,AwayTeam,Referee,"
              "B365H,B365D,B365A,BFDH,BFDD,BFDA,BVH,BVD,BVA,BWH,BWD,BWA,"
              "PPH,PPD,PPA,SKBH,SKBD,SKBA,MaxH,MaxD,MaxA,AvgH,AvgD,AvgA,"
              "BFEH,BFED,BFEA")

    def row(self):
        values = ["E0", "12/09/2026", "20:00", "Liverpool", "Arsenal", "M Oliver"]
        # nine 1X2 triples, one per book present in the real file
        for base in (2.05, 2.06, 2.04, 2.07, 2.05, 2.06, 2.08, 2.14, 2.05):
            values += [str(base), "3.45", "3.70"]
        return self.HEADER + "\n" + ",".join(values) + "\n"

    def test_the_url_uses_the_host_that_answers(self):
        """www.football-data.co.uk returns 503 on every path; the bare host
        returns 200. Four characters, and it is a corrected URL, not a
        workaround."""
        assert source.URL == "https://football-data.co.uk/fixtures.csv"

    def test_every_configured_book_except_pinnacle_maps(self):
        scope, quotes = source.parse(self.row())
        found = {q.bookmaker for q in quotes}
        assert len(scope) == 1
        assert "BET365" in found and "BETFAIR_EX" in found and "MARKET_MAX" in found
        assert len(found) == 9

    def test_pinnacle_is_absent_and_that_is_recorded_not_hidden(self):
        """The benchmark this source was chosen for is not in the file. The
        column stays configured as a sentinel: the day BOOK_PINNACLE stops
        being zero, the benchmark is back."""
        assert "PINNACLE" in dict(source.BOOKS)
        _, quotes = source.parse(self.row())
        assert not [q for q in quotes if q.bookmaker == "PINNACLE"]

    def test_the_bom_does_not_eat_the_division(self):
        """The file is served with a UTF-8 BOM, so the first column arrives as
        "\ufeffDiv" and row["Div"] returns nothing. Nothing fails: a missing
        division is an empty string and an empty string joins fine, so the key
        silently loses the one field that separates two divisions."""
        scope, _ = source.parse(self.row())
        assert scope[0].startswith("E0|"), scope[0]
