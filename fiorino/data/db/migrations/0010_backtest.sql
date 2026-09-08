-- 0010_backtest — walk-forward simulation (M4).
--
-- The bias this exists to eliminate, measured on the previous engine: three
-- matches kicking off at 15:00, each sized at 50% of "current" bankroll,
-- settled sequentially so every stake compounds on results not yet knowable.
--
--     WRONG      100 -> 50 -> 75 -> 112.50
--     REQUIRED   every stake sized against ONE equity snapshot -> 50, 50, 50
--
-- A cohort is that snapshot made explicit.

CREATE TABLE backtest_runs (
    run_id           VARCHAR PRIMARY KEY,
    strategy         VARCHAR NOT NULL,
    mode             VARCHAR NOT NULL DEFAULT 'BACKTEST',
    start_utc        TIMESTAMPTZ NOT NULL,
    end_utc          TIMESTAMPTZ NOT NULL,
    initial_bankroll DECIMAL(18,6) NOT NULL,
    config           JSON,
    code_version     VARCHAR,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (mode IN ('BACKTEST', 'PAPER', 'LIVE')),
    CHECK (initial_bankroll > 0)
);

-- The set of bets decided together and sized against one equity snapshot.
CREATE TABLE cohorts (
    cohort_id      VARCHAR PRIMARY KEY,
    run_id         VARCHAR NOT NULL REFERENCES backtest_runs(run_id),
    decision_utc   TIMESTAMPTZ NOT NULL,   -- when stakes were computed
    settlement_utc TIMESTAMPTZ NOT NULL,   -- when the last member resolves
    -- equity = settled cash + open stakes at cost. Kelly sizes against this.
    equity_open    DECIMAL(18,6) NOT NULL,
    -- Capital committed to earlier kickoffs and not yet returned.
    open_exposure  DECIMAL(18,6) NOT NULL,
    -- What may actually be staked now: equity * max_exposure - open_exposure.
    available_open DECIMAL(18,6) NOT NULL,
    equity_close   DECIMAL(18,6),
    n_candidates   INTEGER NOT NULL DEFAULT 0,
    n_bets         INTEGER NOT NULL DEFAULT 0,
    total_staked   DECIMAL(18,6) NOT NULL DEFAULT 0,
    constrained_by VARCHAR,                -- the oversize policy, when it bit
    CHECK (settlement_utc >= decision_utc)
);

-- Five settlement states, not two. An Asian handicap is impossible to settle
-- correctly with a boolean.
CREATE TABLE bet_settlements (
    bet_id     VARCHAR PRIMARY KEY REFERENCES bets(bet_id),
    outcome    VARCHAR NOT NULL,
    -- Gross return including stake:
    --   WIN stake*price | HALF_WIN stake*(1+(price-1)/2) | PUSH stake
    --   HALF_LOSE stake*0.5 | LOSE 0 | VOID stake
    returned   DECIMAL(18,6) NOT NULL,
    commission DECIMAL(18,6) NOT NULL DEFAULT 0,
    pnl        DECIMAL(18,6) NOT NULL,     -- returned - stake - commission
    settled_at TIMESTAMPTZ NOT NULL,
    CHECK (outcome IN ('WIN', 'HALF_WIN', 'PUSH', 'HALF_LOSE', 'LOSE', 'VOID')),
    CHECK (returned >= 0)
);

CREATE TABLE equity_curve (
    run_id        VARCHAR NOT NULL REFERENCES backtest_runs(run_id),
    ts            TIMESTAMPTZ NOT NULL,
    equity        DECIMAL(18,6) NOT NULL,
    settled_cash  DECIMAL(18,6) NOT NULL,
    open_exposure DECIMAL(18,6) NOT NULL,
    drawdown      DOUBLE NOT NULL,          -- fraction below the running peak
    PRIMARY KEY (run_id, ts)
);

-- M3 left `bets` as a measurement ledger with no stake, because sizing was not
-- its business. M4 adds the sizing. NULL stake still means "recorded to be
-- measured, never staked", which is exactly what the replay instruments are.
ALTER TABLE bets ADD COLUMN cohort_id VARCHAR;
ALTER TABLE bets ADD COLUMN stake DECIMAL(18,6);

CREATE INDEX idx_cohorts_run ON cohorts (run_id, decision_utc);
