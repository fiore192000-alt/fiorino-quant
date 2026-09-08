"""
Walk-forward simulation.

engine.py     — the cohort loop.
clock.py      — drives decision instants; nothing reads wall-clock time.
ledger.py     — append-only bet record; equity, open exposure, available.
settlement.py — resolves WIN/HALF_WIN/PUSH/HALF_LOSE/LOSE against results.
frictions.py  — commission, min/max stake, rounding, price slippage.
metrics.py    — yield on turnover, max drawdown, Sharpe, bootstrap CIs and
                CLV as the headline.

The bias this replaces: settling same-kickoff fixtures sequentially, so
that each bet compounds on results that were not yet knowable. Cohorts fix
it by sizing every simultaneous bet against one equity snapshot.
"""
