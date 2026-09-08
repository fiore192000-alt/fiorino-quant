-- 0001_core — reference dimensions and ingestion provenance.
--
-- Everything M1 writes is attributable: which run, from which source, when.
-- `ingestion_runs` is the spine of that, and every fact table points at it.

CREATE TABLE schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        VARCHAR NOT NULL,
    checksum    VARCHAR NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE competitions (
    competition_id VARCHAR PRIMARY KEY,      -- 'ENG_PL', 'ITA_SA'
    name           VARCHAR NOT NULL,
    country        VARCHAR NOT NULL,
    tier           SMALLINT NOT NULL,
    is_cup         BOOLEAN NOT NULL DEFAULT FALSE
);

-- Seasons are first-class because league membership is a function of season,
-- not an attribute of a team. Promotion and relegation live in
-- team_season_membership, which needs a season to point at.
CREATE TABLE seasons (
    season_id  VARCHAR PRIMARY KEY,          -- '2024-2025'
    starts_on  DATE NOT NULL,
    ends_on    DATE NOT NULL,
    CHECK (ends_on > starts_on)
);

CREATE TABLE competition_seasons (
    competition_id VARCHAR NOT NULL REFERENCES competitions(competition_id),
    season_id      VARCHAR NOT NULL REFERENCES seasons(season_id),
    n_teams        SMALLINT,
    PRIMARY KEY (competition_id, season_id)
);

-- Which source-competition pairs we actually attempt. The "zero unresolved"
-- acceptance criterion is scoped to the rows in this table: Understat does not
-- cover the Championship, and pretending otherwise makes the criterion
-- unsatisfiable by construction rather than by failure.
CREATE TABLE source_coverage (
    source         VARCHAR NOT NULL,
    competition_id VARCHAR NOT NULL REFERENCES competitions(competition_id),
    supports_xg    BOOLEAN NOT NULL DEFAULT FALSE,
    note           VARCHAR,
    PRIMARY KEY (source, competition_id)
);

CREATE TABLE ingestion_runs (
    ingestion_run_id VARCHAR PRIMARY KEY,
    source           VARCHAR NOT NULL,
    competition_id   VARCHAR REFERENCES competitions(competition_id),
    season_id        VARCHAR REFERENCES seasons(season_id),
    started_at       TIMESTAMPTZ NOT NULL,
    finished_at      TIMESTAMPTZ,
    code_version     VARCHAR,
    bronze_path      VARCHAR,
    rows_read        INTEGER NOT NULL DEFAULT 0,
    rows_written     INTEGER NOT NULL DEFAULT 0,
    rows_quarantined INTEGER NOT NULL DEFAULT 0,
    status           VARCHAR NOT NULL DEFAULT 'RUNNING',
    note             VARCHAR
);
