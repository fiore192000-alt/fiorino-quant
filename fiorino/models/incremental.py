"""
M6 — does the model add information to the market?

Two experiments, and keeping them apart is the whole point of this module.

**DEPLOYABLE** blends the model with the de-vigged PREMATCH price. That price
is knowable at the decision instant, so the pooled forecast can be bet and its
CLV measured against the close. This is the question with money attached.

**INFORMATION** blends the model with the de-vigged CLOSING price. That price
is NOT knowable before kickoff, so this arm is evaluated and never bet. It
answers the scientific question — does the model know anything the closing
line does not — against the hardest benchmark available.

Why the separation is not pedantry
----------------------------------
CLV is measured against the closing line. A forecast that IS the closing line
therefore shows positive CLV BY CONSTRUCTION: it only ever bets prices better
than the close, because that is the definition of both. Betting an arm built
from the close would reproduce M4's clairvoyant oracle under a new name and
report it as M6's breakthrough. The oracle exists in this codebase precisely
as a positive control, and it must not be allowed to come back wearing an
ensemble's clothes.

So: the close scores forecasts, the prematch price places bets, and nothing in
the deployable path ever reads a closing price.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from fiorino.models.ensemble import TrainingRow, fit_weight, pool
from fiorino.models.scoring import ORDERED_1X2

__all__ = ["ArmRow", "build_arms", "walk_forward_ensemble", "MARKET_ARM", "ENSEMBLE_ARM"]

#: Arms are written into model_runs/predictions like any other forecast, so the
#: existing strategy, backtest and CLV machinery bets them with no new code.
MARKET_ARM = "market_prematch"
ENSEMBLE_ARM = "ensemble_prematch"

_PRECISION = {"deployable": "PREMATCH", "information": "CLOSING"}


@dataclass(frozen=True)
class ArmRow:
    """One fixture, with every arm's forecast over (HOME, DRAW, AWAY)."""

    match_id: str
    kickoff_utc: datetime
    settled_at: datetime | None
    model: tuple[float, float, float]
    market: tuple[float, float, float]
    outcome: int | None


def _run_id(prefix: str, *parts) -> str:
    payload = "|".join(str(p) for p in parts)
    return prefix + hashlib.blake2b(payload.encode(), digest_size=10).hexdigest()


def build_arms(con, experiment: str, competition_id: str | None = None) -> list[ArmRow]:
    """Assemble the per-fixture forecasts of both source arms.

    The model forecast is the FRESHEST fit whose boundary precedes the fixture's
    kickoff — the same rule ModelEdge bets on, so the evaluation scores what a
    bettor could have had rather than a retrospective refit.

    Fixtures missing either arm are dropped. That is a real restriction and the
    caller is told the count: an ablation run on a different sample per arm
    compares samples, not arms.
    """
    precision = _PRECISION[experiment]
    rows = con.execute(
        """
        WITH freshest AS (
            SELECT p.match_id, p.selection, p.prob_win,
                   row_number() OVER (
                       PARTITION BY p.match_id, p.selection
                       ORDER BY r.trained_through DESC, p.model_run_id
                   ) AS rn
            FROM predictions p
            JOIN model_runs r ON r.model_run_id = p.model_run_id
            JOIN v_analytic_matches m ON m.match_id = p.match_id
            WHERE p.market_type = 'ONE_X_TWO'
              AND r.model_name NOT IN (?, ?)
              AND r.trained_through < m.kickoff_utc
        )
        SELECT m.match_id, m.kickoff_utc, res.settled_at,
               max(f.prob_win)  FILTER (WHERE f.selection = 'HOME') AS mh,
               max(f.prob_win)  FILTER (WHERE f.selection = 'DRAW') AS md,
               max(f.prob_win)  FILTER (WHERE f.selection = 'AWAY') AS ma,
               max(fp.fair_prob) FILTER (WHERE fp.selection = 'HOME') AS kh,
               max(fp.fair_prob) FILTER (WHERE fp.selection = 'DRAW') AS kd,
               max(fp.fair_prob) FILTER (WHERE fp.selection = 'AWAY') AS ka,
               max(CASE WHEN res.goals_home > res.goals_away THEN 0
                        WHEN res.goals_home = res.goals_away THEN 1
                        ELSE 2 END) AS outcome
        FROM v_analytic_matches m
        JOIN freshest f ON f.match_id = m.match_id AND f.rn = 1
        JOIN fair_probabilities fp
          ON  fp.match_id = m.match_id
          AND fp.market_type = 'ONE_X_TWO'
          AND fp.capture_precision = ?
          AND fp.bookmaker_id IN (SELECT bookmaker_id FROM bookmakers WHERE is_reference)
        LEFT JOIN match_results res ON res.match_id = m.match_id
        WHERE (? IS NULL OR m.competition_id = ?)
        GROUP BY m.match_id, m.kickoff_utc, res.settled_at
        HAVING count(*) FILTER (WHERE f.selection IS NOT NULL) > 0
        ORDER BY m.kickoff_utc, m.match_id
        """,
        [MARKET_ARM, ENSEMBLE_ARM, precision, competition_id, competition_id],
    ).fetchall()

    arms = []
    for match_id, kickoff, settled, mh, md, ma, kh, kd, ka, outcome in rows:
        if None in (mh, md, ma, kh, kd, ka):
            continue
        arms.append(ArmRow(match_id, kickoff, settled,
                           (mh, md, ma), (kh, kd, ka), outcome))
    return arms


def _write_arm(con, model_name, competition_id, season_id, boundary,
               fixtures, forecasts, params) -> str:
    """Store an arm's forecasts as a model run, so it can be bet like any other."""
    model_run_id = _run_id("er_", model_name, competition_id, season_id, boundary.isoformat())
    if con.execute("SELECT 1 FROM model_runs WHERE model_run_id = ?",
                   [model_run_id]).fetchone():
        return model_run_id
    con.execute(
        """INSERT INTO model_runs
           (model_run_id, model_name, model_version, competition_id, season_id,
            trained_through, embargo_seconds, n_matches, n_teams, n_prior_teams,
            params, loglikelihood, aic, fit_seconds)
           VALUES (?, ?, '1', ?, ?, ?, 0, ?, 0, 0, ?, NULL, NULL, NULL)""",
        [model_run_id, model_name, competition_id, season_id, boundary,
         params.get("n_train", 0), json.dumps(params)],
    )
    con.executemany(
        """INSERT INTO predictions
           (model_run_id, match_id, market_type, line, selection, as_of,
            prob_win, prob_half_win, prob_push, prob_half_lose, prob_lose,
            lambda_home, lambda_away, used_prior)
           VALUES (?, ?, 'ONE_X_TWO', 0.0, ?, ?, ?, 0.0, 0.0, 0.0, ?, NULL, NULL, FALSE)""",
        [
            [model_run_id, fixture.match_id, ORDERED_1X2[k], boundary,
             probs[k], 1.0 - probs[k]]
            for fixture, probs in zip(fixtures, forecasts)
            for k in range(3)
        ],
    )
    return model_run_id


def walk_forward_ensemble(
    con,
    *,
    experiment: str = "deployable",
    competition_id: str | None = None,
    season_id: str | None = None,
    step: timedelta = timedelta(days=7),
    horizon: timedelta = timedelta(days=8),
    min_train: int = 40,
) -> list[dict]:
    """Refit the blend weight every ``step`` and forecast the fixtures after it.

    Requires M5's walk-forward to have already run: the model arm is read from
    `predictions`, not recomputed, so both experiments score exactly the
    forecasts the model actually made.

    For the deployable experiment the arms are also written back as model runs,
    which is what lets ModelEdge bet MARKET and MARKET+MODEL with no new
    strategy code — and therefore lets the ablation compare three arms through
    one engine rather than three.
    """
    if experiment not in _PRECISION:
        raise ValueError(f"unknown experiment {experiment!r}")

    arms = build_arms(con, experiment, competition_id)
    if not arms:
        return []

    settled = [a for a in arms if a.outcome is not None and a.settled_at is not None]
    bounds = (min(a.kickoff_utc for a in arms), max(a.kickoff_utc for a in arms))

    steps, boundary = [], bounds[0]
    while boundary <= bounds[1]:
        training = [
            TrainingRow(a.match_id, a.settled_at, a.model, a.market, a.outcome)
            for a in settled
        ]
        fitted = fit_weight(training, boundary, min_train=min_train)
        upcoming = [a for a in arms
                    if boundary < a.kickoff_utc <= boundary + horizon]
        if fitted is None or not upcoming:
            boundary += step
            continue

        weight_id = _run_id("w_", experiment, competition_id, season_id,
                            boundary.isoformat())
        if not con.execute("SELECT 1 FROM ensemble_weights WHERE weight_id = ?",
                           [weight_id]).fetchone():
            con.execute(
                """INSERT INTO ensemble_weights
                   (weight_id, experiment, competition_id, season_id, market_source,
                    trained_through, n_train, train_max_settled_at, weight,
                    unconstrained, train_logloss, market_logloss)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [weight_id, experiment, competition_id, season_id,
                 _PRECISION[experiment], boundary, fitted.n_train,
                 fitted.train_max_settled_at, fitted.weight, fitted.unconstrained,
                 fitted.train_logloss, fitted.market_logloss],
            )

        pooled = [pool(a.model, a.market, fitted.weight) for a in upcoming]
        if experiment == "deployable":
            params = {"n_train": fitted.n_train, "weight": fitted.weight,
                      "unconstrained": fitted.unconstrained}
            _write_arm(con, MARKET_ARM, competition_id, season_id, boundary,
                       upcoming, [a.market for a in upcoming], params)
            _write_arm(con, ENSEMBLE_ARM, competition_id, season_id, boundary,
                       upcoming, pooled, params)

        steps.append({
            "boundary": boundary,
            "weight": fitted.weight,
            "unconstrained": fitted.unconstrained,
            "n_train": fitted.n_train,
            "n_forecast": len(upcoming),
            "in_sample_gain": fitted.market_logloss - fitted.train_logloss,
        })
        boundary += step

    return steps
