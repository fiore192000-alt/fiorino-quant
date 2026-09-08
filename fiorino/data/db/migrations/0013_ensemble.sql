-- 0013_ensemble — the M6 incremental-information experiment.
--
-- M5 established that the de-vigged Pinnacle close beats a Dixon-Coles fit in
-- 10 datasets out of 10. M6 asks the different and sharper question: does the
-- model contain information the market LACKS, however little? A model that
-- loses to the market outright can still improve it, and a model that improves
-- it by nothing is a model to stop paying for.

-- The one parameter M6 estimates from outcomes, and therefore the one new way
-- the future could reach the past. Recorded per walk-forward boundary so the
-- audit can check every fit, and so the TRAJECTORY of the weight is visible:
-- a weight that wanders is a weight that is fitting noise.
CREATE TABLE ensemble_weights (
    weight_id       VARCHAR PRIMARY KEY,
    experiment      VARCHAR NOT NULL,      -- 'deployable' | 'information'
    competition_id  VARCHAR REFERENCES competitions(competition_id),
    season_id       VARCHAR REFERENCES seasons(season_id),

    -- Which market forecast was blended. PREMATCH is knowable at decision
    -- time and can be bet; CLOSING is not, and is used only to answer the
    -- information question, never to place a bet.
    market_source   VARCHAR NOT NULL,
    CHECK (market_source IN ('PREMATCH', 'CLOSING')),

    -- Only matches settled STRICTLY before this instant fed the estimate.
    trained_through TIMESTAMPTZ NOT NULL,
    n_train         INTEGER NOT NULL,
    -- The latest settled_at among the rows actually consumed. Recorded so the
    -- point-in-time claim is checkable against data rather than trusted.
    train_max_settled_at TIMESTAMPTZ NOT NULL,

    weight          DOUBLE NOT NULL,
    -- Same objective without the [0,1] constraint: separates "adds nothing"
    -- from "actively misleading", which the constrained fit cannot.
    unconstrained   DOUBLE NOT NULL,
    train_logloss   DOUBLE NOT NULL,
    -- The market alone on the same training rows. w = 0 is always feasible,
    -- so train_logloss <= market_logloss by construction and the gap is an
    -- IN-SAMPLE upper bound on any improvement, not evidence of one.
    market_logloss  DOUBLE NOT NULL,
    fitted_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (weight >= 0.0 AND weight <= 1.0),
    CHECK (n_train > 0)
);

CREATE INDEX idx_weights_boundary ON ensemble_weights (experiment, trained_through);

-- Out-of-sample forecast quality, one row per arm per ablation. Written by the
-- validation driver so the numbers in the report are auditable against the
-- database that produced them rather than against a JSON file.
CREATE TABLE forecast_scores (
    score_id          VARCHAR PRIMARY KEY,
    experiment        VARCHAR NOT NULL,
    arm               VARCHAR NOT NULL,    -- 'MARKET' | 'MODEL' | 'MARKET+MODEL'
    competition_id    VARCHAR REFERENCES competitions(competition_id),
    season_id         VARCHAR REFERENCES seasons(season_id),
    market_source     VARCHAR NOT NULL,

    n                 INTEGER NOT NULL,
    brier             DOUBLE NOT NULL,     -- per selection row, M5 convention
    logloss           DOUBLE NOT NULL,     -- per match, -ln p(realised)
    logloss_selection DOUBLE NOT NULL,     -- M5 convention, for reconciliation
    rps               DOUBLE NOT NULL,     -- ordered: HOME < DRAW < AWAY

    -- Paired bootstrap of (this arm - MARKET) on the same matches. Null on the
    -- MARKET row itself. An interval straddling zero is NOT evidence, and the
    -- report is required to say so rather than quote the point estimate.
    logloss_vs_market      DOUBLE,
    logloss_vs_market_low  DOUBLE,
    logloss_vs_market_high DOUBLE,
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (n > 0)
);

-- v_model_vs_market gains model_name, so an ablation can bet one arm at a time.
-- Without it the freshest-fit window in ModelEdge would mix the arms: three
-- forecasts of the same fixture, and the most recently fitted one wins
-- regardless of which experiment it belongs to.
CREATE OR REPLACE VIEW v_model_vs_market AS
SELECT
    p.model_run_id,
    r.model_name,
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
    p.prob_win       * (o.price_decimal - 1.0)
      + p.prob_half_win  * (o.price_decimal - 1.0) / 2.0
      + p.prob_push      * 0.0
      - p.prob_half_lose * 0.5
      - p.prob_lose      * 1.0                       AS edge_ev,
    rm.closing_price,
    rm.closing_fair_prob
FROM predictions p
JOIN model_runs r ON r.model_run_id = p.model_run_id
JOIN v_analytic_matches m ON m.match_id = p.match_id
JOIN odds_observations o
  ON  o.match_id    = p.match_id
  AND o.market_type = p.market_type
  AND o.line        = p.line
  AND o.selection   = p.selection
LEFT JOIN reference_market rm
  ON  rm.match_id    = p.match_id
  AND rm.market_type = p.market_type
  AND rm.line        = p.line
  AND rm.selection   = p.selection;

-- The audit the acceptance criteria are checked against.
--
-- An audit has to be able to fail, so it cannot be a view over the boundary
-- column alone — that would only restate what the fitter promised. The fitter
-- records the LATEST settlement instant among the rows it actually consumed,
-- and this view compares that against the boundary it claimed. A weight that
-- consumed a match settling at or after its own boundary appears here.
CREATE OR REPLACE VIEW v_weight_leakage AS
SELECT
    weight_id,
    experiment,
    market_source,
    trained_through,
    train_max_settled_at,
    date_diff('second', trained_through, train_max_settled_at) AS seconds_past_boundary
FROM ensemble_weights
WHERE train_max_settled_at >= trained_through;

-- Every weight, with the in-sample gap it bought. Reading this before the
-- out-of-sample scores is the honest order: an in-sample improvement is
-- guaranteed to be non-negative and means nothing on its own.
CREATE OR REPLACE VIEW v_weight_trajectory AS
SELECT
    experiment,
    market_source,
    competition_id,
    season_id,
    trained_through,
    n_train,
    weight,
    unconstrained,
    market_logloss - train_logloss AS in_sample_gain
FROM ensemble_weights
ORDER BY experiment, market_source, competition_id, season_id, trained_through;
