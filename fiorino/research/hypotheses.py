"""
Situations in which the market might be systematically wrong.

Every hypothesis here is computable from what is ALREADY in the warehouse —
the fixture calendar, results, and de-vigged prices. Nothing needs a feed that
does not exist. That is the whole selection criterion: the hypotheses that
require lineups, injuries or timestamps are specified in next-experiment.md and
cannot be run, so they are not here.

WHY THIS IS NOT REFUTED BY M5-M6
--------------------------------
M5 and M6 tested one thing: a Dixon-Coles goals model, blended with the market.
They found it adds nothing. They did NOT test whether the market misprices
particular SITUATIONS, which is a different question with a different shape —
no model, no fitted parameters, just a subset of fixtures and the market's own
calibration inside it.

The distinction is the one already recorded in FINDINGS.md: "model A + X gives
nothing" does not imply "any use of X gives nothing".

POSITIVE CONTROLS
-----------------
Three hypotheses below are known, documented biases (the favourite-longshot
bias above all). They are here to test the SCANNER, not the market. A scan that
cannot find a bias that is known to exist has no standing to report that other
biases do not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

__all__ = ["Hypothesis", "HYPOTHESES", "label_matches", "SELECTIONS"]

SELECTIONS = ("HOME", "DRAW", "AWAY")


@dataclass(frozen=True)
class Hypothesis:
    """A named subset of fixtures, and why anyone would look there."""

    name: str
    rationale: str
    #: SQL predicate over the labelled fixture table built by label_matches().
    predicate: str
    #: True for a bias that is already documented in the literature. Used as a
    #: control on the scanner, and excluded from the discovery count so that
    #: finding a known bias is never reported as a discovery.
    positive_control: bool = False
    #: "fair" = Shin de-vigged, "raw" = the bookmaker's implied probability
    #: including the overround.
    #:
    #: This distinction turned out to matter and was not obvious. The
    #: favourite-longshot bias is exactly what Shin de-vigging is DESIGNED to
    #: remove, so testing for it on fair probabilities asks whether Shin
    #: over-corrects — a question about the de-vig, not about the market. The
    #: control has to run on raw prices to be a control at all.
    prob_source: str = "fair"
    #: When True the predicate is evaluated per SELECTION, and the token
    #: ``{prob}`` is replaced by that selection's own probability column.
    #:
    #: The distinction was found by a positive control failing. Rest and
    #: congestion are properties of a FIXTURE: the subset is the same for all
    #: three selections. The favourite-longshot bias is a property of a PRICE,
    #: and a match-level predicate like "raw_home < 0.12 OR raw_away < 0.12"
    #: selects matches in which one side is a longshot AND the other is a heavy
    #: favourite — so testing HOME inside it mixes the two cases and the bias
    #: cancels almost exactly. Which is what the scan reported: z = +0.63 on
    #: the most documented mispricing in the literature.
    selection_level: bool = False


#: One row per fixture, carrying everything the predicates need. Built once per
#: dataset because recomputing rest days inside twelve predicates would be both
#: slow and a place for twelve subtly different definitions to appear.
LABEL_SQL = """
WITH played AS (
    SELECT m.match_id, m.competition_id, m.season_id, m.kickoff_utc,
           m.home_team_id, m.away_team_id,
           r.goals_home, r.goals_away,
           CASE WHEN r.goals_home > r.goals_away THEN 'HOME'
                WHEN r.goals_home < r.goals_away THEN 'AWAY'
                ELSE 'DRAW' END AS outcome
    FROM v_analytic_matches m
    JOIN match_results r ON r.match_id = m.match_id
),
-- One row per (team, match), so rest and congestion are computed once for a
-- team regardless of whether it was home or away.
appearances AS (
    SELECT match_id, kickoff_utc, home_team_id AS team_id FROM played
    UNION ALL
    SELECT match_id, kickoff_utc, away_team_id AS team_id FROM played
),
rest AS (
    SELECT
        match_id, team_id,
        date_diff('day',
                  lag(kickoff_utc) OVER (PARTITION BY team_id ORDER BY kickoff_utc),
                  kickoff_utc) AS rest_days,
        count(*) OVER (
            PARTITION BY team_id ORDER BY kickoff_utc
            RANGE BETWEEN INTERVAL 8 DAYS PRECEDING AND CURRENT ROW
        ) AS matches_in_8_days
    FROM appearances
),
-- Points before this match, and matches still to play. Both are point-in-time
-- by construction: the window is bounded by the current row, so a fixture never
-- sees its own result or any later one.
standings AS (
    SELECT
        a.match_id, a.team_id, a.kickoff_utc,
        coalesce(sum(pts.points) OVER (
            PARTITION BY a.team_id ORDER BY a.kickoff_utc
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS points_before,
        count(*) OVER (PARTITION BY a.team_id) AS total_matches,
        row_number() OVER (PARTITION BY a.team_id ORDER BY a.kickoff_utc) AS matchday
    FROM appearances a
    JOIN (
        SELECT match_id, home_team_id AS team_id,
               CASE outcome WHEN 'HOME' THEN 3 WHEN 'DRAW' THEN 1 ELSE 0 END AS points
        FROM played
        UNION ALL
        SELECT match_id, away_team_id,
               CASE outcome WHEN 'AWAY' THEN 3 WHEN 'DRAW' THEN 1 ELSE 0 END
        FROM played
    ) pts ON pts.match_id = a.match_id AND pts.team_id = a.team_id
)
SELECT
    p.match_id, p.competition_id, p.season_id, p.kickoff_utc, p.outcome,
    rh.rest_days            AS home_rest_days,
    ra.rest_days            AS away_rest_days,
    rh.matches_in_8_days    AS home_matches_8d,
    ra.matches_in_8_days    AS away_matches_8d,
    sh.points_before        AS home_points,
    sa.points_before        AS away_points,
    sh.matchday             AS home_matchday,
    sh.total_matches        AS season_length,
    dayofweek(p.kickoff_utc) AS dow,
    month(p.kickoff_utc)     AS month,
    -- The market's own view. Both forms: the de-vigged probability every
    -- other part of the system uses, and the raw implied one the controls need.
    fh.fair_prob AS p_home, fd.fair_prob AS p_draw, fa.fair_prob AS p_away,
    fh.raw_implied_prob AS raw_home, fd.raw_implied_prob AS raw_draw,
    fa.raw_implied_prob AS raw_away
FROM played p
JOIN rest rh ON rh.match_id = p.match_id AND rh.team_id = p.home_team_id
JOIN rest ra ON ra.match_id = p.match_id AND ra.team_id = p.away_team_id
JOIN standings sh ON sh.match_id = p.match_id AND sh.team_id = p.home_team_id
JOIN standings sa ON sa.match_id = p.match_id AND sa.team_id = p.away_team_id
JOIN fair_probabilities fh
  ON fh.match_id = p.match_id AND fh.selection = 'HOME'
 AND fh.market_type = 'ONE_X_TWO' AND fh.capture_precision = 'PREMATCH'
 AND fh.bookmaker_id IN (SELECT bookmaker_id FROM bookmakers WHERE is_reference)
JOIN fair_probabilities fd
  ON fd.match_id = p.match_id AND fd.selection = 'DRAW'
 AND fd.market_type = 'ONE_X_TWO' AND fd.capture_precision = 'PREMATCH'
 AND fd.bookmaker_id = fh.bookmaker_id
JOIN fair_probabilities fa
  ON fa.match_id = p.match_id AND fa.selection = 'AWAY'
 AND fa.market_type = 'ONE_X_TWO' AND fa.capture_precision = 'PREMATCH'
 AND fa.bookmaker_id = fh.bookmaker_id
"""


def label_matches(con, competition_id: str | None = None) -> str:
    """Materialise the labelled fixture table. Returns its name."""
    con.execute("CREATE OR REPLACE TEMP TABLE labelled AS " + LABEL_SQL)
    if competition_id:
        con.execute("DELETE FROM labelled WHERE competition_id <> ?", [competition_id])
    return "labelled"


HYPOTHESES: tuple[Hypothesis, ...] = (
    # -- positive controls: known biases, here to test the scanner ----------
    Hypothesis(
        "control_longshot_raw",
        "The favourite-longshot bias on RAW prices, where it is documented to "
        "live. Evaluated per selection, because it is a property of a price. "
        "If the scanner cannot see this, the scanner is broken and nothing "
        "else in the table can be believed.",
        "{prob} < 0.12",
        positive_control=True, prob_source="raw", selection_level=True,
    ),
    Hypothesis(
        "control_favourite_raw",
        "The other side of the same coin: short prices should carry less of "
        "the overround than long ones.",
        "{prob} > 0.60",
        positive_control=True, prob_source="raw", selection_level=True,
    ),
    Hypothesis(
        "control_longshot_devigged",
        "The same per-selection split on Shin de-vigged prices. Not a control "
        "on the scanner but a check on the de-vig: Shin exists to remove "
        "precisely this bias, so a large residual would mean it under-corrects "
        "and every fair_prob in the system is shaded.",
        "{prob} < 0.12",
        positive_control=True, selection_level=True,
    ),
    Hypothesis(
        "control_all_matches",
        "Every fixture. A non-zero bias here cannot be a situation — there is "
        "no complement — and it is reported as the degenerate case it is.",
        "TRUE",
        positive_control=True,
    ),

    # -- rest and congestion: computable today, never tested ---------------
    Hypothesis(
        "home_short_rest",
        "Home side playing on three days' rest or fewer. The classic fatigue "
        "story, and the one closest in shape to 'squadre dopo la Champions' "
        "that this data can express.",
        "home_rest_days IS NOT NULL AND home_rest_days <= 3",
    ),
    Hypothesis(
        "away_short_rest",
        "Same for the away side, which also carries the travel that a home "
        "side does not.",
        "away_rest_days IS NOT NULL AND away_rest_days <= 3",
    ),
    Hypothesis(
        "home_rest_advantage",
        "Home side with at least three more days of rest than the visitor. A "
        "relative measure: absolute fatigue may be priced while the "
        "DIFFERENCE is not.",
        "home_rest_days IS NOT NULL AND away_rest_days IS NOT NULL "
        "AND home_rest_days - away_rest_days >= 3",
    ),
    Hypothesis(
        "away_rest_advantage",
        "The mirror. Included because a bias appearing on only one side of a "
        "symmetric pair is usually noise.",
        "home_rest_days IS NOT NULL AND away_rest_days IS NOT NULL "
        "AND away_rest_days - home_rest_days >= 3",
    ),
    Hypothesis(
        "home_congested",
        "Third match in eight days for the home side.",
        "home_matches_8d >= 3",
    ),
    Hypothesis(
        "away_congested",
        "Third match in eight days for the visitor.",
        "away_matches_8d >= 3",
    ),

    # -- stakes and calendar ------------------------------------------------
    Hypothesis(
        "dead_rubber",
        "Last four rounds, both sides in the middle of the table by points — "
        "the closest this data comes to 'nothing left to play for'. Motivation "
        "is the standard explanation for late-season surprises, and it is not "
        "in any goals model.",
        "home_matchday > season_length - 4 "
        "AND abs(home_points - away_points) < 8 "
        "AND home_points BETWEEN season_length AND season_length * 1.7",
    ),
    Hypothesis(
        "mismatch_late_season",
        "Late season with a large points gap: one side chasing something, the "
        "other not.",
        "home_matchday > season_length - 6 AND abs(home_points - away_points) >= 20",
    ),
    Hypothesis(
        "midweek",
        "Tuesday to Thursday. Different crowds, rotated sides, and a fixture "
        "the market may model less carefully than a Saturday.",
        "dow IN (2, 3, 4)",
    ),
    Hypothesis(
        "festive",
        "The December to early-January pile-up, where congestion is extreme "
        "and squad rotation least predictable.",
        "(month = 12 AND dayofweek(kickoff_utc) IS NOT NULL) OR month = 1",
    ),
    Hypothesis(
        "season_opening",
        "First three rounds, when last season's form is stale and the market "
        "has the least information — the window where a model would most "
        "plausibly know something.",
        "home_matchday <= 3",
    ),
)
