-- =====================================================================
-- Fiorino Quant — derived views and point-in-time macros
-- Applied after schema.sql. Safe to drop and recreate at any time.
-- =====================================================================

-- ---------------------------------------------------------------------
-- The reference closing line, de-vigged. Everything CLV joins to this.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_reference_closing AS
SELECT
    c.fixture_id,
    c.market_type,
    c.line,
    c.selection,
    c.price_decimal        AS closing_price,
    c.captured_at          AS closing_captured_at,
    c.seconds_to_kickoff   AS closing_seconds_to_kickoff,
    c.is_trusted,
    f.fair_prob            AS closing_fair_prob,
    f.overround            AS closing_overround,
    f.devig_method
FROM odds_closing c
JOIN bookmakers b
  ON b.bookmaker_id = c.bookmaker_id AND b.is_reference
LEFT JOIN fair_probabilities f
  ON  f.fixture_id   = c.fixture_id
  AND f.bookmaker_id = c.bookmaker_id
  AND f.market_type  = c.market_type
  AND f.line         = c.line
  AND f.selection    = c.selection
  AND f.captured_at  = c.captured_at
  AND f.is_closing;


-- ---------------------------------------------------------------------
-- One row per bet with decision context, settlement and CLV joined.
-- The table every report and tearsheet is built from.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_bet_performance AS
SELECT
    b.bet_id,
    b.run_id,
    r.strategy_id,
    r.mode,
    b.cohort_id,
    b.fixture_id,
    fx.competition_id,
    fx.season,
    fx.kickoff_utc,
    b.bookmaker_id,
    b.market_type,
    b.line,
    b.selection,
    b.price_taken,
    b.stake,
    b.placed_at,
    date_diff('second', b.placed_at, fx.kickoff_utc) AS seconds_before_kickoff,
    b.model_prob,
    b.blended_prob,
    b.shrunk_prob,
    b.fair_prob_at_placement,
    b.edge_ev,
    b.kelly_applied,
    s.outcome,
    s.returned,
    s.commission,
    s.pnl,
    s.settled_at,
    CASE WHEN b.stake > 0 THEN CAST(s.pnl AS DOUBLE) / CAST(b.stake AS DOUBLE) END AS roi_on_stake,
    v.closing_price,
    v.closing_fair_prob,
    v.clv_price,
    v.clv_ev,
    v.clv_log,
    v.beat_close,
    v.line_matched
FROM bets b
JOIN runs r         ON r.run_id = b.run_id
JOIN fixtures fx    ON fx.fixture_id = b.fixture_id
LEFT JOIN bet_settlements s ON s.bet_id = b.bet_id
LEFT JOIN clv v             ON v.bet_id = b.bet_id;


-- ---------------------------------------------------------------------
-- CLV rollup. This is the dashboard that tells you whether the edge is
-- alive, weeks before the P&L has enough sample to say anything.
--
-- Read it as: mean_clv_ev is the expected ROI implied by the closing
-- line. If it is positive and yield is negative, you are unlucky.
-- If it is negative and yield is positive, you are lucky and about to
-- stop being lucky.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_clv_summary AS
SELECT
    run_id,
    strategy_id,
    competition_id,
    market_type,
    count(*)                                        AS n_bets,
    sum(stake)                                      AS turnover,
    sum(pnl)                                        AS pnl,
    CASE WHEN sum(stake) > 0
         THEN CAST(sum(pnl) AS DOUBLE) / CAST(sum(stake) AS DOUBLE) END AS yield_on_turnover,
    avg(clv_ev)                                     AS mean_clv_ev,
    -- Stake-weighted, because a big bet with poor CLV matters more.
    CASE WHEN sum(stake) > 0
         THEN sum(clv_ev * CAST(stake AS DOUBLE)) / CAST(sum(stake) AS DOUBLE) END AS weighted_clv_ev,
    avg(clv_log)                                    AS mean_clv_log,
    avg(CASE WHEN beat_close THEN 1.0 ELSE 0.0 END) AS beat_close_rate,
    stddev_samp(clv_ev)                             AS clv_ev_stddev,
    -- t-stat of mean CLV against zero. |t| > 2 over a few hundred bets is
    -- real signal; yield needs thousands of bets to say as much.
    CASE WHEN stddev_samp(clv_ev) > 0 AND count(*) > 1
         THEN avg(clv_ev) / (stddev_samp(clv_ev) / sqrt(count(*))) END AS clv_t_stat,
    avg(CASE WHEN line_matched THEN 1.0 ELSE 0.0 END) AS line_match_rate
FROM v_bet_performance
WHERE clv_ev IS NOT NULL
GROUP BY run_id, strategy_id, competition_id, market_type;


-- ---------------------------------------------------------------------
-- Line movement per market: opening, closing, and how far it travelled.
-- Used to detect stale-price opportunities and to sanity-check ingest
-- coverage (a market with 2 snapshots is not a line history).
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_line_history AS
SELECT
    fixture_id,
    bookmaker_id,
    market_type,
    line,
    selection,
    count(*)                            AS n_snapshots,
    min(captured_at)                    AS first_seen,
    max(captured_at)                    AS last_seen,
    arg_min(price_decimal, captured_at) AS opening_price,
    arg_max(price_decimal, captured_at) AS closing_price,
    arg_max(price_decimal, captured_at) / arg_min(price_decimal, captured_at) - 1 AS drift,
    min(price_decimal)                  AS min_price,
    max(price_decimal)                  AS max_price
FROM odds_snapshots
WHERE seconds_to_kickoff > 0
GROUP BY fixture_id, bookmaker_id, market_type, line, selection;


-- ---------------------------------------------------------------------
-- Ingest health. Run this before trusting any backtest: a period with
-- thin odds coverage produces a backtest that only saw the easy fixtures.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_data_coverage AS
SELECT
    fx.competition_id,
    fx.season,
    count(DISTINCT fx.fixture_id)                                     AS n_fixtures,
    count(DISTINCT res.fixture_id)                                    AS n_with_result,
    count(DISTINCT o.fixture_id)                                      AS n_with_any_odds,
    count(DISTINCT cl.fixture_id)                                     AS n_with_ref_close,
    CAST(count(DISTINCT cl.fixture_id) AS DOUBLE)
        / nullif(count(DISTINCT fx.fixture_id), 0)                    AS ref_close_coverage,
    median(snap.n_snapshots)                                          AS median_snapshots_per_fixture
FROM fixtures fx
LEFT JOIN results res ON res.fixture_id = fx.fixture_id
LEFT JOIN odds_snapshots o ON o.fixture_id = fx.fixture_id
LEFT JOIN v_reference_closing cl ON cl.fixture_id = fx.fixture_id
LEFT JOIN (
    SELECT fixture_id, count(*) AS n_snapshots
    FROM odds_snapshots GROUP BY fixture_id
) snap ON snap.fixture_id = fx.fixture_id
GROUP BY fx.competition_id, fx.season;


-- ---------------------------------------------------------------------
-- POINT-IN-TIME MACROS (rule R1)
--
-- These are the ONLY sanctioned way for a backtest to read odds. A query
-- that touches odds_snapshots directly inside strategy code is a bug:
-- it can see the future. fiorino.data.access wraps these, and a test
-- asserts that no module under fiorino/strategy or fiorino/backtest
-- references the raw tables.
-- ---------------------------------------------------------------------

-- Latest price per selection as known at `as_of`, across all books.
CREATE OR REPLACE MACRO odds_as_of(at_ts) AS TABLE
SELECT
    fixture_id, bookmaker_id, market_type, line, selection,
    arg_max(price_decimal, captured_at)  AS price_decimal,
    arg_max(available_size, captured_at) AS available_size,
    max(captured_at)                     AS captured_at
FROM odds_snapshots
WHERE captured_at <= at_ts
GROUP BY fixture_id, bookmaker_id, market_type, line, selection;

-- Best available price per selection at `as_of`, with the book offering it.
-- Optionally restricted to books you actually hold an account with.
CREATE OR REPLACE MACRO best_price_as_of(at_ts) AS TABLE
SELECT
    fixture_id, market_type, line, selection,
    arg_max(bookmaker_id, price_decimal) AS bookmaker_id,
    max(price_decimal)                   AS price_decimal,
    count(*)                             AS n_books
FROM odds_as_of(at_ts)
GROUP BY fixture_id, market_type, line, selection;

-- Fixtures that are legitimately bettable at `as_of`: not yet kicked off,
-- and not already resolved in the data.
CREATE OR REPLACE MACRO bettable_fixtures_as_of(at_ts) AS TABLE
SELECT fx.*
FROM fixtures fx
WHERE fx.kickoff_utc > at_ts
  AND fx.status = 'SCHEDULED';

-- Results knowable at `as_of` — the only rows a model may train on.
CREATE OR REPLACE MACRO results_as_of(at_ts) AS TABLE
SELECT r.*, fx.competition_id, fx.season, fx.kickoff_utc,
       fx.home_team_id, fx.away_team_id, fx.neutral_venue
FROM results r
JOIN fixtures fx ON fx.fixture_id = r.fixture_id
WHERE r.settled_at <= at_ts;

-- Most recent feature value per (entity, feature) knowable at `as_of`.
CREATE OR REPLACE MACRO features_as_of(at_ts) AS TABLE
SELECT entity_type, entity_id, feature_name,
       arg_max(value, as_of) AS value,
       max(as_of)            AS as_of
FROM feature_values
WHERE feature_values.as_of <= at_ts
GROUP BY entity_type, entity_id, feature_name;
