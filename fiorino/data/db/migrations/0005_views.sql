-- 0005_views — the analytic gate and the point-in-time readers.

-- Rule 9, defence in depth. Even though the writer never inserts a match with
-- an unapproved identity, every analytic consumer reads through this view, so
-- a bug in the writer cannot leak quarantined identities into a backtest.
CREATE OR REPLACE VIEW v_analytic_matches AS
SELECT
    m.match_id, m.competition_id, m.season_id, m.match_date_utc,
    -- The latest revision wins; the original stands when none was filed.
    coalesce(rev.kickoff_utc, m.kickoff_utc) AS kickoff_utc,
    m.kickoff_utc AS kickoff_utc_original,
    m.home_team_id, m.away_team_id, m.neutral_venue, m.status,
    m.ingestion_run_id, m.ingested_at
FROM matches m
LEFT JOIN (
    SELECT match_id, arg_max(kickoff_utc, observed_at) AS kickoff_utc
    FROM match_kickoff_revisions GROUP BY match_id
) rev ON rev.match_id = m.match_id
WHERE NOT EXISTS (
        SELECT 1 FROM team_aliases a
        WHERE a.team_id IN (m.home_team_id, m.away_team_id)
          AND a.status <> 'APPROVED')
  AND m.match_id NOT IN (SELECT merged_match_id FROM match_merges);

CREATE OR REPLACE VIEW v_identity_audit AS
SELECT
    t.team_id,
    t.canonical_name,
    t.country,
    count(DISTINCT a.source)                                        AS n_sources,
    count(DISTINCT a.alias_raw)                                     AS n_aliases,
    count(DISTINCT s.source_id)                                     AS n_source_ids,
    count(DISTINCT p.proposal_id) FILTER (WHERE p.status = 'PROPOSED') AS n_open_proposals,
    count(DISTINCT o.override_id)                                   AS n_overrides
FROM teams t
LEFT JOIN team_aliases a          ON a.team_id = t.team_id
LEFT JOIN team_source_ids s       ON s.team_id = t.team_id
LEFT JOIN team_alias_proposals p  ON p.candidate_team_id = t.team_id
LEFT JOIN team_identity_overrides o ON o.team_id = t.team_id
GROUP BY t.team_id, t.canonical_name, t.country;

-- Cross-source reach: how many distinct sources contributed to each match.
CREATE OR REPLACE VIEW v_cross_source_matches AS
SELECT
    m.match_id,
    m.competition_id,
    m.season_id,
    m.match_date_utc,
    count(DISTINCT si.source) AS n_sources,
    list_sort(list(DISTINCT si.source)) AS sources
FROM v_analytic_matches m
LEFT JOIN match_source_ids si ON si.match_id = m.match_id
GROUP BY m.match_id, m.competition_id, m.season_id, m.match_date_utc;

CREATE OR REPLACE VIEW v_coverage AS
SELECT
    m.competition_id,
    m.season_id,
    count(*)                                             AS n_matches,
    count(r.match_id)                                    AS n_with_result,
    CAST(count(r.match_id) AS DOUBLE) / nullif(count(*), 0) AS result_coverage,
    min(m.match_date_utc)                                AS first_match,
    max(m.match_date_utc)                                AS last_match
FROM v_analytic_matches m
LEFT JOIN match_results r ON r.match_id = m.match_id
GROUP BY m.competition_id, m.season_id;

-- ---------------------------------------------------------------------
-- POINT-IN-TIME readers (schema rule R1).
-- The only sanctioned way for a model or a backtest to read history.
-- ---------------------------------------------------------------------

-- Results knowable at `at_ts`. A model training at `at_ts` may read these and
-- nothing else.
CREATE OR REPLACE MACRO results_as_of(at_ts) AS TABLE
SELECT r.match_id, r.goals_home, r.goals_away, r.goals_home_ht, r.goals_away_ht,
       r.settled_at, m.competition_id, m.season_id, m.match_date_utc,
       m.kickoff_utc, m.home_team_id, m.away_team_id, m.neutral_venue
FROM match_results r
JOIN v_analytic_matches m ON m.match_id = r.match_id
WHERE r.settled_at <= at_ts;

-- Matches that have not yet kicked off at `at_ts`.
CREATE OR REPLACE MACRO upcoming_matches_as_of(at_ts) AS TABLE
SELECT m.* FROM v_analytic_matches m WHERE m.kickoff_utc > at_ts;

-- Team league membership knowable at `at_ts`, derived from matches actually
-- played rather than from a season label, so it cannot see the future.
CREATE OR REPLACE MACRO team_membership_as_of(at_ts) AS TABLE
SELECT DISTINCT team_id, competition_id, season_id
FROM (
    SELECT home_team_id AS team_id, competition_id, season_id, kickoff_utc
    FROM v_analytic_matches
    UNION ALL
    SELECT away_team_id, competition_id, season_id, kickoff_utc
    FROM v_analytic_matches
)
WHERE kickoff_utc <= at_ts;
