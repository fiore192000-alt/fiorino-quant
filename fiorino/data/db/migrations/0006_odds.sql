-- 0006_odds — market reconstruction (M2).
--
-- From here on the system is not predicting matches; it is rebuilding the
-- market that the prediction will be measured against.
--
-- THE GOVERNING CONSTRAINT
--
--   Never invent a timestamp for an observation that has none.
--
-- Football-Data publishes at most two prices per market: a pre-match figure
-- and a closing figure. The pre-match column carries NO collection time. A
-- fabricated `captured_at` there would put a falsehood inside rule R1, which
-- everything downstream rests on. So `captured_at` is NULLABLE BY DESIGN and
-- every row states how precisely it is known.

-- The books themselves. `is_reference` marks the sharp benchmark whose
-- de-vigged close every CLV number is measured against; treat it as a
-- constant, because changing it invalidates every historical CLV.
CREATE TABLE bookmakers (
    bookmaker_id      VARCHAR PRIMARY KEY,
    name              VARCHAR NOT NULL,
    kind              VARCHAR NOT NULL,        -- SHARP | SOFT | EXCHANGE | AGGREGATOR
    is_reference      BOOLEAN NOT NULL DEFAULT FALSE,
    commission_rate   DOUBLE  NOT NULL DEFAULT 0.0,   -- exchanges only
    typical_max_stake DECIMAL(18,2),
    country           VARCHAR,
    note              VARCHAR,
    CHECK (kind IN ('SHARP', 'SOFT', 'EXCHANGE', 'AGGREGATOR')),
    CHECK (commission_rate >= 0.0 AND commission_rate < 0.2)
);

CREATE TABLE odds_observations (
    observation_id    VARCHAR PRIMARY KEY,
    match_id          VARCHAR NOT NULL REFERENCES matches(match_id),
    bookmaker_id      VARCHAR NOT NULL REFERENCES bookmakers(bookmaker_id),
    market_type       VARCHAR NOT NULL,        -- ONE_X_TWO | ASIAN_HANDICAP | TOTALS | ...
    line              DOUBLE  NOT NULL DEFAULT 0.0,   -- R3/R4: home perspective, never NULL
    selection         VARCHAR NOT NULL,
    price_decimal     DOUBLE  NOT NULL,

    -- TIMESTAMPED : the source gives a real instant (a poller, an API)
    -- OPENING     : first published price of the market
    -- PREMATCH    : collected at an unstated moment before kickoff
    -- CLOSING     : last price before kickoff; defined semantics, unknown clock
    capture_precision VARCHAR NOT NULL,
    -- Populated ONLY for TIMESTAMPED. NULL everywhere else, on purpose.
    captured_at       TIMESTAMPTZ,
    -- The upper bound that IS known: normally the kickoff. What makes an
    -- untimestamped price still usable without lying about it.
    observed_before   TIMESTAMPTZ,

    available_size    DECIMAL(18,2),           -- exchange depth only
    source            VARCHAR NOT NULL,
    ingestion_run_id  VARCHAR REFERENCES ingestion_runs(ingestion_run_id),
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CHECK (price_decimal > 1.0),
    CHECK (capture_precision IN ('TIMESTAMPED', 'OPENING', 'PREMATCH', 'CLOSING')),
    -- The constraint that enforces the rule rather than trusting it.
    CHECK ((capture_precision = 'TIMESTAMPED') = (captured_at IS NOT NULL))
);

-- One book publishes both a pre-match and a closing price for the same
-- selection, so precision belongs in the uniqueness key.
CREATE UNIQUE INDEX ux_odds_observation ON odds_observations (
    match_id, bookmaker_id, market_type, line, selection,
    capture_precision, coalesce(captured_at, '1970-01-01 00:00:00+00'::TIMESTAMPTZ)
);

-- Materialised closing line: the last price before kickoff per key.
CREATE TABLE odds_closing (
    match_id        VARCHAR NOT NULL REFERENCES matches(match_id),
    bookmaker_id    VARCHAR NOT NULL REFERENCES bookmakers(bookmaker_id),
    market_type     VARCHAR NOT NULL,
    line            DOUBLE  NOT NULL DEFAULT 0.0,
    selection       VARCHAR NOT NULL,
    price_decimal   DOUBLE  NOT NULL,
    observation_id  VARCHAR NOT NULL,
    -- How the close was established: 'DECLARED' when the source labels it as
    -- closing (Football-Data's C columns), 'LATEST' when it is the last
    -- timestamped observation we hold. A LATEST close from a thin poll is a
    -- weaker benchmark, and M3 must be able to tell the difference.
    closing_basis   VARCHAR NOT NULL,
    seconds_to_kickoff BIGINT,                 -- NULL when the close has no clock
    is_trusted      BOOLEAN NOT NULL DEFAULT TRUE,
    materialized_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, bookmaker_id, market_type, line, selection),
    CHECK (closing_basis IN ('DECLARED', 'LATEST'))
);

-- Overround-free probabilities, computed per COMPLETE market and never per
-- selection. Several methods may coexist for one key so the de-vig choice can
-- be compared without re-ingesting.
CREATE TABLE fair_probabilities (
    match_id         VARCHAR NOT NULL REFERENCES matches(match_id),
    bookmaker_id     VARCHAR NOT NULL REFERENCES bookmakers(bookmaker_id),
    market_type      VARCHAR NOT NULL,
    line             DOUBLE  NOT NULL DEFAULT 0.0,
    selection        VARCHAR NOT NULL,
    capture_precision VARCHAR NOT NULL,
    devig_method     VARCHAR NOT NULL,
    fair_prob        DOUBLE  NOT NULL,
    raw_implied_prob DOUBLE  NOT NULL,
    overround        DOUBLE  NOT NULL,
    n_selections     SMALLINT NOT NULL,
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, bookmaker_id, market_type, line, selection,
                 capture_precision, devig_method),
    CHECK (fair_prob > 0.0 AND fair_prob < 1.0)
);

CREATE INDEX idx_odds_match      ON odds_observations (match_id);
CREATE INDEX idx_odds_market     ON odds_observations (match_id, market_type, line);
CREATE INDEX idx_odds_precision  ON odds_observations (capture_precision);
CREATE INDEX idx_fair_match      ON fair_probabilities (match_id, market_type, line);
