"""
M2 — market reconstruction, against real Football-Data output.

The governing rule, tested rather than trusted: never invent a timestamp for an
observation that has none.
"""

from pathlib import Path

import pytest

from fiorino.config.registries import BOOKMAKERS, reference_bookmaker
from fiorino.data.ingest.sources.footballdata import FootballData
from fiorino.data.lake import bronze_path, write_bronze
from fiorino.data.pipeline import ingest_bronze
from fiorino.odds.devig import DEFAULT_METHOD, METHODS, devig, overround

REAL = (Path(__file__).parent / "fixtures" / "footballdata_e0_2017-18_real.csv").read_text()

#: Real Pinnacle closing prices, Arsenal v Leicester, 2017-08-11.
REAL_CLOSE = [1.49, 4.73, 7.25]


@pytest.fixture
def odds_db(seeded_db, tmp_path):
    """A database with one real Football-Data season ingested."""
    rows = FootballData().parse(REAL, "ENG_PL", "2017-2018")
    write_bronze(seeded_db, [r.as_row() for r in rows],
                 bronze_path(tmp_path, "footballdata", "ENG_PL", "2017-2018", "real"))
    ingest_bronze(seeded_db, tmp_path, auto_register_unknown=True)
    return seeded_db


class TestBookmakerRegistry:
    def test_exactly_one_reference_book(self):
        assert reference_bookmaker() == "pinnacle"

    def test_the_reference_is_a_sharp_book(self):
        assert BOOKMAKERS["pinnacle"][1] == "SHARP"

    def test_the_registry_reaches_the_database(self, seeded_db):
        rows = seeded_db.execute(
            "SELECT bookmaker_id FROM bookmakers WHERE is_reference"
        ).fetchall()
        assert rows == [("pinnacle",)]


class TestDevig:
    def test_overround_on_a_real_pinnacle_close(self):
        """~2% is Pinnacle's signature; a wildly different figure means the
        wrong columns are being read as the close."""
        assert 0.015 < overround(REAL_CLOSE) < 0.03

    def test_fair_probabilities_sum_to_one(self):
        for method in METHODS:
            result = devig(["HOME", "DRAW", "AWAY"], REAL_CLOSE, method)
            assert sum(result.fair_probs) == pytest.approx(1.0)

    def test_shin_shades_the_longshot_below_multiplicative(self):
        """The reason Shin is the default: books load margin onto longshots,
        so multiplicative de-vigging overstates them — precisely where a value
        bettor is looking."""
        shin = devig(["H", "D", "A"], REAL_CLOSE, "SHIN").fair_probs
        mult = devig(["H", "D", "A"], REAL_CLOSE, "MULTIPLICATIVE").fair_probs
        assert shin[2] < mult[2]        # longshot
        assert shin[0] > mult[0]        # favourite

    def test_fair_probabilities_are_below_raw_implied(self):
        result = devig(["H", "D", "A"], REAL_CLOSE, DEFAULT_METHOD)
        assert all(f < r for f, r in zip(result.fair_probs, result.raw_implied))

    def test_an_incomplete_market_is_refused(self):
        with pytest.raises(ValueError, match="at least two"):
            devig(["HOME"], [1.5])

    def test_duplicate_selections_are_refused(self):
        with pytest.raises(ValueError, match="duplicate"):
            devig(["HOME", "HOME"], [2.0, 2.0])

    def test_a_sub_unity_book_is_refused_not_normalised(self):
        """Sum below 1.0 is an arbitrage or a corrupt row. Either way it is not
        a market to de-vig silently."""
        with pytest.raises(ValueError, match="arbitrage or a corrupt row"):
            devig(["H", "D", "A"], [4.0, 4.0, 4.0])

    def test_an_unknown_method_is_refused(self):
        with pytest.raises(ValueError, match="unknown de-vig method"):
            devig(["H", "A"], [2.0, 2.0], "VIBES")


class TestNoInventedTimestamps:
    """The M2 constraint, enforced by schema and verified end to end."""

    def test_nothing_from_football_data_carries_a_clock(self, odds_db):
        n = odds_db.execute(
            "SELECT count(*) FROM odds_observations WHERE captured_at IS NOT NULL"
        ).fetchone()[0]
        assert n == 0, "this source timestamps nothing; a clock here is fabricated"

    def test_the_known_bound_is_recorded_instead(self, odds_db):
        n = odds_db.execute(
            "SELECT count(*) FROM odds_observations WHERE observed_before IS NULL"
        ).fetchone()[0]
        assert n == 0, "every price should record the bound that IS known"

    def test_the_schema_rejects_a_timestamped_row_without_a_clock(self, odds_db):
        with pytest.raises(Exception):
            odds_db.execute(
                """INSERT INTO odds_observations
                   (observation_id, match_id, bookmaker_id, market_type, line, selection,
                    price_decimal, capture_precision, captured_at, source)
                   SELECT 'bad', match_id, 'pinnacle', 'ONE_X_TWO', 0.0, 'HOME',
                          2.0, 'TIMESTAMPED', NULL, 't'
                   FROM matches LIMIT 1"""
            )

    def test_the_schema_rejects_a_prematch_row_with_a_clock(self, odds_db):
        with pytest.raises(Exception):
            odds_db.execute(
                """INSERT INTO odds_observations
                   (observation_id, match_id, bookmaker_id, market_type, line, selection,
                    price_decimal, capture_precision, captured_at, source)
                   SELECT 'bad2', match_id, 'pinnacle', 'ONE_X_TWO', 0.0, 'HOME',
                          2.0, 'PREMATCH', now(), 't'
                   FROM matches LIMIT 1"""
            )

    def test_the_point_in_time_reader_ignores_untimestamped_prices(self, odds_db):
        """A price with no clock cannot answer 'what was available at T'."""
        n = odds_db.execute(
            "SELECT count(*) FROM odds_as_of('2030-01-01 00:00:00+00')"
        ).fetchone()[0]
        assert n == 0
        assert odds_db.execute("SELECT count(*) FROM odds_observations").fetchone()[0] > 0


class TestObservations:
    def test_both_precisions_are_ingested(self, odds_db):
        by_precision = dict(odds_db.execute(
            "SELECT capture_precision, count(*) FROM odds_observations GROUP BY 1"
        ).fetchall())
        assert set(by_precision) == {"PREMATCH", "CLOSING"}

    def test_the_reference_book_has_both_precisions_in_equal_number(self, odds_db):
        """Scoped to Pinnacle. Other books publish a pre-match price without a
        closing one in older files, so a global equality would be false for a
        reason that has nothing to do with correctness."""
        by_precision = dict(odds_db.execute(
            """SELECT capture_precision, count(*) FROM odds_observations
               WHERE bookmaker_id = 'pinnacle' GROUP BY 1"""
        ).fetchall())
        assert by_precision["PREMATCH"] == by_precision["CLOSING"]

    def test_every_available_book_is_kept(self, odds_db):
        """Best price cannot be shopped from one book, so none is discarded."""
        books = {r[0] for r in odds_db.execute(
            "SELECT DISTINCT bookmaker_id FROM odds_observations"
        ).fetchall()}
        assert "pinnacle" in books
        assert len(books) > 1, "other books present in the file were dropped"

    def test_three_selections_per_market(self, odds_db):
        """A complete 1X2 has exactly three selections — per BOOK and per
        precision. Grouping without the book counts two books as one market."""
        counts = odds_db.execute(
            """SELECT count(*) FROM (
                 SELECT match_id, bookmaker_id, capture_precision, count(*) c
                 FROM odds_observations WHERE market_type = 'ONE_X_TWO'
                 GROUP BY 1, 2, 3) WHERE c <> 3"""
        ).fetchone()[0]
        assert counts == 0

    def test_ingestion_is_idempotent(self, odds_db, tmp_path):
        before = odds_db.execute("SELECT count(*) FROM odds_observations").fetchone()[0]
        rows = FootballData().parse(REAL, "ENG_PL", "2017-2018")
        from fiorino.odds.ingest import ingest_odds

        again = ingest_odds(odds_db, [r.as_row() for r in rows])
        assert again.observations == 0
        assert odds_db.execute("SELECT count(*) FROM odds_observations").fetchone()[0] == before

    def test_odds_never_attach_to_a_quarantined_match(self, odds_db):
        n = odds_db.execute(
            """SELECT count(*) FROM odds_observations o
               WHERE NOT EXISTS (SELECT 1 FROM v_analytic_matches m
                                 WHERE m.match_id = o.match_id)"""
        ).fetchone()[0]
        assert n == 0


class TestClosingLine:
    def test_the_close_is_declared_by_the_source(self, odds_db):
        bases = odds_db.execute(
            "SELECT DISTINCT closing_basis FROM odds_closing"
        ).fetchall()
        assert bases == [("DECLARED",)]

    def test_one_closing_row_per_market_selection(self, odds_db):
        dupes = odds_db.execute(
            """SELECT count(*) FROM (
                 SELECT match_id, bookmaker_id, market_type, line, selection, count(*) c
                 FROM odds_closing GROUP BY 1,2,3,4,5) WHERE c > 1"""
        ).fetchone()[0]
        assert dupes == 0

    def test_closing_prices_differ_from_prematch(self, odds_db):
        """If they never differed, the two columns would be one reading."""
        moved = odds_db.execute(
            "SELECT count(*) FROM v_line_movement WHERE drift IS NOT NULL AND abs(drift) > 0.001"
        ).fetchone()[0]
        assert moved > 0


class TestReferenceMarket:
    """What M3 will consume."""

    def test_it_carries_only_the_reference_book(self, odds_db):
        books = odds_db.execute(
            "SELECT DISTINCT reference_bookmaker_id FROM reference_market"
        ).fetchall()
        assert books == [("pinnacle",)]

    def test_every_row_has_a_fair_probability(self, odds_db):
        missing = odds_db.execute(
            "SELECT count(*) FROM reference_market WHERE closing_fair_prob IS NULL"
        ).fetchone()[0]
        assert missing == 0

    def test_fair_probabilities_sum_to_one_per_market(self, odds_db):
        bad = odds_db.execute(
            """SELECT count(*) FROM (
                 SELECT match_id, market_type, line, sum(closing_fair_prob) s
                 FROM reference_market GROUP BY 1,2,3) WHERE abs(s - 1.0) > 1e-6"""
        ).fetchone()[0]
        assert bad == 0

    def test_the_overround_is_pinnacle_shaped(self, odds_db):
        lo, med, hi = odds_db.execute(
            "SELECT min(closing_overround), median(closing_overround), max(closing_overround) "
            "FROM reference_market"
        ).fetchone()
        assert 0.005 < lo and hi < 0.06
        assert 0.015 < med < 0.03

    def test_coverage_is_reported(self, odds_db):
        row = odds_db.execute(
            "SELECT n_matches, n_with_reference_close, reference_close_coverage "
            "FROM v_odds_coverage"
        ).fetchone()
        assert row[0] > 0 and row[1] == row[0] and row[2] == pytest.approx(1.0)


class TestDevigFallbackIsHonest:
    """The de-vig may fall back. It must never lie about having done so.

    M3 established that the CLV calibration identity holds under multiplicative
    de-vig and NOT under Shin. A multiplicative result wearing a SHIN label
    would quietly invalidate every check built on that identity, which is a
    worse failure than refusing to compute.
    """

    PRICES = [2.10, 3.40, 3.60]

    def test_a_successful_devig_reports_what_was_asked(self):
        from fiorino.odds.devig import devig

        result = devig(["HOME", "DRAW", "AWAY"], self.PRICES, method="SHIN")
        assert result.method == result.requested_method
        assert not result.fell_back

    def test_an_absent_penaltyblog_falls_back_and_says_so(self, monkeypatch):
        """The clean-clone case: the repository's own penaltyblog directory
        shadows any installed copy and its Cython extensions are not built."""
        import builtins

        from fiorino.odds.devig import devig

        real_import = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name.startswith("penaltyblog"):
                raise ModuleNotFoundError("No module named 'penaltyblog.metrics.metrics'")
            return real_import(name, *args, **kwargs)

        import importlib

        # fiorino.odds re-exports devig as a FUNCTION, which shadows the
        # module of the same name.
        devig_module = importlib.import_module("fiorino.odds.devig")

        monkeypatch.setattr(devig_module, "_SOLVER", None)
        monkeypatch.setattr(builtins, "__import__", blocked)
        result = devig(["HOME", "DRAW", "AWAY"], self.PRICES, method="SHIN")

        assert result.fell_back
        assert result.method == "MULTIPLICATIVE"
        assert result.requested_method == "SHIN"
        assert sum(result.fair_probs) == pytest.approx(1.0)

    def test_the_solver_is_probed_once_not_per_call(self, monkeypatch):
        """Probing per call is non-deterministic: a failed `import penaltyblog`
        can leave submodules in sys.modules so the SECOND attempt succeeds. One
        rebuild then tags rows SHIN and MULTIPLICATIVE and the next tags only
        SHIN, from identical input — which breaks rule A, semantic determinism
        of rebuilds, and breaks it quietly."""
        import builtins

        import importlib

        # fiorino.odds re-exports devig as a FUNCTION, which shadows the
        # module of the same name.
        devig_module = importlib.import_module("fiorino.odds.devig")

        monkeypatch.setattr(devig_module, "_SOLVER", None)
        attempts = []
        real_import = builtins.__import__

        def counting(name, *args, **kwargs):
            if name.startswith("penaltyblog"):
                attempts.append(name)
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", counting)
        for _ in range(5):
            devig_module.devig(["HOME", "DRAW", "AWAY"], self.PRICES, method="SHIN")
        assert len(attempts) <= 1, f"probed {len(attempts)} times: {attempts}"

    def test_the_method_is_stable_across_repeated_devigs(self, monkeypatch):
        from fiorino.odds.devig import devig

        methods = {devig(["HOME", "DRAW", "AWAY"], self.PRICES, method="SHIN").method
                   for _ in range(10)}
        assert len(methods) == 1, f"the de-vig method drifted: {methods}"

    def test_the_fallback_still_produces_a_distribution(self, monkeypatch):
        import builtins

        from fiorino.odds.devig import devig

        import importlib

        # fiorino.odds re-exports devig as a FUNCTION, which shadows the
        # module of the same name.
        devig_module = importlib.import_module("fiorino.odds.devig")

        real_import = builtins.__import__
        monkeypatch.setattr(devig_module, "_SOLVER", None)
        monkeypatch.setattr(
            builtins, "__import__",
            lambda n, *a, **k: (_ for _ in ()).throw(ImportError())
            if n.startswith("penaltyblog") else real_import(n, *a, **k))
        result = devig(["HOME", "DRAW", "AWAY"], self.PRICES, method="SHIN")
        assert all(0 < p < 1 for p in result.fair_probs)
        assert sum(result.fair_probs) == pytest.approx(1.0)
