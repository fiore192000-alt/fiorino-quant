-- 0002_identity — canonical team identity.
--
-- team_id is an OPAQUE SURROGATE, never derived from the name. A hash of the
-- name breaks on the first rename (Hellas Verona -> Verona) and would take
-- every historical foreign key with it. The name is a mutable attribute of a
-- stable identity, not the identity itself.
--
-- Resolution precedence, first hit wins:
--   1. team_identity_overrides   human, deterministic, always wins
--   2. exact on raw name + source
--   3. exact on normalized name + country
--   4. fuzzy                     PROPOSAL ONLY, never applied automatically
--   5. unresolved                pipeline blocks
--
-- Rule 9 is absolute: a team whose identity is not APPROVED cannot reach the
-- analytic dataset, and neither can any match that references it.

CREATE TABLE teams (
    team_id        VARCHAR PRIMARY KEY,      -- opaque, e.g. 't_9f2c1ab84e07'
    canonical_name VARCHAR NOT NULL,
    country        VARCHAR NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by_run VARCHAR REFERENCES ingestion_runs(ingestion_run_id)
);

-- Every name any source has ever emitted. A rename adds an alias to the SAME
-- team_id; it never creates a team. valid_from / valid_to are optional and
-- record when a name was in use, for sources that replay history.
CREATE TABLE team_aliases (
    alias_raw        VARCHAR NOT NULL,
    source           VARCHAR NOT NULL,
    country          VARCHAR NOT NULL,       -- in the key: Arsenal ENG != Arsenal ARG
    alias_normalized VARCHAR NOT NULL,
    team_id          VARCHAR NOT NULL REFERENCES teams(team_id),
    match_method     VARCHAR NOT NULL,       -- OVERRIDE|EXACT_RAW|EXACT_NORMALIZED|SEED
    confidence       DOUBLE  NOT NULL DEFAULT 1.0,
    status           VARCHAR NOT NULL DEFAULT 'APPROVED',  -- APPROVED|REJECTED
    valid_from       DATE,
    valid_to         DATE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    ingestion_run_id VARCHAR REFERENCES ingestion_runs(ingestion_run_id),
    PRIMARY KEY (alias_raw, source, country),
    CHECK (match_method <> 'FUZZY')          -- fuzzy never lands here directly
);

-- Quarantine. Fuzzy output stops here and goes no further without a human.
CREATE TABLE team_alias_proposals (
    proposal_id        VARCHAR PRIMARY KEY,
    alias_raw          VARCHAR NOT NULL,
    source             VARCHAR NOT NULL,
    country            VARCHAR NOT NULL,
    alias_normalized   VARCHAR NOT NULL,
    candidate_team_id  VARCHAR REFERENCES teams(team_id),
    score              DOUBLE  NOT NULL,
    method             VARCHAR NOT NULL,     -- JARO_WINKLER|TOKEN_SET
    status             VARCHAR NOT NULL DEFAULT 'PROPOSED',  -- PROPOSED|APPROVED|REJECTED
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    ingestion_run_id   VARCHAR REFERENCES ingestion_runs(ingestion_run_id),
    decided_by         VARCHAR,
    decided_at         TIMESTAMPTZ,
    decision_note      VARCHAR
);

-- Human decisions. Append-only, highest precedence, fully attributed.
-- source '*' applies to every source.
CREATE TABLE team_identity_overrides (
    override_id VARCHAR PRIMARY KEY,
    alias_raw   VARCHAR NOT NULL,
    source      VARCHAR NOT NULL DEFAULT '*',
    country     VARCHAR NOT NULL,
    team_id     VARCHAR NOT NULL REFERENCES teams(team_id),
    reason      VARCHAR NOT NULL,
    created_by  VARCHAR NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One team_id, many source identifiers. A single source_id column on `teams`
-- cannot express "this is Understat 89 AND FBref 361ca564".
CREATE TABLE team_source_ids (
    source        VARCHAR NOT NULL,
    source_id     VARCHAR NOT NULL,
    team_id       VARCHAR NOT NULL REFERENCES teams(team_id),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_id)
);

-- Promotion and relegation, expressed as data rather than as a special case.
CREATE TABLE team_season_membership (
    team_id        VARCHAR NOT NULL REFERENCES teams(team_id),
    competition_id VARCHAR NOT NULL REFERENCES competitions(competition_id),
    season_id      VARCHAR NOT NULL REFERENCES seasons(season_id),
    source         VARCHAR NOT NULL,
    first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, competition_id, season_id)
);

CREATE INDEX idx_alias_norm ON team_aliases (alias_normalized, country);
CREATE INDEX idx_alias_team ON team_aliases (team_id);
CREATE INDEX idx_prop_status ON team_alias_proposals (status);
