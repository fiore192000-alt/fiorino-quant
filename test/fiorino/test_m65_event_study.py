"""
The lineup event study, and the rule that guards it.

The experiment cannot be run: no source of timestamped odds or timestamped
lineups is reachable. So the machinery is validated the way the hypothesis
scanner was — by planting a known effect in synthetic data and checking it is
found, and by planting nothing and checking nothing is found.

That is a real validation of the instrument. It is not evidence about football.
"""

from datetime import datetime, timedelta, timezone

import pytest

from fiorino.data.db.connection import connect
from fiorino.data.db.migrate import migrate
from fiorino.research.event_study import (
    CATEGORIES,
    Category,
    difference_in_differences,
    formation_shock,
    measure_windows,
    require_timestamped,
)

UTC = timezone.utc
KICKOFF = datetime(2025, 3, 1, 15, 0, tzinfo=UTC)
PUBLISHED = KICKOFF - timedelta(minutes=70)


class TestFormationShock:
    def test_no_absences_scores_zero(self):
        shock = formation_shock([])
        assert shock.value == 0.0
        assert shock.categories == (Category.NONE,)

    def test_a_goalkeeper_is_categorised(self):
        shock = formation_shock([
            {"position": "GOALKEEPER", "start_share": 1.0, "replacement_share": 0.0}])
        assert Category.GOALKEEPER_OUT in shock.categories
        assert shock.value == pytest.approx(1.0)

    def test_a_like_for_like_swap_is_not_a_shock(self):
        """A replacement who also starts most weeks is not news."""
        shock = formation_shock([
            {"position": "FORWARD", "start_share": 0.9, "replacement_share": 0.85}])
        assert shock.value < 0.05

    def test_an_upgrade_does_not_score_negative(self):
        """A better replacement is a different event, not a negative shock.
        Letting it go negative would cancel real signal in the average."""
        shock = formation_shock([
            {"position": "MIDFIELDER", "start_share": 0.2, "replacement_share": 0.9}])
        assert shock.value == 0.0

    def test_a_goalkeeper_outweighs_a_midfielder(self):
        gk = formation_shock([
            {"position": "GOALKEEPER", "start_share": 1.0, "replacement_share": 0.0}])
        mid = formation_shock([
            {"position": "MIDFIELDER", "start_share": 1.0, "replacement_share": 0.0}])
        assert gk.value > mid.value

    def test_three_absences_trigger_the_multiple_category(self):
        shock = formation_shock([
            {"position": "DEFENDER", "start_share": 0.8, "replacement_share": 0.1},
            {"position": "MIDFIELDER", "start_share": 0.7, "replacement_share": 0.2},
            {"position": "FORWARD", "start_share": 0.9, "replacement_share": 0.0}])
        assert Category.MULTIPLE_ABSENCES in shock.categories
        assert shock.n_absent == 3

    def test_half_the_eleven_is_a_surprise_lineup(self):
        shock = formation_shock([
            {"position": "MIDFIELDER", "start_share": 0.6, "replacement_share": 0.1}
        ] * 6)
        assert Category.SURPRISE_XI in shock.categories

    def test_categories_are_not_duplicated(self):
        shock = formation_shock([
            {"position": "GOALKEEPER", "start_share": 1.0, "replacement_share": 0.0},
            {"position": "GOALKEEPER", "start_share": 1.0, "replacement_share": 0.0}])
        assert len(shock.categories) == len(set(shock.categories))


@pytest.fixture
def db():
    con = connect()
    migrate(con)
    con.execute("INSERT INTO competitions VALUES ('ENG_PL', 'Premier League', 'ENG', 1, FALSE)")
    con.execute("INSERT INTO seasons VALUES ('2024-2025', DATE '2024-08-01', DATE '2025-05-31')")
    con.execute("INSERT INTO bookmakers VALUES ('bk', 'Book', 'SHARP', TRUE, 0.0, NULL, 'ENG', NULL)")
    con.execute("INSERT INTO players VALUES ('p1', 'A Player', NULL, now(), NULL)")
    yield con
    con.close()


def _match(con, i):
    mid = f"m{i}"
    kickoff = KICKOFF + timedelta(days=i)
    con.execute("INSERT INTO teams (team_id, canonical_name, country, created_at) "
                "VALUES (?, ?, 'ENG', now())", [f"th{i}", f"Home {i}"])
    con.execute("INSERT INTO teams (team_id, canonical_name, country, created_at) "
                "VALUES (?, ?, 'ENG', now())", [f"ta{i}", f"Away {i}"])
    con.execute(
        """INSERT INTO matches (match_id, competition_id, season_id, match_date_utc,
                                kickoff_utc, home_team_id, away_team_id, status, ingested_at)
           VALUES (?, 'ENG_PL', '2024-2025', ?, ?, ?, ?, 'SCHEDULED', now())""",
        [mid, kickoff.date(), kickoff, f"th{i}", f"ta{i}"])
    published = kickoff - timedelta(minutes=70)
    con.execute(
        """INSERT INTO lineups (lineup_id, match_id, team_id, source, published_at,
                                lineup_status, ingested_at)
           VALUES (?, ?, ?, 'test', ?, 'CONFIRMED', now())""",
        [f"l{i}", mid, f"th{i}", published])
    con.execute("INSERT INTO lineup_slots VALUES (?, 'p1', 'STARTER', 9)", [f"l{i}"])
    return mid, published


def _prices(con, mid, published, pre_drift, post_drift):
    """Four observations: two before publication, two after."""
    base = 2.50
    points = [
        (published - timedelta(minutes=40), base),
        (published - timedelta(minutes=5), base * (1 + pre_drift)),
        (published + timedelta(minutes=5), base * (1 + pre_drift)),
        (published + timedelta(minutes=40), base * (1 + pre_drift) * (1 + post_drift)),
    ]
    for j, (ts, price) in enumerate(points):
        con.execute(
            """INSERT INTO odds_observations
               (observation_id, match_id, bookmaker_id, market_type, line, selection,
                price_decimal, capture_precision, captured_at, source, ingested_at)
               VALUES (?, ?, 'bk', 'ONE_X_TWO', 0.0, 'HOME', ?, 'TIMESTAMPED', ?,
                       'test', now())""",
            [f"o_{mid}_{j}", mid, price, ts])


class TestTheTimestampRule:
    def test_an_event_study_on_untimestamped_prices_refuses_to_run(self, db):
        """The one place where refusing to compute is correct. Everywhere else
        an audit reports and continues; here a number produced anyway would be
        indistinguishable from a real one."""
        mid, published = _match(db, 0)
        db.execute(
            """INSERT INTO odds_observations
               (observation_id, match_id, bookmaker_id, market_type, line, selection,
                price_decimal, capture_precision, captured_at, source, ingested_at)
               VALUES ('o1', ?, 'bk', 'ONE_X_TWO', 0.0, 'HOME', 2.5,
                       'PREMATCH', NULL, 'test', now())""", [mid])
        with pytest.raises(RuntimeError, match="TIMESTAMPED"):
            require_timestamped(db)
        with pytest.raises(RuntimeError):
            measure_windows(db)

    def test_it_runs_once_prices_carry_instants(self, db):
        mid, published = _match(db, 0)
        _prices(db, mid, published, 0.0, 0.05)
        require_timestamped(db)
        assert len(measure_windows(db)) == 1


class TestDifferenceInDifferences:
    def _world(self, con, *, treated_post_drift, n=40):
        """Half the matches carry a goalkeeper shock, half carry nothing.

        Both groups drift identically BEFORE publication, so anything the
        design finds has to come from the post window.
        """
        treated = set()
        for i in range(n):
            mid, published = _match(con, i)
            is_treated = i % 2 == 0
            if is_treated:
                treated.add(mid)
            # A deterministic pre-drift that alternates sign, identical in
            # both groups: it must cancel in the double difference.
            pre = 0.02 if i % 4 < 2 else -0.02
            post = treated_post_drift if is_treated else 0.0
            _prices(con, mid, published, pre, post)
        return treated

    def test_a_planted_effect_is_found(self, db):
        treated = self._world(db, treated_post_drift=0.08)
        windows = measure_windows(db)
        result = difference_in_differences(
            windows,
            lambda m: (Category.GOALKEEPER_OUT,) if m in treated else (),
            category=Category.GOALKEEPER_OUT)
        assert result is not None
        assert result.effect > 0
        assert result.p_value < 0.01, (
            "the instrument must find an effect this large, or it cannot be "
            "trusted to report that smaller ones are absent"
        )

    def test_no_effect_is_not_invented(self, db):
        """The same world with nothing planted. Must come back null."""
        treated = self._world(db, treated_post_drift=0.0)
        windows = measure_windows(db)
        result = difference_in_differences(
            windows,
            lambda m: (Category.GOALKEEPER_OUT,) if m in treated else (),
            category=Category.GOALKEEPER_OUT)
        assert result is not None
        assert result.p_value > 0.10

    def test_the_pre_window_drift_cancels(self, db):
        """The design's whole purpose: match-level volatility must not leak
        into the estimate."""
        treated = self._world(db, treated_post_drift=0.0)
        windows = measure_windows(db)
        assert any(abs(w.pre_move) > 0.01 for w in windows), (
            "the fixture must contain pre-window movement, or this proves nothing"
        )
        result = difference_in_differences(
            windows,
            lambda m: (Category.GOALKEEPER_OUT,) if m in treated else (),
            category=Category.GOALKEEPER_OUT)
        assert abs(result.effect) < 0.01

    def test_too_few_matches_returns_none_rather_than_a_number(self, db):
        mid, published = _match(db, 0)
        _prices(db, mid, published, 0.0, 0.05)
        windows = measure_windows(db)
        assert difference_in_differences(
            windows, lambda m: (Category.GOALKEEPER_OUT,),
            category=Category.GOALKEEPER_OUT) is None

    def test_every_category_is_testable(self, db):
        treated = self._world(db, treated_post_drift=0.05)
        windows = measure_windows(db)
        for category in CATEGORIES:
            result = difference_in_differences(
                windows,
                lambda m, c=category: (c,) if m in treated else (),
                category=category)
            assert result is not None, category
