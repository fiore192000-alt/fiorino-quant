-- 0007_odds_views — the reference market, and the point-in-time odds reader.

-- The de-vigged closing line of the reference book. This is the denominator
-- of every CLV number M3 will compute, so it is defined once, here.
CREATE OR REPLACE VIEW reference_market AS
SELECT
    c.match_id,
    c.market_type,
    c.line,
    c.selection,
    c.price_decimal      AS closing_price,
    c.closing_basis,
    c.seconds_to_kickoff,
    c.is_trusted,
    f.fair_prob          AS closing_fair_prob,
    f.overround          AS closing_overround,
    f.devig_method,
    b.bookmaker_id       AS reference_bookmaker_id
FROM odds_closing c
JOIN bookmakers b
  ON b.bookmaker_id = c.bookmaker_id AND b.is_reference
LEFT JOIN fair_probabilities f
  ON  f.match_id     = c.match_id
  AND f.bookmaker_id = c.bookmaker_id
  AND f.market_type  = c.market_type
  AND f.line         = c.line
  AND f.selection    = c.selection
  AND f.capture_precision = 'CLOSING';

-- Line movement between the two points a free source gives us. Not a curve:
-- with Football-Data there are two observations, so this is drift, not a path.
CREATE OR REPLACE VIEW v_line_movement AS
SELECT
    o.match_id,
    o.bookmaker_id,
    o.market_type,
    o.line,
    o.selection,
    max(o.price_decimal) FILTER (WHERE o.capture_precision IN ('OPENING', 'PREMATCH'))
        AS opening_price,
    max(o.price_decimal) FILTER (WHERE o.capture_precision = 'CLOSING')
        AS closing_price,
    max(o.price_decimal) FILTER (WHERE o.capture_precision = 'CLOSING')
        / nullif(max(o.price_decimal) FILTER (WHERE o.capture_precision IN ('OPENING', 'PREMATCH')), 0)
        - 1 AS drift,
    count(*) AS n_observations
FROM odds_observations o
GROUP BY o.match_id, o.bookmaker_id, o.market_type, o.line, o.selection;

-- Market coverage. Read before trusting any CLV: a period with thin closing
-- coverage yields a CLV computed over whichever matches happened to have a
-- close, which is not a random sample.
CREATE OR REPLACE VIEW v_odds_coverage AS
SELECT
    m.competition_id,
    m.season_id,
    count(DISTINCT m.match_id)                        AS n_matches,
    count(DISTINCT o.match_id)                        AS n_with_any_odds,
    count(DISTINCT r.match_id)                        AS n_with_reference_close,
    CAST(count(DISTINCT r.match_id) AS DOUBLE)
        / nullif(count(DISTINCT m.match_id), 0)       AS reference_close_coverage,
    count(DISTINCT o.bookmaker_id)                    AS n_bookmakers
FROM v_analytic_matches m
LEFT JOIN odds_observations o ON o.match_id = m.match_id
LEFT JOIN reference_market  r ON r.match_id = m.match_id
GROUP BY m.competition_id, m.season_id;

-- POINT-IN-TIME odds reader (rule R1).
--
-- ONLY TIMESTAMPED observations are visible. A PREMATCH price has no clock, so
-- it cannot honestly answer "what was available at time T" — including it
-- would silently let a backtest claim a price it cannot prove was on offer.
-- Those rows remain available to CLV, which compares against the CLOSE rather
-- than against an instant.
CREATE OR REPLACE MACRO odds_as_of(at_ts) AS TABLE
SELECT
    match_id, bookmaker_id, market_type, line, selection,
    arg_max(price_decimal, captured_at)  AS price_decimal,
    arg_max(available_size, captured_at) AS available_size,
    max(captured_at)                     AS captured_at
FROM odds_observations
WHERE capture_precision = 'TIMESTAMPED' AND captured_at <= at_ts
GROUP BY match_id, bookmaker_id, market_type, line, selection;

CREATE OR REPLACE MACRO best_price_as_of(at_ts) AS TABLE
SELECT
    match_id, market_type, line, selection,
    arg_max(bookmaker_id, price_decimal) AS bookmaker_id,
    max(price_decimal)                   AS price_decimal,
    count(*)                             AS n_books
FROM odds_as_of(at_ts)
GROUP BY match_id, market_type, line, selection;
