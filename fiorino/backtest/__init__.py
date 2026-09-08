"""
Walk-forward simulation (M4).

engine.py      the cohort loop
ledger.py      equity, exposure, and what may actually be staked
settlement.py  resolves bets across all five outcome states
frictions.py   commission, rounding, stake limits, slippage
strategy.py    the candidate protocol and the naive baselines
metrics.py     yield on TURNOVER, drawdown, Sharpe, bootstrap CI, CLV first

The bias this replaces: settling same-kickoff matches sequentially, so each
stake compounds on results that were not yet knowable. Cohorts fix it by
sizing every simultaneous bet against one equity snapshot.
"""

from .engine import BacktestConfig, BacktestResult, run_backtest
from .frictions import NO_FRICTIONS, Frictions
from .ledger import Ledger
from .metrics import BacktestMetrics, compute_metrics
from .settlement import settle
from .strategy import Candidate, TakeFavourite, TakeSelection, TakeValueVsClose

__all__ = [
    "run_backtest",
    "BacktestConfig",
    "BacktestResult",
    "Ledger",
    "Frictions",
    "NO_FRICTIONS",
    "settle",
    "compute_metrics",
    "BacktestMetrics",
    "Candidate",
    "TakeSelection",
    "TakeFavourite",
    "TakeValueVsClose",
]
