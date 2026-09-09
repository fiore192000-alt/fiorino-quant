-- 0015_opportunities — the research opportunity list.
--
-- PR #2 does not look for bets. It builds the list of things that COULD be
-- researched, and says for each one exactly what is missing.
--
-- The states are INDEPENDENT on purpose. A fixture with no price is not a
-- fixture with no edge, and a single collapsed status column would make those
-- two indistinguishable on a screen. That collapse is the specific
-- falsification this migration exists to prevent:
--
--     NO ODDS  ->  DATA_GAP     ->  do not score
--     ODDS     ->  no advantage ->  NO_SIGNAL, score 0
--
-- Zero says "assessed and found worthless". A gap says "could not assess".
-- Only the second is true today for an upcoming fixture.
CREATE OR REPLACE VIEW v_research_opportunities AS
WITH price AS (
    SELECT match_id,
           count(*)                                                 AS n_prices,
           count(*) FILTER (WHERE capture_precision = 'TIMESTAMPED') AS n_timestamped,
           max(captured_at)                                          AS last_captured
    FROM odds_observations
    GROUP BY match_id
),
model AS (
    SELECT p.match_id, count(*) AS n_predictions, max(r.trained_through) AS fitted_through
    FROM predictions p
    JOIN model_runs r ON r.model_run_id = p.model_run_id
    GROUP BY p.match_id
),
lineup AS (
    SELECT match_id, count(*) AS n_lineups, min(published_at) AS published_at
    FROM v_analytic_lineups
    GROUP BY match_id
)
SELECT
    m.match_id,
    m.competition_id,
    m.season_id,
    th.canonical_name AS home_team,
    ta.canonical_name AS away_team,
    m.kickoff_utc,

    -- FIXTURE: about the calendar, nothing else.
    CASE WHEN res.match_id IS NOT NULL THEN 'FINISHED'
         WHEN m.kickoff_utc > now()    THEN 'UPCOMING'
         ELSE 'EXISTS' END                                   AS fixture_status,

    -- ODDS: DATA_GAP is not a judgement about value.
    CASE WHEN coalesce(p.n_prices, 0) = 0 THEN 'DATA_GAP'
         ELSE 'AVAILABLE' END                                AS odds_status,
    -- Separate from availability: a price with no instant cannot support any
    -- statement about WHEN the market knew something.
    CASE WHEN coalesce(p.n_prices, 0) = 0        THEN 'NONE'
         WHEN coalesce(p.n_timestamped, 0) > 0   THEN 'TIMESTAMPED'
         ELSE 'UNKNOWN_INSTANT' END                          AS odds_timestamp_quality,

    CASE WHEN coalesce(l.n_lineups, 0) > 0        THEN 'AVAILABLE'
         WHEN m.kickoff_utc > now()               THEN 'NOT_YET_AVAILABLE'
         ELSE 'DATA_GAP' END                                 AS lineup_status,
    CASE WHEN l.published_at IS NOT NULL THEN 'PUBLISHED_AT_KNOWN'
         ELSE 'NONE' END                                     AS lineup_timestamp_quality,

    CASE WHEN coalesce(mo.n_predictions, 0) > 0 THEN 'RUN'
         ELSE 'NOT_RUN' END                                  AS model_status,

    -- DECISION: only reachable when there is something to decide ABOUT.
    CASE WHEN coalesce(p.n_prices, 0) = 0 THEN 'DATA_GAP'
         WHEN coalesce(mo.n_predictions, 0) = 0 THEN 'DATA_GAP'
         ELSE 'EVALUABLE' END                                AS decision_status,

    coalesce(p.n_prices, 0)      AS n_prices,
    coalesce(mo.n_predictions, 0) AS n_predictions,
    p.last_captured
FROM v_analytic_matches m
JOIN teams th ON th.team_id = m.home_team_id
JOIN teams ta ON ta.team_id = m.away_team_id
LEFT JOIN match_results res ON res.match_id = m.match_id
LEFT JOIN price p  ON p.match_id  = m.match_id
LEFT JOIN model mo ON mo.match_id = m.match_id
LEFT JOIN lineup l ON l.match_id  = m.match_id;

-- What the terminal shows first: how much of the pipeline is actually fed.
CREATE OR REPLACE VIEW v_data_readiness AS
SELECT
    competition_id,
    season_id,
    fixture_status,
    count(*)                                                     AS n_matches,
    count(*) FILTER (WHERE odds_status = 'AVAILABLE')            AS n_with_odds,
    count(*) FILTER (WHERE odds_timestamp_quality = 'TIMESTAMPED') AS n_timestamped,
    count(*) FILTER (WHERE lineup_status = 'AVAILABLE')          AS n_with_lineup,
    count(*) FILTER (WHERE model_status = 'RUN')                 AS n_with_model,
    count(*) FILTER (WHERE decision_status = 'EVALUABLE')        AS n_evaluable,
    count(*) FILTER (WHERE decision_status = 'DATA_GAP')         AS n_data_gap
FROM v_research_opportunities
GROUP BY competition_id, season_id, fixture_status;
