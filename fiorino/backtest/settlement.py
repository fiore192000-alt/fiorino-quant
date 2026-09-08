"""Resolve bets against results, across all five settlement states."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from fiorino.core.markets import Outcome, return_multiplier, settle_bet

__all__ = ["Settled", "settle"]


@dataclass(frozen=True)
class Settled:
    bet_id: str
    outcome: Outcome
    returned: Decimal
    commission: Decimal
    pnl: Decimal


def settle(bet_id, market_type, line, selection, price, stake, goals_home, goals_away,
           frictions) -> Settled:
    """Settle one bet. Commission applies to net winnings only."""
    stake = Decimal(str(stake))
    outcome = settle_bet(market_type, line, selection, int(goals_home), int(goals_away))
    multiplier = Decimal(str(return_multiplier(outcome, float(price))))
    returned = (stake * multiplier).quantize(Decimal("0.000001"))
    gross_profit = returned - stake
    commission = frictions.commission_on(gross_profit)
    return Settled(bet_id, outcome, returned, commission, gross_profit - commission)
