-- 0011_models — model fits and their predictions (M5).
--
-- This is where penaltyblog finally enters, as a DEPENDENCY reached through an
-- adapter. Nothing below names it: swapping the statistical engine must not
-- touch ingestion, CLV or the backtest.

CREATE TABLE model_runs (
    model_run_id    VARCHAR PRIMARY KEY,
    model_name      VARCHAR NOT NULL,          -- 'dixon_coles', 'bivariate_poisson'
    model_version   VARCHAR NOT NULL,
    competition_id  VARCHAR REFERENCES competitions(competition_id),
    season_id       VARCHAR REFERENCES seasons(season_id),

    -- THE WALK-FORWARD BOUNDARY. No training row may have settled_at beyond
    -- trained_through. The fit is done through the point-in-time view, so this
    -- column records what the view was asked for rather than a promise.
    trained_through TIMESTAMPTZ NOT NULL,
    -- Extra gap between the last training result and the first prediction.
    -- Zero here because the models use only settled results; a rolling
    -- feature that straddles the cut would need this to be non-zero.
    embargo_seconds BIGINT NOT NULL DEFAULT 0,

    n_matches       INTEGER NOT NULL,
    n_teams         INTEGER NOT NULL,
    -- Teams predicted for but never seen in training: promoted sides, mostly.
    -- They get a league prior, and the count is kept because a fit carrying
    -- many of them is weaker than its log-likelihood suggests.
    n_prior_teams   INTEGER NOT NULL DEFAULT 0,
    params          JSON,
    loglikelihood   DOUBLE,
    aic             DOUBLE,
    fit_seconds     DOUBLE,
    fitted_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (n_matches >= 0)
);

-- Model output already projected onto the market vocabulary, so a prediction
-- joins to odds on (market_type, line, selection) with no translation layer.
--
-- FIVE probabilities, not one. A quarter line settles as half-win or half-lose
-- and an integer line pushes. Collapsing to a single prob_win is not a
-- simplification, it is a pricing error: with p_win=0.42, p_push=0.08 at 2.60
-- the true edge is +17.2% and the two-state formula reports +9.2%, so a 10%
-- threshold rejects the bet.
CREATE TABLE predictions (
    model_run_id   VARCHAR NOT NULL REFERENCES model_runs(model_run_id),
    match_id       VARCHAR NOT NULL REFERENCES matches(match_id),
    market_type    VARCHAR NOT NULL,
    line           DOUBLE  NOT NULL DEFAULT 0.0,
    selection      VARCHAR NOT NULL,
    -- When this prediction became makeable: the fit boundary, never the kickoff.
    as_of          TIMESTAMPTZ NOT NULL,
    prob_win       DOUBLE  NOT NULL,
    prob_half_win  DOUBLE  NOT NULL DEFAULT 0.0,
    prob_push      DOUBLE  NOT NULL DEFAULT 0.0,
    prob_half_lose DOUBLE  NOT NULL DEFAULT 0.0,
    prob_lose      DOUBLE  NOT NULL,
    lambda_home    DOUBLE,
    lambda_away    DOUBLE,
    -- TRUE when either side was unseen in training and priced from the league
    -- prior. Such predictions are honest but weaker, and downstream must be
    -- able to exclude them rather than discover them by their behaviour.
    used_prior     BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (model_run_id, match_id, market_type, line, selection),
    CHECK (abs(prob_win + prob_half_win + prob_push
               + prob_half_lose + prob_lose - 1.0) < 1e-6)
);

CREATE INDEX idx_pred_match ON predictions (match_id);
CREATE INDEX idx_pred_market ON predictions (match_id, market_type, line);
