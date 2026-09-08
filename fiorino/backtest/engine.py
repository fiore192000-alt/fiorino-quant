"""
The cohort loop.

One rule governs the whole file: every bet in a cohort is sized against ONE
equity snapshot, taken before any of them resolves. Threading a mutating
bankroll through the loop is the bug this engine exists to eliminate, and it is
invisible in the output — it just makes every strategy look better.

    WRONG      bankroll 100, three 15:00 kickoffs at 50% -> 50, 75, 112.50
    REQUIRED                                             -> 50, 50, 50
                                                            then constrained
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from fiorino.core.capital import OversizePolicy, apply_capital_constraint
from fiorino.data.access.point_in_time import PointInTimeView

from .frictions import Frictions
from .ledger import Ledger
from .settlement import settle

__all__ = ["BacktestConfig", "BacktestResult", "run_backtest"]

#: A result is knowable this long after kickoff. Matches the ingest rule, so
#: settlement and training agree about when a match ended.
SETTLEMENT_LAG = timedelta(hours=2)


@dataclass
class BacktestConfig:
    initial_bankroll: Decimal = Decimal("1000")
    #: Fraction of equity staked on each candidate. Flat in M4: real sizing is
    #: M7, and a flat stake makes the engine's behaviour legible.
    stake_fraction: float = 0.01
    #: Cap on total capital at risk at any instant.
    max_exposure: float = 0.25
    oversize_policy: OversizePolicy = OversizePolicy.SCALE_PRO_RATA
    frictions: Frictions = field(default_factory=Frictions)
    #: Stop when the bankroll is gone. A run that continues past ruin reports
    #: a recovery nobody could have financed.
    stop_at_ruin: bool = True
    ruin_threshold: Decimal = Decimal("0")


@dataclass
class BacktestResult:
    run_id: str
    n_cohorts: int = 0
    n_candidates: int = 0
    n_bets: int = 0
    n_settled: int = 0
    total_staked: Decimal = Decimal("0")
    final_equity: Decimal = Decimal("0")
    max_drawdown: float = 0.0
    ruined: bool = False
    constrained_cohorts: int = 0


def _cohort_id(run_id, decision_utc) -> str:
    return "c_" + hashlib.blake2b(
        f"{run_id}|{decision_utc}".encode(), digest_size=8
    ).hexdigest()


def _bet_id(run_id, cohort_id, candidate) -> str:
    payload = "|".join(str(x) for x in (
        run_id, cohort_id, candidate.match_id, candidate.bookmaker_id,
        candidate.market_type, candidate.line, candidate.selection,
    ))
    return "b_" + hashlib.blake2b(payload.encode(), digest_size=12).hexdigest()


def _decision_points(con, start_utc, end_utc):
    """One decision instant per distinct kickoff.

    Matches sharing a kickoff share a cohort — which is the entire point.
    Ordering is by instant, so capital committed earlier is already reflected
    in the exposure when a later cohort is sized.

    Why the kickoff and not something earlier: with an untimestamped source the
    only thing known about a PREMATCH price is that it was available at some
    point before kickoff. The kickoff is therefore the LATEST instant at which
    the price is certainly still real, and using it makes the weakest claim the
    data supports. A timestamped feed would let the decision move earlier and
    make that claim precise; until then, moving it earlier would be a guess
    dressed as a schedule.
    """
    rows = con.execute(
        """SELECT kickoff_utc, list(match_id ORDER BY match_id)
           FROM v_analytic_matches
           WHERE kickoff_utc >= ? AND kickoff_utc <= ?
           GROUP BY kickoff_utc ORDER BY kickoff_utc""",
        [start_utc, end_utc],
    ).fetchall()
    return [(ts, list(ids)) for ts, ids in rows]


def run_backtest(con, strategy, config: BacktestConfig, start_utc, end_utc,
                 code_version=None) -> BacktestResult:
    """Walk forward through the cohorts, sizing, placing and settling."""
    run_id = "r_" + uuid.uuid4().hex[:10]
    con.execute(
        """INSERT INTO backtest_runs
           (run_id, strategy, start_utc, end_utc, initial_bankroll, code_version)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [run_id, getattr(strategy, "name", type(strategy).__name__),
         start_utc, end_utc, config.initial_bankroll, code_version],
    )

    ledger = Ledger(config.initial_bankroll, max_exposure=config.max_exposure)
    result = BacktestResult(run_id=run_id, final_equity=config.initial_bankroll)

    for decision_utc, match_ids in _decision_points(con, start_utc, end_utc):
        # Settle everything that resolved before this decision, so the equity
        # snapshot reflects only what was genuinely knowable now.
        result.n_settled += _settle_due(con, ledger, decision_utc, config, run_id)
        _record_equity(con, run_id, ledger, decision_utc)

        if config.stop_at_ruin and ledger.equity <= config.ruin_threshold:
            result.ruined = True
            break

        # THE SNAPSHOT. Read once, before any bet in this cohort is placed.
        equity_open = ledger.equity
        open_exposure = ledger.open_exposure
        available = ledger.available

        view = PointInTimeView.at(con, decision_utc)
        candidates = _dedupe(strategy.generate(view, match_ids))
        result.n_candidates += len(candidates)
        if not candidates:
            continue

        cohort_id = _cohort_id(run_id, decision_utc)
        settlement_utc = decision_utc + SETTLEMENT_LAG

        # Every stake is a fraction of the SAME equity. Not of a running total.
        requested = [
            config.frictions.round_stake(equity_open * Decimal(str(config.stake_fraction)))
            for _ in candidates
        ]
        decision = apply_capital_constraint(
            requested, available, config.oversize_policy,
            rank=[c.rank for c in candidates]
            if config.oversize_policy is OversizePolicy.TRUNCATE_BY_RANK else None,
        )
        if decision.was_constrained:
            result.constrained_cohorts += 1

        placed = 0
        for candidate, stake in zip(candidates, decision.stakes):
            stake = config.frictions.round_stake(stake)
            if stake <= 0 or stake > ledger.settled_cash:
                continue
            bet_id = _bet_id(run_id, cohort_id, candidate)
            price = config.frictions.effective_price(candidate.price)
            con.execute(
                """INSERT INTO bets
                   (bet_id, run_id, match_id, bookmaker_id, market_type, line, selection,
                    price_taken, price_precision, placed_at, observed_before, model_prob,
                    cohort_id, stake)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)""",
                [bet_id, run_id, candidate.match_id, candidate.bookmaker_id,
                 candidate.market_type, float(candidate.line), candidate.selection,
                 float(price), candidate.price_precision, decision_utc,
                 candidate.model_prob, cohort_id, stake],
            )
            ledger.place(bet_id, stake, settlement_utc)
            placed += 1
            result.total_staked += stake

        con.execute(
            """INSERT INTO cohorts
               (cohort_id, run_id, decision_utc, settlement_utc, equity_open,
                open_exposure, available_open, n_candidates, n_bets, total_staked,
                constrained_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [cohort_id, run_id, decision_utc, settlement_utc, equity_open,
             open_exposure, available, len(candidates), placed,
             sum(decision.stakes, Decimal("0")),
             decision.policy.value if decision.was_constrained else None],
        )
        result.n_cohorts += 1
        result.n_bets += placed

    # Settle whatever is still open at the end of the window.
    far_future = end_utc + timedelta(days=3650)
    result.n_settled += _settle_due(con, ledger, far_future, config, run_id)
    _record_equity(con, run_id, ledger, end_utc)

    result.final_equity = ledger.equity
    result.max_drawdown = _max_drawdown(con, run_id)
    return result


def _dedupe(candidates):
    """One bet per selection per cohort.

    A strategy reading several model fits can legitimately propose the same
    selection twice; placing both would double the intended stake and collide
    on the bet id. The best-ranked duplicate wins.
    """
    best: dict[tuple, object] = {}
    for candidate in candidates:
        key = (candidate.match_id, candidate.bookmaker_id, candidate.market_type,
               candidate.line, candidate.selection)
        if key not in best or candidate.rank > best[key].rank:
            best[key] = candidate
    return list(best.values())


def _settle_due(con, ledger, as_of, config, run_id) -> int:
    """Resolve every open bet whose settlement instant has passed."""
    due = ledger.due(as_of)
    if not due:
        return 0
    ids = [b.bet_id for b in due]
    placeholders = ", ".join("?" for _ in ids)
    rows = con.execute(
        f"""SELECT bet_id, match_id, market_type, line, selection, price_taken, stake
            FROM bets WHERE bet_id IN ({placeholders})""",
        ids,
    ).fetchall()

    # Results are read through the point-in-time view, bounded by the
    # settlement instant. Querying the results table directly would let a bet
    # resolve against a result that was not yet knowable — leakage wearing the
    # costume of bookkeeping. The M1 guard exists to catch exactly this, and
    # caught it here.
    view = PointInTimeView.at(con, as_of)
    known = view.results_for_matches([r[1] for r in rows])

    n = 0
    for bet_id, match_id, market, line, selection, price, stake in rows:
        goals = known.get(match_id)
        if goals is None:
            # No result: the bet is void and the stake comes back untouched.
            # Treating it as a loss would invent losses from missing data.
            ledger.settle(bet_id, Decimal(str(stake)))
            con.execute(
                """INSERT INTO bet_settlements
                   (bet_id, outcome, returned, commission, pnl, settled_at)
                   VALUES (?, 'VOID', ?, 0, 0, ?)""",
                [bet_id, stake, as_of],
            )
            n += 1
            continue
        outcome = settle(bet_id, market, line, selection, price, stake,
                         goals[0], goals[1], config.frictions)
        ledger.settle(bet_id, outcome.returned, outcome.commission)
        con.execute(
            """INSERT INTO bet_settlements
               (bet_id, outcome, returned, commission, pnl, settled_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [bet_id, outcome.outcome.value, outcome.returned, outcome.commission,
             outcome.pnl, as_of],
        )
        n += 1
    return n


def _record_equity(con, run_id, ledger, ts) -> None:
    con.execute(
        """INSERT INTO equity_curve (run_id, ts, equity, settled_cash, open_exposure, drawdown)
           VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
        [run_id, ts, ledger.equity, ledger.settled_cash, ledger.open_exposure,
         ledger.drawdown],
    )


def _max_drawdown(con, run_id) -> float:
    row = con.execute(
        "SELECT max(drawdown) FROM equity_curve WHERE run_id = ?", [run_id]
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0
