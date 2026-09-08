"""
Closing Line Value — the primary edge signal (M3).

formulas.py  the arithmetic, isolated and pure
compute.py   scores bets against the reference book's de-vigged close
replay.py    instruments to populate the ledger without a model, for validation

Why this exists: CLV converges on the truth in hundreds of bets; P&L needs
thousands. A strategy with negative CLV and positive P&L is lucky, and knowing
that early is worth more than the P&L.

M3 measures. It does not size, select or settle.
"""

from .compute import ClvResult, bet_id_for, compute_clv, record_bet
from .formulas import beat_close, clv_ev, clv_log, clv_price

__all__ = [
    "clv_price",
    "clv_ev",
    "clv_log",
    "beat_close",
    "compute_clv",
    "record_bet",
    "bet_id_for",
    "ClvResult",
]
