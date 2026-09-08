"""
The ledger — equity, exposure, and what may actually be staked.

Three quantities, and conflating any two of them is how a backtest starts
lying:

    settled_cash    money actually returned by resolved bets
    open_exposure   stakes on bets that have not resolved
    equity          settled_cash + open_exposure  (stakes at cost)

Kelly sizes against EQUITY. The constraint is AVAILABLE, which is equity times
the exposure cap minus what is already committed. Capital tied up in a 12:30
kickoff is not available again at 15:00, and a simulation that forgets this
runs a strategy nobody could have run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

__all__ = ["Ledger", "OpenBet"]


@dataclass
class OpenBet:
    bet_id: str
    stake: Decimal
    settlement_utc: object


@dataclass
class Ledger:
    """Append-only accounting for one run."""

    initial_bankroll: Decimal
    max_exposure: float = 1.0
    settled_cash: Decimal = field(init=False)
    _open: dict = field(default_factory=dict, init=False)
    peak_equity: Decimal = field(init=False)

    def __post_init__(self) -> None:
        self.settled_cash = Decimal(str(self.initial_bankroll))
        self.peak_equity = self.settled_cash
        if not 0 < self.max_exposure <= 1.0:
            raise ValueError("max_exposure must lie in (0, 1]")

    # -- state --------------------------------------------------------
    @property
    def open_exposure(self) -> Decimal:
        return sum((b.stake for b in self._open.values()), Decimal("0"))

    @property
    def equity(self) -> Decimal:
        """Settled cash plus open stakes at cost. What Kelly sizes against."""
        return self.settled_cash + self.open_exposure

    @property
    def available(self) -> Decimal:
        """What this cohort may stake, after the exposure cap and commitments."""
        room = self.equity * Decimal(str(self.max_exposure)) - self.open_exposure
        return max(room, Decimal("0"))

    @property
    def drawdown(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return float((self.peak_equity - self.equity) / self.peak_equity)

    # -- transitions --------------------------------------------------
    def place(self, bet_id: str, stake: Decimal, settlement_utc) -> None:
        """Commit capital. Refuses to overspend rather than going negative."""
        stake = Decimal(str(stake))
        if stake < 0:
            raise ValueError("stake must be non-negative")
        if bet_id in self._open:
            raise ValueError(f"bet {bet_id} is already open")
        if stake > self.settled_cash:
            raise ValueError(
                f"cannot stake {stake} against {self.settled_cash} in settled cash; "
                "the capital constraint should have prevented this"
            )
        self.settled_cash -= stake
        self._open[bet_id] = OpenBet(bet_id, stake, settlement_utc)

    def settle(self, bet_id: str, returned: Decimal, commission: Decimal = Decimal("0")) -> Decimal:
        """Resolve a bet. Returns its P&L."""
        if bet_id not in self._open:
            raise KeyError(f"bet {bet_id} is not open")
        bet = self._open.pop(bet_id)
        returned = Decimal(str(returned))
        commission = Decimal(str(commission))
        self.settled_cash += returned - commission
        self.peak_equity = max(self.peak_equity, self.equity)
        return returned - bet.stake - commission

    def due(self, as_of) -> list[OpenBet]:
        """Bets whose settlement instant has arrived, oldest first."""
        return sorted(
            (b for b in self._open.values() if b.settlement_utc <= as_of),
            key=lambda b: (b.settlement_utc, b.bet_id),
        )

    @property
    def open_count(self) -> int:
        return len(self._open)
