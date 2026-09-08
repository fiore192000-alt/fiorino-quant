"""
Settlement algebra for football betting markets.

The point of this module is a refusal: a bet's outcome is NOT a coin flip.
Asian handicaps and totals settle across five states, and collapsing them to a
single ``prob_win`` silently misprices every integer and quarter line.

    WIN         stake * price
    HALF_WIN    stake * (1 + (price - 1) / 2)      quarter lines
    PUSH        stake                              integer lines
    HALF_LOSE   stake * 0.5                        quarter lines
    LOSE        0

Everything downstream — EV, Kelly, settlement, the ``predictions`` table — is
built on :class:`OutcomeStructure` and keeps all five states explicit.

Pure specification: no IO, no database, no third-party dependencies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

__all__ = [
    "Outcome",
    "settle_bet",
    "OutcomeStructure",
    "Side",
    "asian_handicap_outcomes",
    "totals_outcomes",
    "one_x_two_outcomes",
    "is_quarter_line",
    "return_multiplier",
]

_TOL = 1e-9


class Outcome(str, Enum):
    """The five ways a stake can come back. Mirrors ``settle_t`` in the schema."""

    WIN = "WIN"
    HALF_WIN = "HALF_WIN"
    PUSH = "PUSH"
    HALF_LOSE = "HALF_LOSE"
    LOSE = "LOSE"


class Side(str, Enum):
    HOME = "HOME"
    AWAY = "AWAY"
    OVER = "OVER"
    UNDER = "UNDER"


def return_multiplier(outcome: Outcome, price: float) -> float:
    """Gross return per unit staked, stake included.

    ``LOSE`` returns 0, ``PUSH`` returns the stake, ``WIN`` returns the full
    price. The half states split the stake across two adjacent lines.
    """
    if price <= 1.0:
        raise ValueError(f"decimal price must exceed 1.0, got {price}")
    if outcome is Outcome.WIN:
        return price
    if outcome is Outcome.HALF_WIN:
        return 1.0 + (price - 1.0) / 2.0
    if outcome is Outcome.PUSH:
        return 1.0
    if outcome is Outcome.HALF_LOSE:
        return 0.5
    return 0.0


def is_quarter_line(line: float) -> bool:
    """True for .25 / .75 lines, which split the stake over two half-lines."""
    return not math.isclose(abs(line * 2.0) % 1.0, 0.0, abs_tol=_TOL)


@dataclass(frozen=True)
class OutcomeStructure:
    """Probability mass over the five settlement states for one selection.

    Construct it from a score grid via :func:`asian_handicap_outcomes` or
    :func:`totals_outcomes` rather than by hand, so the structure always
    matches the line it came from.
    """

    win: float
    half_win: float = 0.0
    push: float = 0.0
    half_lose: float = 0.0
    lose: float = 0.0

    def __post_init__(self) -> None:
        for name, p in self.as_dict().items():
            if p < -_TOL or p > 1.0 + _TOL:
                raise ValueError(f"{name} probability out of range: {p}")
        total = sum(self.as_dict().values())
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError(f"outcome probabilities must sum to 1.0, got {total}")

    def as_dict(self) -> dict[str, float]:
        return {
            "win": self.win,
            "half_win": self.half_win,
            "push": self.push,
            "half_lose": self.half_lose,
            "lose": self.lose,
        }

    @property
    def has_push_risk(self) -> bool:
        """True when this selection cannot be priced as a two-state bet."""
        return (self.push + self.half_win + self.half_lose) > _TOL

    def expected_value(self, price: float) -> float:
        """Expected profit per unit staked.

        For a three-state market this is ``p_win * price + p_push - 1``. The
        naive two-state form ``p_win * (price - 1) - (1 - p_win)`` understates
        it by exactly ``p_push``.
        """
        return self.expected_return(price) - 1.0

    def expected_return(self, price: float) -> float:
        """Expected gross return per unit staked, stake included."""
        return sum(
            p * return_multiplier(Outcome(name.upper()), price)
            for name, p in self.as_dict().items()
        )

    def kelly_fraction(self, price: float, fraction: float = 1.0) -> float:
        """Growth-optimal stake as a fraction of bankroll, times ``fraction``.

        Three-state markets (win/push/lose) have a closed form::

            f* = (p_win * b - p_lose) / (b * (p_win + p_lose)),   b = price - 1

        which reduces to standard Kelly when ``p_push`` is zero. Quarter lines
        carry five states and have no closed form, so they are solved by
        bisection on the derivative of expected log growth — concave, so the
        root is unique.
        """
        if fraction < 0.0:
            raise ValueError("fraction must be non-negative")
        if self.expected_value(price) <= 0.0:
            return 0.0

        b = price - 1.0
        if self.half_win <= _TOL and self.half_lose <= _TOL:
            denom = b * (self.win + self.lose)
            if denom <= _TOL:
                return 0.0
            f = (self.win * b - self.lose) / denom
        else:
            f = self._kelly_bisect(price)
        return max(0.0, min(1.0, f * fraction))

    def expected_log_growth(self, price: float, stake_fraction: float) -> float:
        """E[log W] for staking ``stake_fraction`` of bankroll at ``price``."""
        total = 0.0
        for name, p in self.as_dict().items():
            if p <= 0.0:
                continue
            w = 1.0 + stake_fraction * (
                return_multiplier(Outcome(name.upper()), price) - 1.0
            )
            if w <= 0.0:
                return -math.inf
            total += p * math.log(w)
        return total

    def _kelly_bisect(self, price: float) -> float:
        """Root of dE[log W]/df on (0, 1). Concave, so bisection is safe."""
        payoffs = [
            (p, return_multiplier(Outcome(name.upper()), price) - 1.0)
            for name, p in self.as_dict().items()
            if p > 0.0
        ]

        def deriv(f: float) -> float:
            return sum(p * r / (1.0 + f * r) for p, r in payoffs)

        lo, hi = 0.0, 1.0 - 1e-9
        if deriv(lo) <= 0.0:
            return 0.0
        if deriv(hi) > 0.0:
            return hi
        for _ in range(200):
            mid = (lo + hi) / 2.0
            if deriv(mid) > 0.0:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0


def _settle_single(margin: float) -> Outcome:
    """Settle one whole/half line. ``margin`` is the handicap-adjusted result."""
    if margin > _TOL:
        return Outcome.WIN
    if margin < -_TOL:
        return Outcome.LOSE
    return Outcome.PUSH


# A quarter line places half the stake on each adjacent half-line. Those two
# lines differ by 0.5, so their settlements are always adjacent: (WIN, LOSE)
# can never occur. Anything outside this table is a bug in the caller.
_QUARTER_COMBINATION = {
    (Outcome.WIN, Outcome.WIN): Outcome.WIN,
    (Outcome.WIN, Outcome.PUSH): Outcome.HALF_WIN,
    (Outcome.PUSH, Outcome.WIN): Outcome.HALF_WIN,
    (Outcome.PUSH, Outcome.LOSE): Outcome.HALF_LOSE,
    (Outcome.LOSE, Outcome.PUSH): Outcome.HALF_LOSE,
    (Outcome.LOSE, Outcome.LOSE): Outcome.LOSE,
}


def _accumulate(grid: Sequence[Sequence[float]], margin_fn, line: float) -> OutcomeStructure:
    """Walk the score grid and bucket each cell's probability by settlement."""
    if is_quarter_line(line):
        components = (line - 0.25, line + 0.25)
    else:
        components = (line,)

    mass = {o: 0.0 for o in Outcome}
    for h, row in enumerate(grid):
        for a, p in enumerate(row):
            if p <= 0.0:
                continue
            settles = tuple(_settle_single(margin_fn(h, a) + c) for c in components)
            if len(settles) == 1:
                outcome = settles[0]
            else:
                try:
                    outcome = _QUARTER_COMBINATION[settles]
                except KeyError:  # pragma: no cover - defensive
                    raise AssertionError(
                        f"impossible quarter-line settlement {settles} at line {line}"
                    ) from None
            mass[outcome] += p

    total = sum(mass.values())
    if total <= 0.0:
        raise ValueError("probability grid is empty")
    return OutcomeStructure(
        win=mass[Outcome.WIN] / total,
        half_win=mass[Outcome.HALF_WIN] / total,
        push=mass[Outcome.PUSH] / total,
        half_lose=mass[Outcome.HALF_LOSE] / total,
        lose=mass[Outcome.LOSE] / total,
    )


def asian_handicap_outcomes(
    grid: Sequence[Sequence[float]], selection: Side, home_line: float
) -> OutcomeStructure:
    """Settlement structure for an Asian handicap.

    ``home_line`` follows schema rule R3: the line is ALWAYS stored from the
    home team's perspective. "Away +0.5" is ``home_line = -0.5`` with
    ``selection = Side.AWAY``.
    """
    if selection is Side.HOME:
        return _accumulate(grid, lambda h, a: h - a, home_line)
    if selection is Side.AWAY:
        return _accumulate(grid, lambda h, a: a - h, -home_line)
    raise ValueError(f"asian handicap selection must be HOME or AWAY, got {selection}")


def totals_outcomes(
    grid: Sequence[Sequence[float]], selection: Side, line: float
) -> OutcomeStructure:
    """Settlement structure for an over/under total, quarter lines included."""
    if selection is Side.OVER:
        return _accumulate(grid, lambda h, a: h + a, -line)
    if selection is Side.UNDER:
        return _accumulate(grid, lambda h, a: -(h + a), line)
    raise ValueError(f"totals selection must be OVER or UNDER, got {selection}")


def one_x_two_outcomes(
    grid: Sequence[Sequence[float]], selection: str
) -> OutcomeStructure:
    """1X2 never pushes, so it is a genuine two-state bet."""
    mass = {"HOME": 0.0, "DRAW": 0.0, "AWAY": 0.0}
    for h, row in enumerate(grid):
        for a, p in enumerate(row):
            mass["HOME" if h > a else "AWAY" if a > h else "DRAW"] += p
    total = sum(mass.values())
    if total <= 0.0:
        raise ValueError("probability grid is empty")
    if selection not in mass:
        raise ValueError(f"1X2 selection must be HOME, DRAW or AWAY, got {selection}")
    win = mass[selection] / total
    return OutcomeStructure(win=win, lose=1.0 - win)


def settle_bet(
    market_type: str, line: float, selection: str, goals_home: int, goals_away: int
) -> Outcome:
    """How a bet actually settled, given the final score.

    The deterministic twin of :func:`asian_handicap_outcomes`: the same margin
    algebra and the same quarter-line composition, applied to one scoreline
    instead of a probability grid. Written as reuse rather than a second
    implementation precisely because two copies of settlement logic drift, and
    a backtest that settles differently from how it priced is worthless.
    """
    market_type = market_type.upper()
    selection = selection.upper()

    if market_type == "ONE_X_TWO":
        actual = "HOME" if goals_home > goals_away else "AWAY" if goals_away > goals_home else "DRAW"
        if selection not in ("HOME", "DRAW", "AWAY"):
            raise ValueError(f"1X2 selection must be HOME, DRAW or AWAY, got {selection!r}")
        return Outcome.WIN if selection == actual else Outcome.LOSE

    if market_type == "BTTS":
        both = goals_home > 0 and goals_away > 0
        if selection not in ("YES", "NO"):
            raise ValueError(f"BTTS selection must be YES or NO, got {selection!r}")
        return Outcome.WIN if (selection == "YES") == both else Outcome.LOSE

    if market_type == "ASIAN_HANDICAP":
        if selection == "HOME":
            margin, effective = goals_home - goals_away, line
        elif selection == "AWAY":
            margin, effective = goals_away - goals_home, -line
        else:
            raise ValueError(f"handicap selection must be HOME or AWAY, got {selection!r}")
        return _settle_with_quarters(margin, effective)

    if market_type == "TOTALS":
        total = goals_home + goals_away
        if selection == "OVER":
            margin, effective = total, -line
        elif selection == "UNDER":
            margin, effective = -total, line
        else:
            raise ValueError(f"totals selection must be OVER or UNDER, got {selection!r}")
        return _settle_with_quarters(margin, effective)

    raise ValueError(f"cannot settle market type {market_type!r}")


def _settle_with_quarters(margin: float, line: float) -> Outcome:
    """Settle one line, splitting quarter lines across their two neighbours."""
    if not is_quarter_line(line):
        return _settle_single(margin + line)
    lower, upper = _settle_single(margin + line - 0.25), _settle_single(margin + line + 0.25)
    try:
        return _QUARTER_COMBINATION[(lower, upper)]
    except KeyError:  # pragma: no cover - adjacent lines cannot disagree by two
        raise AssertionError(
            f"impossible quarter-line settlement {(lower, upper)} at line {line}"
        ) from None
