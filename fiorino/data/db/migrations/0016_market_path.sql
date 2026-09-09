-- 0016_market_path — the observed path of a price, and its movements.
--
-- The question this exists for is not "who will win" but "why did the market
-- move 9% in the last three hours". Answering it needs a PATH, not two points,
-- and every view here is restricted to capture_precision = 'TIMESTAMPED'.
--
-- That restriction is the point. A PREMATCH price and a CLOSING price are two
-- observations of unknown instants: differencing them gives a total drift and
-- says nothing about WHEN it happened. Letting them into a movement view would
-- produce a table that looks like a time series and is not one.
--
-- These views are therefore EMPTY today, and correctly so: not one TIMESTAMPED
-- row exists. Emptiness here means "no data", never "no movement" — the same
-- distinction PR #2 drew between DATA_GAP and NO_SIGNAL.

-- Consecutive observations of one price, with the step between them.
CREATE OR REPLACE VIEW v_market_path AS
SELECT
    o.match_id,
    m.competition_id,
    m.kickoff_utc,
    o.bookmaker_id,
    o.market_type,
    o.line,
    o.selection,
    o.captured_at,
    o.price_decimal,
    lag(o.price_decimal) OVER w  AS previous_price,
    lag(o.captured_at)   OVER w  AS previous_at,
    -- Implied probability, raw. De-vigging needs the whole market at the same
    -- instant, which is a stronger requirement than one price, so it is left
    -- to a caller that can establish simultaneity.
    1.0 / o.price_decimal                                  AS implied_prob,
    1.0 / o.price_decimal - 1.0 / lag(o.price_decimal) OVER w
                                                           AS implied_delta,
    date_diff('second', lag(o.captured_at) OVER w, o.captured_at)
                                                           AS seconds_since_previous,
    date_diff('minute', o.captured_at, m.kickoff_utc)      AS minutes_to_kickoff
FROM odds_observations o
JOIN v_analytic_matches m ON m.match_id = o.match_id
WHERE o.capture_precision = 'TIMESTAMPED'
  AND o.captured_at IS NOT NULL
WINDOW w AS (
    PARTITION BY o.match_id, o.bookmaker_id, o.market_type, o.line, o.selection
    ORDER BY o.captured_at
);

-- A movement worth looking at: a step large enough not to be noise.
--
-- The threshold is a parameter of the QUESTION, not a discovery. It is stated
-- here so that "the market moved" always means the same thing, and so that
-- changing it is a visible edit rather than a filter chosen after seeing the
-- results.
CREATE OR REPLACE VIEW v_market_moves AS
SELECT *
FROM v_market_path
WHERE previous_price IS NOT NULL
  AND abs(implied_delta) >= 0.01;      -- one probability point

-- How much a price travelled, and over what window. One row per price series.
CREATE OR REPLACE VIEW v_market_summary AS
SELECT
    match_id,
    competition_id,
    bookmaker_id,
    market_type,
    line,
    selection,
    count(*)                                   AS n_observations,
    min(captured_at)                           AS first_seen,
    max(captured_at)                           AS last_seen,
    date_diff('minute', min(captured_at), max(captured_at)) AS observed_minutes,
    min(minutes_to_kickoff)                    AS closest_to_kickoff,
    arg_min(price_decimal, captured_at)        AS first_price,
    arg_max(price_decimal, captured_at)        AS last_price,
    -- Total drift, and the distance actually travelled. They differ when a
    -- price moves out and comes back: a reversal shows as a large path length
    -- with a small net drift, and averaging only the net would hide it.
    arg_max(implied_prob, captured_at) - arg_min(implied_prob, captured_at)
                                               AS net_implied_drift,
    sum(abs(implied_delta))                    AS total_implied_travel,
    max(abs(implied_delta))                    AS largest_single_move
FROM v_market_path
GROUP BY match_id, competition_id, bookmaker_id, market_type, line, selection;

-- Breadth: one book moving is not the same fact as every book moving.
--
-- The distinction the audit named. A single-book move can be a stale price
-- being corrected; a simultaneous move across books is the market changing its
-- mind, and only the second is information about the fixture.
CREATE OR REPLACE VIEW v_market_breadth AS
SELECT
    match_id,
    market_type,
    line,
    selection,
    date_trunc('minute', captured_at)          AS minute,
    count(DISTINCT bookmaker_id)               AS n_books_moving,
    avg(implied_delta)                         AS mean_delta,
    stddev_samp(implied_delta)                 AS delta_dispersion,
    min(implied_delta)                         AS min_delta,
    max(implied_delta)                         AS max_delta
FROM v_market_path
WHERE previous_price IS NOT NULL AND abs(implied_delta) >= 0.005
GROUP BY match_id, market_type, line, selection, date_trunc('minute', captured_at);

-- What the terminal must show before any movement number: how much of the
-- market is observed at all. A path over two observations is not a path.
CREATE OR REPLACE VIEW v_path_coverage AS
SELECT
    m.competition_id,
    m.season_id,
    count(DISTINCT m.match_id)                                     AS n_matches,
    count(DISTINCT o.match_id) FILTER (WHERE o.capture_precision = 'TIMESTAMPED')
                                                                   AS n_with_path,
    count(*) FILTER (WHERE o.capture_precision = 'TIMESTAMPED')    AS n_timestamped_rows,
    count(*) FILTER (WHERE o.capture_precision <> 'TIMESTAMPED')   AS n_untimestamped_rows
FROM v_analytic_matches m
LEFT JOIN odds_observations o ON o.match_id = m.match_id
GROUP BY m.competition_id, m.season_id;
