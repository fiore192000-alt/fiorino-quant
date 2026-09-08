-- 0008_clv — Closing Line Value (M3).
--
-- The primary edge signal. CLV converges on the truth in hundreds of bets;
-- P&L needs thousands. A strategy with negative CLV and positive P&L is lucky,
-- and knowing that early is worth more than the P&L.
--
-- M3 measures. It does not size, select or settle: no staking, no strategy,
-- no bankroll. Those are M4 and M7.

-- A recorded bet. In M3 this is a MEASUREMENT LEDGER, not a betting engine:
-- rows are placed here to be scored against the close, and `stake` is
-- deliberately absent because sizing is not this milestone's business.
CREATE TABLE bets (
    bet_id           VARCHAR PRIMARY KEY,
    run_id           VARCHAR NOT NULL,
    match_id         VARCHAR NOT NULL REFERENCES matches(match_id),
    bookmaker_id     VARCHAR NOT NULL REFERENCES bookmakers(bookmaker_id),
    market_type      VARCHAR NOT NULL,
    line             DOUBLE  NOT NULL DEFAULT 0.0,
    selection        VARCHAR NOT NULL,
    price_taken      DOUBLE  NOT NULL,

    -- The same honesty as M2. A bet struck at a PREMATCH price inherits that
    -- price's ignorance: we know it was available before kickoff and no more.
    -- Claiming an instant would be a fabrication, so placed_at is NULL there.
    price_precision  VARCHAR NOT NULL,
    placed_at        TIMESTAMPTZ,
    observed_before  TIMESTAMPTZ,

    model_prob       DOUBLE,          -- NULL in M3: there is no model yet
    note             VARCHAR,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CHECK (price_taken > 1.0),
    CHECK (price_precision IN ('TIMESTAMPED', 'OPENING', 'PREMATCH', 'CLOSING')),
    CHECK ((price_precision = 'TIMESTAMPED') = (placed_at IS NOT NULL))
);

-- One row per scored bet.
CREATE TABLE bet_clv (
    bet_id            VARCHAR PRIMARY KEY REFERENCES bets(bet_id),
    ref_bookmaker_id  VARCHAR NOT NULL REFERENCES bookmakers(bookmaker_id),
    closing_price     DOUBLE,
    closing_fair_prob DOUBLE,
    closing_basis     VARCHAR,

    -- price_taken / closing_price - 1. Ignores the overround, so it flatters a
    -- bet struck into a wide market. Report it; do not decide on it.
    clv_price         DOUBLE,
    -- closing_fair_prob * price_taken - 1. THE headline: expected ROI if the
    -- de-vigged close is the truth, on the same scale as yield, so "+2% CLV,
    -- -1% yield" is a legible statement about luck.
    clv_ev            DOUBLE,
    -- ln(closing_fair_prob * price_taken). Additive across bets, so a sequence
    -- aggregates without the upward bias the mean of ratios carries.
    clv_log           DOUBLE,
    beat_close        BOOLEAN,

    -- FALSE when the reference book never offered this exact (market, line,
    -- selection). Such bets are EXCLUDED from the statistics rather than
    -- compared against a different line, which would be a silent error.
    line_matched      BOOLEAN NOT NULL,
    exclusion_reason  VARCHAR,
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_bets_run   ON bets (run_id);
CREATE INDEX idx_bets_match ON bets (match_id);
