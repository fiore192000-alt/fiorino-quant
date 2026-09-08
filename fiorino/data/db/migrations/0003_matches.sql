-- 0003_matches — the canonical match, and what happens to the ones we cannot
-- identify.
--
-- match_id is deterministic:
--     blake2b(competition_id | season_id | match_date_utc | home_team_id | away_team_id)
--
-- Note match_date_utc, not the full kickoff timestamp. Sources correct kickoff
-- TIMES constantly (a 15:00 listing becomes 15:15, or a source stores local
-- time and later fixes the offset). Hashing the instant would mint a second
-- match every time that happens, which is precisely the duplication the
-- deterministic id exists to prevent. The date is the stable component; the
-- exact kickoff is a mutable attribute.
--
-- Corrections that DO cross a date boundary (postponements) legitimately
-- produce a new id, and are reconciled by match_merges rather than silently.

CREATE TABLE matches (
    match_id         VARCHAR PRIMARY KEY,
    competition_id   VARCHAR NOT NULL REFERENCES competitions(competition_id),
    season_id        VARCHAR NOT NULL REFERENCES seasons(season_id),
    match_date_utc   DATE NOT NULL,          -- identity component
    kickoff_utc      TIMESTAMPTZ NOT NULL,   -- mutable attribute
    home_team_id     VARCHAR NOT NULL REFERENCES teams(team_id),
    away_team_id     VARCHAR NOT NULL REFERENCES teams(team_id),
    neutral_venue    BOOLEAN NOT NULL DEFAULT FALSE,
    status           VARCHAR NOT NULL DEFAULT 'SCHEDULED',
    ingestion_run_id VARCHAR REFERENCES ingestion_runs(ingestion_run_id),
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (home_team_id <> away_team_id)
);

-- Kickoff corrections are HISTORY, not mutation.
--
-- Sources revise kickoff times constantly. Overwriting the row would destroy
-- the answer to "what did we believe the kickoff was at time T", which rule R1
-- exists to preserve — and it is impossible anyway: DuckDB refuses to UPDATE a
-- row that a foreign key still references. Both problems have the same answer,
-- which the rest of the ledger already uses: append.
--
-- `matches.kickoff_utc` holds the first observed value; the latest revision, if
-- any, wins in `v_analytic_matches`.
CREATE TABLE match_kickoff_revisions (
    match_id         VARCHAR NOT NULL REFERENCES matches(match_id),
    kickoff_utc      TIMESTAMPTZ NOT NULL,
    observed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    source           VARCHAR NOT NULL,
    ingestion_run_id VARCHAR REFERENCES ingestion_runs(ingestion_run_id),
    PRIMARY KEY (match_id, kickoff_utc, source)
);

CREATE TABLE match_results (
    match_id      VARCHAR PRIMARY KEY REFERENCES matches(match_id),
    goals_home    SMALLINT NOT NULL,
    goals_away    SMALLINT NOT NULL,
    goals_home_ht SMALLINT,
    goals_away_ht SMALLINT,
    -- Rule R1. Nothing may read this row before this instant. Feature
    -- computation and settlement both gate on it.
    settled_at    TIMESTAMPTZ NOT NULL,
    source        VARCHAR NOT NULL,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (goals_home >= 0 AND goals_away >= 0)
);

CREATE TABLE match_source_ids (
    source           VARCHAR NOT NULL,
    source_id        VARCHAR NOT NULL,
    match_id         VARCHAR NOT NULL REFERENCES matches(match_id),
    ingestion_run_id VARCHAR REFERENCES ingestion_runs(ingestion_run_id),
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_id)
);

-- Controlled merge. When a correction crosses a date boundary and mints a
-- second id for the same real match, the loser is recorded here and every
-- lookup follows the chain to the survivor. Merges are never implicit.
CREATE TABLE match_merges (
    merged_match_id    VARCHAR PRIMARY KEY,
    surviving_match_id VARCHAR NOT NULL REFERENCES matches(match_id),
    reason             VARCHAR NOT NULL,
    created_by         VARCHAR NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (merged_match_id <> surviving_match_id)
);

-- Rule 9 made physical. A match with an unapproved identity on either side
-- lands here and NOT in `matches`. It stays visible for audit, and it stays
-- out of every analytic query.
CREATE TABLE match_quarantine (
    quarantine_id    VARCHAR PRIMARY KEY,
    source           VARCHAR NOT NULL,
    source_id        VARCHAR,
    competition_id   VARCHAR,
    season_id        VARCHAR,
    match_date_utc   DATE,
    raw_home_name    VARCHAR NOT NULL,
    raw_away_name    VARCHAR NOT NULL,
    unresolved_side  VARCHAR NOT NULL,       -- HOME|AWAY|BOTH
    reason           VARCHAR NOT NULL,
    ingestion_run_id VARCHAR REFERENCES ingestion_runs(ingestion_run_id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_matches_date ON matches (match_date_utc);
CREATE INDEX idx_matches_comp ON matches (competition_id, season_id);
CREATE INDEX idx_matches_home ON matches (home_team_id);
CREATE INDEX idx_matches_away ON matches (away_team_id);
