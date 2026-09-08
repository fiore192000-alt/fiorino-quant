"""
Backtest metrics.

Yield is on TURNOVER, not on the initial bankroll. "ROI 237%" against a bankroll
that was recycled forty times is a number about staking volume, not about edge.

CLV leads the report, because it is the metric that converges first.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

__all__ = ["BacktestMetrics", "compute_metrics", "bootstrap_yield_ci"]


@dataclass
class BacktestMetrics:
    run_id: str
    n_bets: int
    n_settled: int
    turnover: float
    pnl: float
    yield_on_turnover: float
    initial_bankroll: float
    final_equity: float
    growth: float
    max_drawdown: float
    win_rate: float
    sharpe: float
    mean_clv_ev: float | None
    clv_t_stat: float | None
    #: Mean relative price advantage over the close. clv_ev is the headline
    #: because it is what the bankroll experiences; clv_price is reported
    #: beside it because it is the number a trader recognises, and the two can
    #: disagree in sign when the closing overround is large.
    mean_clv_price: float | None = None
    #: Fraction of bets struck at a better price than the close. Sign only —
    #: it says how OFTEN, never by how much, so it cannot stand alone.
    beat_close_rate: float | None = None
    yield_ci_low: float | None = None
    yield_ci_high: float | None = None

    @property
    def verdict(self) -> str:
        """A one-line reading that resists the usual self-flattery."""
        if self.n_settled < 30:
            return "too few settled bets to say anything"
        if self.mean_clv_ev is None:
            return "no CLV available: unverifiable"
        if self.mean_clv_ev > 0 and self.yield_on_turnover < 0:
            return "positive CLV, negative yield: unlucky, edge plausible"
        if self.mean_clv_ev < 0 and self.yield_on_turnover > 0:
            return "negative CLV, positive yield: lucky, expect it to stop"
        if self.mean_clv_ev < 0:
            return "negative CLV and negative yield: no edge"
        return "positive CLV and positive yield: consistent with an edge"


def compute_metrics(con, run_id: str, *, bootstrap: int = 0, seed: int = 0) -> BacktestMetrics:
    row = con.execute(
        """SELECT count(*), sum(b.stake), sum(s.pnl),
                  count(*) FILTER (WHERE s.outcome IN ('WIN', 'HALF_WIN'))
           FROM bets b JOIN bet_settlements s ON s.bet_id = b.bet_id
           WHERE b.run_id = ?""",
        [run_id],
    ).fetchone()
    n_settled = row[0] or 0
    turnover = float(row[1] or 0)
    pnl = float(row[2] or 0)
    wins = row[3] or 0

    n_bets, = con.execute("SELECT count(*) FROM bets WHERE run_id = ?", [run_id]).fetchone()
    initial, = con.execute(
        "SELECT initial_bankroll FROM backtest_runs WHERE run_id = ?", [run_id]
    ).fetchone()
    initial = float(initial)

    final_row = con.execute(
        "SELECT equity FROM equity_curve WHERE run_id = ? ORDER BY ts DESC LIMIT 1", [run_id]
    ).fetchone()
    final = float(final_row[0]) if final_row else initial

    dd_row = con.execute(
        "SELECT max(drawdown) FROM equity_curve WHERE run_id = ?", [run_id]
    ).fetchone()
    max_dd = float(dd_row[0]) if dd_row and dd_row[0] is not None else 0.0

    # Sharpe on per-bet returns, which is what the ledger actually holds.
    returns = [
        float(r[0]) for r in con.execute(
            """SELECT s.pnl / nullif(b.stake, 0) FROM bets b
               JOIN bet_settlements s ON s.bet_id = b.bet_id
               WHERE b.run_id = ? AND b.stake > 0""", [run_id]
        ).fetchall() if r[0] is not None
    ]
    sharpe = 0.0
    if len(returns) > 1:
        mean = sum(returns) / len(returns)
        var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        sharpe = mean / math.sqrt(var) * math.sqrt(len(returns)) if var > 0 else 0.0

    clv_row = con.execute(
        """SELECT avg(c.clv_ev), stddev_samp(c.clv_ev), count(*),
                  avg(c.clv_price),
                  avg(CASE WHEN c.beat_close THEN 1.0 ELSE 0.0 END)
           FROM bets b JOIN bet_clv c ON c.bet_id = b.bet_id
           WHERE b.run_id = ? AND c.line_matched""", [run_id]
    ).fetchone()
    mean_clv = clv_row[0]
    clv_t = None
    if mean_clv is not None and clv_row[1] and clv_row[2] > 1:
        clv_t = mean_clv / (clv_row[1] / math.sqrt(clv_row[2]))

    metrics = BacktestMetrics(
        run_id=run_id,
        n_bets=n_bets,
        n_settled=n_settled,
        turnover=turnover,
        pnl=pnl,
        yield_on_turnover=pnl / turnover if turnover else 0.0,
        initial_bankroll=initial,
        final_equity=final,
        growth=final / initial - 1 if initial else 0.0,
        max_drawdown=max_dd,
        win_rate=wins / n_settled if n_settled else 0.0,
        sharpe=sharpe,
        mean_clv_ev=mean_clv,
        clv_t_stat=clv_t,
        mean_clv_price=clv_row[3],
        beat_close_rate=clv_row[4],
    )
    if bootstrap and returns:
        metrics.yield_ci_low, metrics.yield_ci_high = bootstrap_yield_ci(
            returns, n=bootstrap, seed=seed
        )
    return metrics


def bootstrap_yield_ci(returns, n: int = 2000, seed: int = 0, alpha: float = 0.05):
    """Percentile bootstrap on per-bet returns.

    Betting returns are wildly non-normal — mostly -1, occasionally +4 — so a
    normal confidence interval understates how wide the uncertainty really is.
    Resampling makes no distributional assumption.
    """
    if not returns:
        return None, None
    rng = random.Random(seed)
    k = len(returns)
    means = sorted(
        sum(rng.choice(returns) for _ in range(k)) / k for _ in range(n)
    )
    lo = means[int(alpha / 2 * n)]
    hi = means[min(int((1 - alpha / 2) * n), n - 1)]
    return lo, hi
