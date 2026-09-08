-- 0009_clv_views — CLV reporting.

CREATE OR REPLACE VIEW v_bet_clv AS
SELECT
    b.bet_id, b.run_id, b.match_id, b.bookmaker_id,
    b.market_type, b.line, b.selection,
    b.price_taken, b.price_precision, b.model_prob,
    m.competition_id, m.season_id, m.match_date_utc, m.kickoff_utc,
    c.ref_bookmaker_id, c.closing_price, c.closing_fair_prob, c.closing_basis,
    c.clv_price, c.clv_ev, c.clv_log, c.beat_close,
    c.line_matched, c.exclusion_reason
FROM bets b
JOIN v_analytic_matches m ON m.match_id = b.match_id
LEFT JOIN bet_clv c       ON c.bet_id   = b.bet_id;

-- The dashboard. Read `mean_clv_ev` as the expected ROI implied by the close:
-- positive with negative yield means unlucky; negative with positive yield
-- means lucky, and about to stop being.
--
-- Only line-matched bets count. A bet compared against a different line is not
-- a weaker measurement, it is a wrong one.
CREATE OR REPLACE VIEW v_clv_summary AS
SELECT
    run_id,
    competition_id,
    season_id,
    market_type,
    count(*)                                          AS n_bets,
    avg(clv_ev)                                       AS mean_clv_ev,
    median(clv_ev)                                    AS median_clv_ev,
    avg(clv_log)                                      AS mean_clv_log,
    avg(clv_price)                                    AS mean_clv_price,
    avg(CASE WHEN beat_close THEN 1.0 ELSE 0.0 END)   AS beat_close_rate,
    stddev_samp(clv_ev)                               AS clv_ev_stddev,
    -- t-stat of mean CLV against zero. |t| > 2 over a few hundred bets is real
    -- signal; yield needs thousands of bets to say as much.
    CASE WHEN stddev_samp(clv_ev) > 0 AND count(*) > 1
         THEN avg(clv_ev) / (stddev_samp(clv_ev) / sqrt(count(*))) END AS clv_t_stat
FROM v_bet_clv
WHERE line_matched AND clv_ev IS NOT NULL
GROUP BY run_id, competition_id, season_id, market_type;

-- How much of the ledger could actually be scored. A CLV computed over the
-- subset that happened to have a close is not a random sample.
CREATE OR REPLACE VIEW v_clv_coverage AS
SELECT
    run_id,
    count(*)                                                       AS n_bets,
    count(*) FILTER (WHERE line_matched)                           AS n_scored,
    count(*) FILTER (WHERE NOT line_matched)                       AS n_excluded,
    CAST(count(*) FILTER (WHERE line_matched) AS DOUBLE)
        / nullif(count(*), 0)                                      AS scored_fraction,
    list_sort(list(DISTINCT exclusion_reason)
        FILTER (WHERE exclusion_reason IS NOT NULL))               AS exclusion_reasons
FROM v_bet_clv
GROUP BY run_id;
