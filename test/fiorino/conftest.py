"""Shared fixtures for the Fiorino specification suite."""

import sys
from pathlib import Path

# Let tests do `from factories import ...` without packaging the fixture module.
sys.path.insert(0, str(Path(__file__).parent))


import pytest


@pytest.fixture
def poisson_grid():
    """A 2D score grid P[home][away] from independent Poisson marginals.

    Deliberately hand-rolled rather than taken from penaltyblog: these are
    specification tests, and they must not pass or fail because of a change
    in a dependency.
    """
    import math

    def _build(mu_home: float, mu_away: float, max_goals: int = 12):
        def pmf(k, mu):
            return math.exp(-mu) * mu**k / math.factorial(k)

        h = [pmf(i, mu_home) for i in range(max_goals + 1)]
        a = [pmf(j, mu_away) for j in range(max_goals + 1)]
        grid = [[hi * aj for aj in a] for hi in h]
        total = sum(sum(row) for row in grid)
        return [[c / total for c in row] for row in grid]

    return _build


@pytest.fixture
def exact_grid():
    """Build a grid from an explicit {(home, away): probability} mapping.

    Lets a test state precisely which scorelines carry mass, so the expected
    settlement can be worked out by hand rather than trusted.
    """

    def _build(mapping: dict[tuple[int, int], float], size: int = 6):
        grid = [[0.0] * size for _ in range(size)]
        for (h, a), p in mapping.items():
            grid[h][a] = p
        total = sum(sum(row) for row in grid)
        assert abs(total - 1.0) < 1e-9, f"probabilities must sum to 1, got {total}"
        return grid

    return _build


# ---------------------------------------------------------------------
# M1 data-layer fixtures
# ---------------------------------------------------------------------

import pytest as _pytest


@_pytest.fixture
def db():
    """An empty, fully migrated in-memory database."""
    from fiorino.data.db.connection import connect
    from fiorino.data.db.migrate import migrate

    con = connect()
    migrate(con)
    try:
        yield con
    finally:
        con.close()


@_pytest.fixture
def seeded_db(db):
    """Migrated database with reference dimensions loaded."""
    from fiorino.data.pipeline import bootstrap_reference

    bootstrap_reference(db)
    return db


@_pytest.fixture
def resolver(seeded_db):
    from fiorino.data.identity.resolver import IdentityResolver

    return IdentityResolver(seeded_db)


SMALL_COMPETITIONS = ["ENG_PL", "PRT_L1"]
SMALL_SEASONS = ["2017-2018", "2019-2020"]


@_pytest.fixture(scope="session")
def small_lake(tmp_path_factory):
    """Bronze for two competitions and two seasons — fast, still nasty.

    Session-scoped: the lake is immutable by construction, so building it once
    is both safe and the difference between a 4-minute suite and a 20-second
    one. Tests that mutate a database get a fresh one from `seeded_db`.
    """
    from factories import build_bronze
    from fiorino.data.db.connection import connect
    from fiorino.data.pipeline import bootstrap_reference

    root = tmp_path_factory.mktemp("lake")
    con = connect()
    bootstrap_reference(con)
    build_bronze(con, root, competitions=SMALL_COMPETITIONS, seasons=SMALL_SEASONS)
    con.close()
    return root
