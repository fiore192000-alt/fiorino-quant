-- 0004_quality — persisted data-quality audit.

CREATE TABLE data_quality_runs (
    dq_run_id    VARCHAR PRIMARY KEY,
    started_at   TIMESTAMPTZ NOT NULL,
    finished_at  TIMESTAMPTZ,
    status       VARCHAR NOT NULL DEFAULT 'RUNNING',  -- PASS|FAIL|RUNNING
    n_findings   INTEGER NOT NULL DEFAULT 0,
    n_blocking   INTEGER NOT NULL DEFAULT 0,
    code_version VARCHAR
);

CREATE TABLE data_quality_findings (
    dq_run_id  VARCHAR NOT NULL REFERENCES data_quality_runs(dq_run_id),
    check_name VARCHAR NOT NULL,
    severity   VARCHAR NOT NULL,             -- BLOCKING|WARNING|INFO
    entity     VARCHAR,
    detail     VARCHAR NOT NULL,
    n_affected INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
