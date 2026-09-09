-- 0014_lineups — players, published elevens, and the instant they became known.
--
-- The entity M6.5 needs, built to the same rules as teams in M1 because a
-- misidentified player produces a phantom unexpected absence — which would
-- present itself as signal. The rules that survived M1 apply unchanged:
--
--   * the id is opaque, so nothing downstream can parse meaning out of it;
--   * an alias is a recorded human decision, never a similarity score;
--   * FUZZY is refused by a CHECK, not by a convention.
--
-- NOTE ON EMPTINESS: no source for these tables is reachable from the current
-- environment. The schema exists so the audit in 0015 has something to check
-- and so the source contract is written down rather than implied. It is not
-- evidence that lineups have been ingested.

CREATE TABLE players (
    player_id       VARCHAR PRIMARY KEY,   -- opaque surrogate, like team_id
    canonical_name  VARCHAR NOT NULL,
    birth_date      DATE,                  -- the only near-stable disambiguator
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes           VARCHAR
);

CREATE TABLE player_aliases (
    alias_id        VARCHAR PRIMARY KEY,
    player_id       VARCHAR NOT NULL REFERENCES players(player_id),
    source          VARCHAR NOT NULL,
    raw_name        VARCHAR NOT NULL,
    normalized_name VARCHAR NOT NULL,
    match_method    VARCHAR NOT NULL,
    -- Mirrors team_aliases: an alias exists as soon as a source names a player,
    -- but only an APPROVED one lets that player's lineup into the analytic
    -- view. This is the column that makes the guard below reachable.
    status          VARCHAR NOT NULL DEFAULT 'PROPOSED',
    decided_by      VARCHAR,
    decided_at      TIMESTAMPTZ,
    UNIQUE (source, raw_name),
    CHECK (status IN ('PROPOSED', 'APPROVED', 'REJECTED')),
    -- Rule 9, applied to a new entity. Player names collide far more than club
    -- names do — initials, transliterations, fathers and sons, two players of
    -- the same name in one league — so the rule matters more here, not less.
    CHECK (match_method <> 'FUZZY'),
    CHECK (match_method IN ('EXACT', 'ALIAS', 'SOURCE_ID', 'MANUAL'))
);

CREATE TABLE player_source_ids (
    source       VARCHAR NOT NULL,
    source_id    VARCHAR NOT NULL,
    player_id    VARCHAR NOT NULL REFERENCES players(player_id),
    PRIMARY KEY (source, source_id)
);

-- A published eleven, and — the column the whole milestone exists for — the
-- instant it was published.
--
-- published_at is NOT NULL and carries no default. A lineup whose publication
-- instant is unknown is useless for this experiment: the entire question is
-- what the market did AFTER it appeared. Deriving it from the kickoff (minus
-- an hour, say) would fabricate exactly the quantity being measured, which is
-- the same error M2 refused for odds and refuses again here.
CREATE TABLE lineups (
    lineup_id      VARCHAR PRIMARY KEY,
    match_id       VARCHAR NOT NULL REFERENCES matches(match_id),
    team_id        VARCHAR NOT NULL REFERENCES teams(team_id),
    source         VARCHAR NOT NULL,
    published_at   TIMESTAMPTZ NOT NULL,
    -- CONFIRMED is the official eleven; PREDICTED is a forecast of it, which is
    -- a different fact and must never be mistaken for one.
    lineup_status  VARCHAR NOT NULL,
    ingested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (match_id, team_id, source, published_at),
    CHECK (lineup_status IN ('CONFIRMED', 'PREDICTED'))
);

CREATE TABLE lineup_slots (
    lineup_id    VARCHAR NOT NULL REFERENCES lineups(lineup_id),
    player_id    VARCHAR NOT NULL REFERENCES players(player_id),
    role         VARCHAR NOT NULL,
    shirt_number SMALLINT,
    PRIMARY KEY (lineup_id, player_id),
    CHECK (role IN ('STARTER', 'BENCH', 'GOALKEEPER'))
);

CREATE INDEX idx_lineups_match ON lineups (match_id, published_at);
CREATE INDEX idx_slots_player   ON lineup_slots (player_id);

-- Only confirmed elevens whose identity is fully adjudicated, mirroring
-- v_analytic_matches.
--
-- The first version of this view excluded lineups containing a player with no
-- row in `players`. A test proved that guard unreachable: the foreign key on
-- lineup_slots already makes such a row impossible to insert. The real risk is
-- the one M1 found for teams — a player who EXISTS but whose alias has not been
-- adjudicated, which is how a name collision enters the dataset wearing a
-- valid id.
--
-- A lineup with one unadjudicated player is not partially usable: "unexpected
-- absence" is computed against the whole eleven, so a single wrong identity
-- corrupts the label for that match.
CREATE OR REPLACE VIEW v_analytic_lineups AS
SELECT l.*
FROM lineups l
WHERE l.lineup_status = 'CONFIRMED'
  AND NOT EXISTS (
      SELECT 1
      FROM lineup_slots s
      JOIN player_aliases a ON a.player_id = s.player_id
      WHERE s.lineup_id = l.lineup_id
        AND a.status <> 'APPROVED'
  );
