"""
openfootball adapter — against real payloads, offline.

The fixtures in fixtures/ are trimmed extracts of live openfootball data, kept
in the repository so the suite never touches the network. They deliberately
include every score shape the source actually emits.
"""

import json
from pathlib import Path

import pytest

from fiorino.data.ingest.base import settle_instant
from fiorino.data.ingest.sources.openfootball import (
    LEAGUE_CODES,
    OpenFootball,
    to_openfootball_season,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def serie_a():
    return load("openfootball_it1_2026-27.json")


@pytest.fixture
def premier():
    return load("openfootball_en1_2025-26.json")


class TestSeasonMapping:
    @pytest.mark.parametrize(
        "season_id,expected",
        [("2026-2027", "2026-27"), ("2015-2016", "2015-16"), ("1999-2000", "1999-00")],
    )
    def test_season_ids_map_to_the_upstream_layout(self, season_id, expected):
        assert to_openfootball_season(season_id) == expected

    def test_all_eight_competitions_are_mapped(self):
        from fiorino.config.registries import COMPETITIONS

        assert set(LEAGUE_CODES) == set(COMPETITIONS)

    def test_url_is_built_from_the_mapping(self):
        url = OpenFootball().url_for("ITA_SA", "2026-2027")
        assert url.endswith("/2026-27/it.1.json")


class TestScoreShapes:
    """The five shapes observed live. A parser that knows only one crashes."""

    @pytest.mark.parametrize(
        "score,ft,ht",
        [
            ({"ft": [2, 1], "ht": [1, 0]}, [2, 1], [1, 0]),
            ({"ft": [0, 0]}, [0, 0], [None, None]),
            ({}, [None, None], [None, None]),
            ([3, 1], [3, 1], [None, None]),
            (None, [None, None], [None, None]),
            ("nonsense", [None, None], [None, None]),
        ],
    )
    def test_every_shape_is_handled(self, score, ft, ht):
        assert OpenFootball._parse_score(score) == (ft, ht)

    def test_real_payload_parses_without_error(self, serie_a, premier):
        src = OpenFootball()
        assert src.parse(serie_a, "ITA_SA", "2026-2027")
        assert src.parse(premier, "ENG_PL", "2025-2026")

    def test_bare_list_scores_are_read_as_full_time(self, premier):
        rows = OpenFootball().parse(premier, "ENG_PL", "2025-2026")
        assert any(r.goals_home is not None for r in rows)


class TestParsing:
    def test_unplayed_matches_carry_no_result(self, serie_a):
        rows = OpenFootball().parse(serie_a, "ITA_SA", "2026-2027")
        unplayed = [r for r in rows if r.goals_home is None]
        assert unplayed, "the fixture includes scheduled matches"
        assert all(r.goals_away is None for r in unplayed)

    def test_source_ids_are_stable_and_unique(self, serie_a):
        rows = OpenFootball().parse(serie_a, "ITA_SA", "2026-2027")
        ids = [r.source_id for r in rows]
        assert len(ids) == len(set(ids))
        again = OpenFootball().parse(serie_a, "ITA_SA", "2026-2027")
        assert ids == [r.source_id for r in again]

    def test_team_names_are_kept_raw(self, serie_a):
        """Resolving them is the identity layer's job, not the adapter's."""
        rows = OpenFootball().parse(serie_a, "ITA_SA", "2026-2027")
        assert any(" " in r.home_name_raw for r in rows)

    def test_incomplete_rows_are_skipped_not_guessed(self):
        payload = {"matches": [{"date": "2026-08-22", "team1": "A"}, {"team2": "B"}]}
        assert OpenFootball().parse(payload, "ITA_SA", "2026-2027") == []


class TestKickoffPrecision:
    """The source publishes a local wall clock with no zone."""

    def test_a_time_field_yields_local_approx(self, serie_a):
        rows = [r for r in OpenFootball().parse(serie_a, "ITA_SA", "2026-2027")]
        timed = [r for r in rows if r.kickoff_precision == "LOCAL_APPROX"]
        assert timed, "the fixture includes matches with a time"

    def test_a_missing_time_yields_date_only(self, serie_a):
        rows = OpenFootball().parse(serie_a, "ITA_SA", "2026-2027")
        assert any(r.kickoff_precision == "DATE_ONLY" for r in rows)

    def test_imprecise_sources_settle_conservatively_late(self):
        """Erring late costs training data; erring early is leakage."""
        from datetime import date, datetime, timezone

        kickoff = datetime(2026, 8, 22, 18, 30, tzinfo=timezone.utc)
        day = date(2026, 8, 22)
        exact = settle_instant(kickoff, day, "EXACT")
        approx = settle_instant(kickoff, day, "LOCAL_APPROX")
        assert approx > exact
        assert approx > kickoff.replace(hour=23, minute=59)

    def test_an_unknown_precision_is_refused(self):
        from datetime import date, datetime, timezone

        with pytest.raises(ValueError, match="unknown kickoff precision"):
            settle_instant(datetime(2026, 1, 1, tzinfo=timezone.utc), date(2026, 1, 1), "GUESS")


class TestNoNetworkInTests:
    def test_the_adapter_accepts_an_injected_opener(self, serie_a):
        """How the suite stays offline: the fetch path is injectable."""
        src = OpenFootball(opener=lambda url: json.dumps(serie_a))
        rows = src.fetch("ITA_SA", "2026-2027")
        assert rows and all(r.source == "openfootball" for r in rows)

    def test_an_uncovered_competition_is_refused(self):
        with pytest.raises(ValueError, match="does not cover"):
            OpenFootball().fetch("XXX_YY", "2026-2027")


class TestEndToEndIntoSilver:
    """Real names through the real identity layer."""

    def test_unknown_real_names_are_quarantined_never_guessed(self, seeded_db, serie_a, tmp_path):
        from fiorino.data.lake import bronze_path, write_bronze
        from fiorino.data.pipeline import ingest_bronze

        rows = OpenFootball().parse(serie_a, "ITA_SA", "2026-2027")
        write_bronze(seeded_db, [r.as_row() for r in rows],
                     bronze_path(tmp_path, "openfootball", "ITA_SA", "2026-2027", "t"))
        result = ingest_bronze(seeded_db, tmp_path)
        assert result.matches_written == 0
        assert result.quarantined == len(rows)

    def test_seeding_admits_them_all(self, seeded_db, serie_a, tmp_path):
        from fiorino.data.lake import bronze_path, write_bronze
        from fiorino.data.pipeline import ingest_bronze

        rows = OpenFootball().parse(serie_a, "ITA_SA", "2026-2027")
        write_bronze(seeded_db, [r.as_row() for r in rows],
                     bronze_path(tmp_path, "openfootball", "ITA_SA", "2026-2027", "t"))
        result = ingest_bronze(seeded_db, tmp_path, auto_register_unknown=True)
        assert result.matches_written == len(rows)
        assert result.quarantined == 0
