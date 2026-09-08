"""Shared fixtures for the Fiorino specification suite."""

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
