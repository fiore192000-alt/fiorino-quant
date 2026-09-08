-- 0012_model_views — where model meets market.

-- The join that M5 exists to produce: a model probability beside the price
-- actually on offer, and beside the reference close for CLV.
CREATE OR REPLACE VIEW v_model_vs_market AS
SELECT
    p.model_run_id,
    p.match_id,
    m.competition_id,
    m.season_id,
    m.kickoff_utc,
    p.market_type,
    p.line,
    p.selection,
    p.prob_win,
    p.prob_push,
    p.prob_half_win,
    p.prob_half_lose,
    p.prob_lose,
    p.used_prior,
    o.bookmaker_id,
    o.price_decimal          AS offered_price,
    o.capture_precision,
    -- Expected value per unit staked, with push and the half states handled:
    --   win pays (price - 1), half-win pays (price - 1)/2, push returns 0,
    --   half-lose costs 0.5, lose costs 1.
    p.prob_win       * (o.price_decimal - 1.0)
      + p.prob_half_win  * (o.price_decimal - 1.0) / 2.0
      + p.prob_push      * 0.0
      - p.prob_half_lose * 0.5
      - p.prob_lose      * 1.0                       AS edge_ev,
    r.closing_price,
    r.closing_fair_prob
FROM predictions p
JOIN v_analytic_matches m ON m.match_id = p.match_id
JOIN odds_observations o
  ON  o.match_id    = p.match_id
  AND o.market_type = p.market_type
  AND o.line        = p.line
  AND o.selection   = p.selection
LEFT JOIN reference_market r
  ON  r.match_id    = p.match_id
  AND r.market_type = p.market_type
  AND r.line        = p.line
  AND r.selection   = p.selection;

-- How well the model forecasts, against the only benchmark that matters.
-- A model that does not beat the de-vigged close has no edge, whatever its
-- log-likelihood says.
CREATE OR REPLACE VIEW v_model_calibration AS
SELECT
    p.model_run_id,
    m.competition_id,
    m.season_id,
    count(*)                                             AS n,
    avg(p.used_prior::INTEGER)                           AS prior_fraction,
    -- Brier against the realised outcome, for the model and for the close.
    avg((p.prob_win - hit.won) ^ 2)                      AS model_brier,
    avg((r.closing_fair_prob - hit.won) ^ 2)             AS market_brier,
    avg((r.closing_fair_prob - hit.won) ^ 2)
      - avg((p.prob_win - hit.won) ^ 2)                  AS brier_edge,
    avg(-ln(nullif(CASE WHEN hit.won = 1 THEN p.prob_win
                        ELSE 1 - p.prob_win END, 0)))    AS model_logloss,
    avg(-ln(nullif(CASE WHEN hit.won = 1 THEN r.closing_fair_prob
                        ELSE 1 - r.closing_fair_prob END, 0))) AS market_logloss
FROM predictions p
JOIN v_analytic_matches m ON m.match_id = p.match_id
JOIN reference_market r
  ON  r.match_id = p.match_id AND r.market_type = p.market_type
  AND r.line = p.line AND r.selection = p.selection
JOIN (
    SELECT mr.match_id, '1X2' AS mk, sel.selection,
           CASE WHEN sel.selection = CASE
                WHEN mr.goals_home > mr.goals_away THEN 'HOME'
                WHEN mr.goals_away > mr.goals_home THEN 'AWAY'
                ELSE 'DRAW' END THEN 1 ELSE 0 END AS won
    FROM match_results mr
    CROSS JOIN (SELECT unnest(['HOME', 'DRAW', 'AWAY']) AS selection) sel
) hit ON hit.match_id = p.match_id AND hit.selection = p.selection
WHERE p.market_type = 'ONE_X_TWO'
GROUP BY p.model_run_id, m.competition_id, m.season_id;
