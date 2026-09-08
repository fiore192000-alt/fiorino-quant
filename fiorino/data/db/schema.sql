-- =====================================================================
-- Fiorino Quant — DuckDB schema
-- =====================================================================
-- Design rules (violate these and the backtest silently lies to you):
--
--  R1. POINT-IN-TIME. Every fact that the system can *learn over time*
--      carries the instant it became knowable: odds -> captured_at,
--      results -> settled_at, features -> as_of, models -> trained_through.
--      No query in a backtest may read a row whose knowable-instant is
--      greater than the current simulation clock.
--
--  R2. ONE ODDS SHAPE. Every market in every book is (market_type, line,
--      selection). No per-market tables, no wide columns. This is what
--      makes cross-book best-price and CLV joins trivial.
--
--  R3. HOME-PERSPECTIVE LINES. Asian handicap lines are ALWAYS stored
--      from the home team's point of view. "Away +0.5" is stored as
--      (ASIAN_HANDICAP, line = -0.5, selection = 'AWAY'). Without this
--      normalisation the same price appears under two keys and best-price
--      comparison breaks.
--
--  R4. LINE IS NOT NULL. Markets without a line use 0.0. NULLs compare
--      as distinct in UNIQUE constraints, which would silently permit
--      duplicate 1X2 snapshots.
--
--  R5. IMMUTABLE LEDGER. bets / bet_settlements are append-only. Any
--      correction is a new row, never an UPDATE.
-- =====================================================================


-- ---------------------------------------------------------------------
-- 0. Enumerations
-- ---------------------------------------------------------------------
CREATE TYPE market_t AS ENUM (
    'ONE_X_TWO',
    'ASIAN_HANDICAP',
    'TOTALS',
    'TEAM_TOTALS',
    'BTTS',
    'DOUBLE_CHANCE',
    'DRAW_NO_BET',
    'CORRECT_SCORE'
);

CREATE TYPE book_kind_t AS ENUM ('SHARP', 'SOFT', 'EXCHANGE', 'AGGREGATOR');

CREATE TYPE fixture_status_t AS ENUM (
    'SCHEDULED', 'LIVE', 'FINISHED', 'POSTPONED', 'ABANDONED', 'CANCELLED'
);

CREATE TYPE devig_t AS ENUM (
    'MULTIPLICATIVE', 'ADDITIVE', 'POWER', 'SHIN',
    'ODDS_RATIO', 'LOGARITHMIC', 'DIFFERENTIAL_MARGIN'
);

CREATE TYPE bet_status_t AS ENUM ('PENDING', 'SETTLED', 'VOID', 'REJECTED');

-- Asian handicap and integer totals need five settlement states, not two.
CREATE TYPE settle_t AS ENUM ('WIN', 'HALF_WIN', 'PUSH', 'HALF_LOSE', 'LOSE', 'VOID');

CREATE TYPE run_mode_t AS ENUM ('BACKTEST', 'PAPER', 'LIVE');


-- ---------------------------------------------------------------------
-- 1. Reference dimensions
-- ---------------------------------------------------------------------
CREATE TABLE competitions (
    competition_id  VARCHAR PRIMARY KEY,          -- 'ENG_PL', 'ITA_SA'
    name            VARCHAR NOT NULL,
    country         VARCHAR NOT NULL,
    tier            SMALLINT,
    is_cup          BOOLEAN NOT NULL DEFAULT FALSE,
    uefa_coefficient DOUBLE,                      -- cross-league prior anchor
    source_slugs    JSON                          -- {"footballdata":"E0", ...}
);

CREATE TABLE teams (
    team_id         VARCHAR PRIMARY KEY,          -- stable surrogate, never a name
    canonical_name  VARCHAR NOT NULL,
    country         VARCHAR,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Identity resolution. Every external name a source has ever emitted maps
-- here. Unverified rows are fuzzy-matcher proposals awaiting review.
CREATE TABLE team_aliases (
    alias           VARCHAR NOT NULL,
    source          VARCHAR NOT NULL,             -- 'pinnacle', 'footballdata', ...
    team_id         VARCHAR NOT NULL REFERENCES teams(team_id),
    confidence      DOUBLE  NOT NULL DEFAULT 1.0,
    verified        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (alias, source)
);

CREATE TABLE bookmakers (
    bookmaker_id      VARCHAR PRIMARY KEY,
    name              VARCHAR NOT NULL,
    kind              book_kind_t NOT NULL,
    -- Exactly one book should carry is_reference = TRUE. It defines the
    -- closing line against which ALL CLV is measured. Changing it
    -- invalidates every historical CLV number, so treat it as a constant.
    is_reference      BOOLEAN NOT NULL DEFAULT FALSE,
    commission_rate   DOUBLE  NOT NULL DEFAULT 0.0,   -- exchanges only
    typical_max_stake DECIMAL(18,2),
    country           VARCHAR
);

-- Valid (market, selection) vocabulary. CORRECT_SCORE selections are
-- free-form ('2-1'), so they are validated by pattern, not by this table.
CREATE TABLE market_selections (
    market_type   market_t NOT NULL,
    selection     VARCHAR  NOT NULL,
    requires_line BOOLEAN  NOT NULL,
    n_selections  SMALLINT NOT NULL,   -- size of the complete market, for de-vig
    description   VARCHAR,
    PRIMARY KEY (market_type, selection)
);


-- ---------------------------------------------------------------------
-- 2. Fixtures and results
-- ---------------------------------------------------------------------
-- fixture_id is a deterministic hash of
--   (competition_id, season, utc_date, home_team_id, away_team_id)
-- so that re-ingesting the same fixture from any source is idempotent.
CREATE TABLE fixtures (
    fixture_id     VARCHAR PRIMARY KEY,
    competition_id VARCHAR NOT NULL REFERENCES competitions(competition_id),
    season         VARCHAR NOT NULL,              -- '2024-2025'
    kickoff_utc    TIMESTAMPTZ NOT NULL,
    home_team_id   VARCHAR NOT NULL REFERENCES teams(team_id),
    away_team_id   VARCHAR NOT NULL REFERENCES teams(team_id),
    neutral_venue  BOOLEAN NOT NULL DEFAULT FALSE,
    status         fixture_status_t NOT NULL DEFAULT 'SCHEDULED',
    ingested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (home_team_id <> away_team_id)
);

CREATE TABLE results (
    fixture_id     VARCHAR PRIMARY KEY REFERENCES fixtures(fixture_id),
    goals_home     SMALLINT NOT NULL,
    goals_away     SMALLINT NOT NULL,
    goals_home_ht  SMALLINT,
    goals_away_ht  SMALLINT,
    -- R1: when the result became knowable. Settlement and any feature
    -- derived from this match must not be visible before this instant.
    settled_at     TIMESTAMPTZ NOT NULL,
    source         VARCHAR NOT NULL,
    ingested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (goals_home >= 0 AND goals_away >= 0)
);


-- ---------------------------------------------------------------------
-- 3. Odds — the line history
-- ---------------------------------------------------------------------
-- The highest-cardinality table in the system: one row per
-- (fixture, book, market, line, selection, poll). Millions of rows per
-- season. Everything else about pricing is derived from it.
CREATE SEQUENCE seq_odds_snapshot START 1;

CREATE TABLE odds_snapshots (
    snapshot_id        BIGINT PRIMARY KEY DEFAULT nextval('seq_odds_snapshot'),
    fixture_id         VARCHAR NOT NULL REFERENCES fixtures(fixture_id),
    bookmaker_id       VARCHAR NOT NULL REFERENCES bookmakers(bookmaker_id),
    market_type        market_t NOT NULL,
    line               DOUBLE  NOT NULL DEFAULT 0.0,   -- R3/R4
    selection          VARCHAR NOT NULL,
    price_decimal      DOUBLE  NOT NULL,
    available_size     DECIMAL(18,2),                  -- exchange depth
    captured_at        TIMESTAMPTZ NOT NULL,           -- R1
    seconds_to_kickoff BIGINT  NOT NULL,               -- negative = in-play
    source             VARCHAR NOT NULL,
    ingested_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Groups the selections that together form one complete market, which
    -- is the unit of overround removal.
    market_key         VARCHAR GENERATED ALWAYS AS (
                           md5(fixture_id || '|' || bookmaker_id || '|' ||
                               CAST(market_type AS VARCHAR) || '|' ||
                               CAST(line AS VARCHAR))
                       ) VIRTUAL,
    CHECK (price_decimal > 1.0),
    UNIQUE (fixture_id, bookmaker_id, market_type, line, selection, captured_at)
);

-- Materialised from odds_snapshots: the last snapshot strictly before
-- kickoff for each (fixture, book, market, line, selection).
-- Rebuilt by fiorino.odds.closing after every ingest cycle.
CREATE TABLE odds_closing (
    fixture_id         VARCHAR NOT NULL REFERENCES fixtures(fixture_id),
    bookmaker_id       VARCHAR NOT NULL REFERENCES bookmakers(bookmaker_id),
    market_type        market_t NOT NULL,
    line               DOUBLE  NOT NULL DEFAULT 0.0,
    selection          VARCHAR NOT NULL,
    price_decimal      DOUBLE  NOT NULL,
    captured_at        TIMESTAMPTZ NOT NULL,
    seconds_to_kickoff BIGINT  NOT NULL,
    snapshot_id        BIGINT  NOT NULL,
    -- Quality gate: a "closing" price captured 6 hours out is not a close.
    -- fiorino.clv refuses to score CLV when this exceeds the configured
    -- staleness threshold.
    is_trusted         BOOLEAN NOT NULL DEFAULT TRUE,
    materialized_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (fixture_id, bookmaker_id, market_type, line, selection)
);

-- Overround-free probabilities. Computed per complete market, per capture
-- instant. Multiple methods may coexist for the same key so that the
-- de-vig choice can be A/B tested without re-ingesting.
CREATE TABLE fair_probabilities (
    fixture_id        VARCHAR NOT NULL REFERENCES fixtures(fixture_id),
    bookmaker_id      VARCHAR NOT NULL REFERENCES bookmakers(bookmaker_id),
    market_type       market_t NOT NULL,
    line              DOUBLE  NOT NULL DEFAULT 0.0,
    selection         VARCHAR NOT NULL,
    captured_at       TIMESTAMPTZ NOT NULL,
    devig_method      devig_t NOT NULL,
    fair_prob         DOUBLE  NOT NULL,
    raw_implied_prob  DOUBLE  NOT NULL,             -- 1 / price
    overround         DOUBLE  NOT NULL,             -- sum(raw) - 1
    n_selections      SMALLINT NOT NULL,
    is_closing        BOOLEAN NOT NULL DEFAULT FALSE,
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (fixture_id, bookmaker_id, market_type, line,
                 selection, captured_at, devig_method),
    CHECK (fair_prob > 0.0 AND fair_prob < 1.0)
);


-- ---------------------------------------------------------------------
-- 4. Features (point-in-time)
-- ---------------------------------------------------------------------
-- Narrow by design: features are added and retired constantly, and a wide
-- table would need a migration each time. as_of is the instant the value
-- became computable from already-settled information.
CREATE TABLE feature_values (
    entity_type  VARCHAR NOT NULL,     -- 'TEAM' | 'FIXTURE'
    entity_id    VARCHAR NOT NULL,
    feature_set  VARCHAR NOT NULL,     -- 'form_v1', 'xg_rolling_v2'
    feature_name VARCHAR NOT NULL,
    as_of        TIMESTAMPTZ NOT NULL, -- R1
    value        DOUBLE,
    computed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (entity_type, entity_id, feature_name, as_of)
);


-- ---------------------------------------------------------------------
-- 5. Models and predictions
-- ---------------------------------------------------------------------
CREATE TABLE model_runs (
    model_run_id    VARCHAR PRIMARY KEY,
    model_name      VARCHAR NOT NULL,          -- 'dixon_coles', 'blend_v2'
    model_version   VARCHAR NOT NULL,
    competition_id  VARCHAR REFERENCES competitions(competition_id),
    -- R1: the walk-forward boundary. No training row may have
    -- settled_at > trained_through - embargo_seconds.
    trained_through TIMESTAMPTZ NOT NULL,
    embargo_seconds BIGINT NOT NULL DEFAULT 0,
    n_matches       INTEGER,
    params          JSON,
    fitted_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Model output already projected onto the market vocabulary, so that a
-- prediction joins to odds on (market_type, line, selection) with no
-- translation layer.
--
-- FIVE probabilities, not one. A quarter line (-0.25, +0.75, ...) settles as
-- half-win or half-lose, and an integer line pushes. Collapsing this to a
-- single prob_win is not a simplification, it is a pricing error:
--
--   p_win=0.42, p_push=0.08, p_lose=0.50 at price 2.60
--     EV correct  = p_win*price + p_push - 1        = +17.2%
--     EV collapsed= p_win*(price-1) - (1 - p_win)   =  +9.2%
--
--   understated by exactly p_push. Under a 10% edge threshold the bet is
--   rejected. See fiorino/core/markets.py for the settlement algebra.
CREATE TABLE predictions (
    model_run_id    VARCHAR NOT NULL REFERENCES model_runs(model_run_id),
    fixture_id      VARCHAR NOT NULL REFERENCES fixtures(fixture_id),
    market_type     market_t NOT NULL,
    line            DOUBLE  NOT NULL DEFAULT 0.0,
    selection       VARCHAR NOT NULL,
    as_of           TIMESTAMPTZ NOT NULL,
    prob_win        DOUBLE  NOT NULL,
    prob_half_win   DOUBLE  NOT NULL DEFAULT 0.0,   -- quarter lines only
    prob_push       DOUBLE  NOT NULL DEFAULT 0.0,   -- integer lines only
    prob_half_lose  DOUBLE  NOT NULL DEFAULT 0.0,   -- quarter lines only
    prob_lose       DOUBLE  NOT NULL,
    lambda_home     DOUBLE,
    lambda_away     DOUBLE,
    PRIMARY KEY (model_run_id, fixture_id, market_type, line, selection),
    CHECK (abs(prob_win + prob_half_win + prob_push
               + prob_half_lose + prob_lose - 1.0) < 1e-6)
);


-- ---------------------------------------------------------------------
-- 6. Strategies, runs, cohorts
-- ---------------------------------------------------------------------
CREATE TABLE strategies (
    strategy_id VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL,
    description VARCHAR,
    config      JSON
);

CREATE TABLE runs (
    run_id           VARCHAR PRIMARY KEY,
    strategy_id      VARCHAR NOT NULL REFERENCES strategies(strategy_id),
    mode             run_mode_t NOT NULL,
    start_utc        TIMESTAMPTZ NOT NULL,
    end_utc          TIMESTAMPTZ NOT NULL,
    initial_bankroll DECIMAL(18,6) NOT NULL,
    config           JSON,
    code_version     VARCHAR,           -- git sha; runs are not comparable across shas
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A cohort is the set of bets sized against one common bankroll snapshot.
-- This is the fix for the sequential-settlement bias: three 15:00 kickoffs
-- form ONE cohort and are all sized against the equity available at the
-- decision instant, not against each other's results.
CREATE TABLE cohorts (
    cohort_id      VARCHAR PRIMARY KEY,
    run_id         VARCHAR NOT NULL REFERENCES runs(run_id),
    decision_utc   TIMESTAMPTZ NOT NULL,   -- when stakes were computed
    settlement_utc TIMESTAMPTZ NOT NULL,   -- when the last member resolves
    equity_open    DECIMAL(18,6) NOT NULL, -- settled cash + open stakes at cost
    open_exposure  DECIMAL(18,6) NOT NULL, -- stakes still unresolved
    available_open DECIMAL(18,6) NOT NULL, -- what can actually be staked now
    equity_close   DECIMAL(18,6),
    n_candidates   INTEGER NOT NULL DEFAULT 0,
    n_bets         INTEGER NOT NULL DEFAULT 0,
    total_staked   DECIMAL(18,6) NOT NULL DEFAULT 0
);


-- ---------------------------------------------------------------------
-- 7. Bets, settlement, CLV
-- ---------------------------------------------------------------------
-- R5: append-only.
CREATE TABLE bets (
    bet_id                 VARCHAR PRIMARY KEY,
    run_id                 VARCHAR NOT NULL REFERENCES runs(run_id),
    cohort_id              VARCHAR REFERENCES cohorts(cohort_id),
    fixture_id             VARCHAR NOT NULL REFERENCES fixtures(fixture_id),
    bookmaker_id           VARCHAR NOT NULL REFERENCES bookmakers(bookmaker_id),
    market_type            market_t NOT NULL,
    line                   DOUBLE  NOT NULL DEFAULT 0.0,
    selection              VARCHAR NOT NULL,
    price_taken            DOUBLE  NOT NULL,
    stake                  DECIMAL(18,6) NOT NULL,
    placed_at              TIMESTAMPTZ NOT NULL,
    -- The full decision context, frozen. Without these columns a losing
    -- run cannot be diagnosed after the fact.
    model_run_id           VARCHAR REFERENCES model_runs(model_run_id),
    model_prob             DOUBLE,   -- raw model
    blended_prob           DOUBLE,   -- after market blending + calibration
    shrunk_prob            DOUBLE,   -- after estimation-uncertainty shrinkage
    fair_prob_at_placement DOUBLE,   -- reference book, de-vigged, at placed_at
    edge_ev                DOUBLE,   -- shrunk_prob * price_taken - 1
    kelly_full             DOUBLE,   -- unconstrained Kelly fraction
    kelly_applied          DOUBLE,   -- after fraction + caps + allocator
    status                 bet_status_t NOT NULL DEFAULT 'PENDING',
    CHECK (price_taken > 1.0),
    CHECK (stake >= 0)
);

CREATE TABLE bet_settlements (
    bet_id     VARCHAR PRIMARY KEY REFERENCES bets(bet_id),
    outcome    settle_t NOT NULL,
    -- returned = gross return including stake:
    --   WIN stake*price | HALF_WIN stake*(1+(price-1)/2) | PUSH stake
    --   HALF_LOSE stake*0.5 | LOSE 0 | VOID stake
    returned   DECIMAL(18,6) NOT NULL,
    commission DECIMAL(18,6) NOT NULL DEFAULT 0,
    pnl        DECIMAL(18,6) NOT NULL,   -- returned - stake - commission
    settled_at TIMESTAMPTZ NOT NULL
);

-- The primary edge signal. Measured against the REFERENCE book's closing
-- line for the identical (market_type, line, selection) — never against
-- the book the bet was struck with.
CREATE TABLE clv (
    bet_id            VARCHAR PRIMARY KEY REFERENCES bets(bet_id),
    ref_bookmaker_id  VARCHAR NOT NULL REFERENCES bookmakers(bookmaker_id),
    closing_price     DOUBLE,
    closing_fair_prob DOUBLE,   -- de-vigged reference close
    -- clv_price: pure price improvement, price_taken / closing_price - 1
    clv_price         DOUBLE,
    -- clv_ev: expected ROI if the closing fair prob is truth,
    --         closing_fair_prob * price_taken - 1.  THE headline number.
    clv_ev            DOUBLE,
    -- clv_log: ln(closing_fair_prob * price_taken). Additive across bets,
    --          so it aggregates without the arithmetic-mean bias.
    clv_log           DOUBLE,
    beat_close        BOOLEAN,
    -- FALSE when the reference book never offered this exact line and the
    -- comparison had to be interpolated (or was skipped entirely).
    line_matched      BOOLEAN NOT NULL,
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE equity_curve (
    run_id        VARCHAR NOT NULL REFERENCES runs(run_id),
    ts            TIMESTAMPTZ NOT NULL,
    equity        DECIMAL(18,6) NOT NULL,
    settled_cash  DECIMAL(18,6) NOT NULL,
    open_exposure DECIMAL(18,6) NOT NULL,
    drawdown      DOUBLE NOT NULL,          -- fraction from running peak
    PRIMARY KEY (run_id, ts)
);


-- ---------------------------------------------------------------------
-- 8. Indexes
-- ---------------------------------------------------------------------
CREATE INDEX idx_fixtures_kickoff    ON fixtures (kickoff_utc);
CREATE INDEX idx_fixtures_comp       ON fixtures (competition_id, season);
CREATE INDEX idx_snap_fixture        ON odds_snapshots (fixture_id);
CREATE INDEX idx_snap_captured       ON odds_snapshots (captured_at);
CREATE INDEX idx_snap_market         ON odds_snapshots (fixture_id, market_type, line);
CREATE INDEX idx_fair_fixture        ON fair_probabilities (fixture_id, market_type, line);
CREATE INDEX idx_feat_lookup         ON feature_values (entity_id, feature_name, as_of);
CREATE INDEX idx_bets_run            ON bets (run_id);
CREATE INDEX idx_bets_fixture        ON bets (fixture_id);
CREATE INDEX idx_pred_fixture        ON predictions (fixture_id);
