"""
Market frictions — first class, not an afterthought.

A backtest without them reports a strategy that does not exist. Each friction
here removes a specific way the simulation would otherwise flatter itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

__all__ = ["Frictions", "NO_FRICTIONS"]


@dataclass(frozen=True)
class Frictions:
    """What the world charges you that a spreadsheet does not."""

    #: Exchange commission on net winnings. Books charge nothing; exchanges
    #: take 2-5% of the winnings, which converts a small edge into none.
    commission_rate: float = 0.0
    #: Stake rounding. Nobody stakes 13.7429.
    stake_increment: Decimal = Decimal("0.01")
    #: Below this, do not bother: the bet is noise and often not accepted.
    min_stake: Decimal = Decimal("0.50")
    #: What the book will actually lay. A strategy whose edge only exists at
    #: sizes no book accepts does not have an edge.
    max_stake: Decimal | None = None
    #: Fraction of the quoted price lost between deciding and striking.
    #: Applied as a haircut on the price, never on the probability.
    slippage: float = 0.0

    def round_stake(self, stake: Decimal) -> Decimal:
        """Round DOWN to the increment: rounding up invents capital."""
        if stake <= 0:
            return Decimal("0")
        increments = (stake / self.stake_increment).quantize(Decimal("1"), rounding=ROUND_DOWN)
        rounded = increments * self.stake_increment
        if self.max_stake is not None and rounded > self.max_stake:
            rounded = self.max_stake
        return rounded if rounded >= self.min_stake else Decimal("0")

    def effective_price(self, price: float) -> float:
        """The price after slippage. Never below evens, or the bet is void."""
        if self.slippage <= 0:
            return price
        adjusted = 1.0 + (price - 1.0) * (1.0 - self.slippage)
        return max(adjusted, 1.0000001)

    def commission_on(self, gross_profit: Decimal) -> Decimal:
        """Charged on NET WINNINGS only — losses are not taxed twice."""
        if self.commission_rate <= 0 or gross_profit <= 0:
            return Decimal("0")
        return (gross_profit * Decimal(str(self.commission_rate))).quantize(
            Decimal("0.000001"), rounding=ROUND_DOWN
        )


#: For tests that isolate one behaviour. Never a sane default for a real run.
NO_FRICTIONS = Frictions(min_stake=Decimal("0"))
