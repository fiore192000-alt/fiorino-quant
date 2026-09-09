"""
Which packages may read raw tables, and which must go through the clock.

Until now this was a convention: a list of guarded packages inside one test,
and silence for everything else. Silence is inherited — a new package written
next year picks up no rule at all, and the guard says nothing.

So the taxonomy is declared here, beside the reader it protects, with the
reason for each entry. A package absent from BOTH lists fails the guard: the
default is "you must say which you are", not "you are free".

DECIDERS may not name a raw table. Their output changes what gets bet, so they
read through :class:`PointInTimeView` and nothing else.

PRODUCERS build and measure the warehouse. They necessarily touch raw tables —
an ingester that could only read the past through a clock could not write the
present. They never decide anything.
"""

from __future__ import annotations

__all__ = ["DECIDERS", "PRODUCERS", "RAW_TABLES", "ORACLE_TABLES", "ORACLE_ALLOWED"]

#: Packages whose code influences a betting decision.
DECIDERS = {
    "strategy": "generates candidates; sees only what the clock allows",
    "backtest": "places and settles; the decision instant is its whole subject",
    "portfolio": "allocates across simultaneous bets",
    "staking": "sizes them",
    "pricing": "turns a model into prices a strategy will read",
    "models": "fits and predicts; decides what a model may train on",
    "decision": "classifies a signal for display; must not out-know the clock",
}

#: Packages that build or measure. They read raw tables by necessity.
PRODUCERS = {
    "data": "builds the warehouse; the clock is what it writes, not what it reads",
    "odds": "ingests prices and de-vigs them",
    "clv": "measures settled bets against a close that is, by then, the past",
    "research": "retrospective analysis; produces no bet and no price",
    "core": "pure kernels: identifiers, market vocabulary, Kelly",
    "config": "registries and paths",
    "reporting": "renders what others computed",
    "cli": "argument parsing",
}

#: External history: facts that existed before a run started. A decider that
#: reads one of these unbounded can see the future, so none may be named.
#:
#: The previous version of this list contained "odds_snapshots", a table that
#: does not exist in any migration. It guarded nothing and could not fail —
#: the same defect as a view whose WHERE clause is unreachable.
HISTORY_TABLES = (
    "matches",
    "match_results",
    "odds_observations",
    "odds_closing",
    "fair_probabilities",
    "team_aliases",
    "match_kickoff_revisions",
    # Derived, but guarded for the same reason: a prediction made AFTER the
    # decision instant is as much a view of the future as a result is.
    "predictions",
)

#: The run's own bookkeeping. A backtest writes these and reads them back; the
#: ledger contains only what the run has already done, so reading it cannot
#: reveal anything the run did not itself just decide.
#:
#: Widening the guard made this distinction necessary. Without it the engine
#: reading its own equity curve looks identical to a strategy reading match
#: results, and the two are not remotely the same act.
LEDGER_TABLES = (
    "bets",
    "bet_clv",
    "equity_curve",
    "cohorts",
    "bet_settlements",
    "backtest_runs",
)

#: Reads by a decider that are safe only because the QUERY carries the bound,
#: not because the table does. Each needs a stated reason and each is a debt:
#: the safety lives in SQL a future edit could remove.
#:
#: The test asserts this dict exactly, so a new bypass cannot be added by
#: accident — only by writing the reason down.
BOUNDED_READS = {
    ("backtest", "strategy.py", "odds_observations"): (
        "Strategies filter capture_precision = 'PREMATCH' and take the kickoff "
        "as the decision instant, the convention documented in "
        "docs/architecture/backtest.md. odds_as_of() cannot be used yet: it "
        "reads only TIMESTAMPED rows and there are none. THIS IS A DATED DEBT "
        "— when timestamped odds arrive this becomes a live leak path and must "
        "be routed through odds_as_of(). See PR1_AUDIT S3."
    ),
    ("models", "incremental.py", "match_results"): (
        "build_arms() reads outcomes for the whole history and hands them to "
        "fit_weight(), which applies the boundary (settled_at < boundary) and "
        "records the latest instant it actually consumed. The bound is real and "
        "audited by v_weight_leakage, but it lives one call downstream of the "
        "read — which is precisely why this entry exists rather than silence."
    ),
    ("models", "incremental.py", "fair_probabilities"): (
        "The market arm of the ablation. For the deployable experiment this is "
        "the PREMATCH price, knowable at the decision instant. For the "
        "information experiment it is deliberately the CLOSING price — see "
        "CLOSING_ALLOWED, which is what keeps that from becoming tradeable."
    ),
    ("models", "incremental.py", "predictions"): (
        "Reads out-of-sample forecasts written by EARLIER fits, bounded in the "
        "query by r.trained_through < m.kickoff_utc. Model output, not external "
        "history: a prediction exists only because a fit that respected the "
        "clock produced it."
    ),
}

#: Kept for callers that want everything the guard knows about.
RAW_TABLES = HISTORY_TABLES

#: Tables that hold the CLOSING line. Reading one inside a decider is the
#: clairvoyance the whole system is built to prevent, so they are listed apart
#: and permitted to exactly one place.
ORACLE_TABLES = ("reference_market", "odds_closing")

#: A closing price does not only live in a table called "closing". It is also
#: reachable as fair_probabilities filtered to capture_precision = 'CLOSING',
#: and the table-name check above walks straight past that.
#:
#: This hole was found by widening the guard, not by review. So any decider
#: file mentioning the literal 'CLOSING' must appear here with its reason.
CLOSING_ALLOWED = {
    ("models", "incremental.py"): (
        "The 'information' experiment blends the model with the CLOSING price "
        "to ask whether the model knows anything the close does not. That arm "
        "is SCORED AND NEVER BET: _write_arm() is called only for the "
        "'deployable' experiment, whose market source is PREMATCH. Betting an "
        "arm built from the close would reproduce M4's clairvoyant oracle and "
        "report it as a discovery — see docs/architecture/ensemble.md."
    ),
    ("backtest", "strategy.py"): (
        "TakeValueVsClose, the clairvoyant positive control. Same entry as "
        "ORACLE_ALLOWED, restated here because the two checks catch different "
        "spellings of the same mistake."
    ),
    ("backtest", "settlement.py"): (
        "Settlement vocabulary, not a price: the five settlement states. No "
        "closing price is read."
    ),
}

#: The single sanctioned reader of a closing price, and why.
#:
#: TakeValueVsClose is the positive control: a strategy that deliberately sees
#: the future, used to prove the machinery can detect a real edge when one is
#: planted. It has to read the close. Nothing else may, and until this entry
#: existed nothing said so — a new strategy could have joined reference_market
#: and no test would have objected.
ORACLE_ALLOWED = {("backtest", "strategy.py"): "TakeValueVsClose, the clairvoyant control"}
