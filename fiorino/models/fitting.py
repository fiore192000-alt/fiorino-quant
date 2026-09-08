"""
Walk-forward fitting and pricing.

The point-in-time discipline finally does real work here: a model is fitted
only on results that had settled by its boundary, and prices only fixtures that
had not yet kicked off. Nothing enforces that at the SQL level — the guarantee
comes from reading through :class:`PointInTimeView` and from recording the
boundary that was asked for.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from fiorino.data.access.point_in_time import PointInTimeView
from fiorino.models.adapters.penaltyblog import PenaltyblogModel
from fiorino.pricing.grid import grid_from_lambdas
from fiorino.pricing.markets import price_grid

__all__ = ["FitWindow", "fit_and_price", "walk_forward"]


@dataclass
class FitWindow:
    """One step of the walk: fit through a boundary, price what comes after."""

    as_of: datetime
    model_run_id: str
    n_train: int
    n_priced: int
    n_prior: int
    fit_seconds: float


def _model_run_id(model_name, competition_id, season_id, as_of) -> str:
    payload = f"{model_name}|{competition_id}|{season_id}|{as_of.isoformat()}"
    return "mr_" + hashlib.blake2b(payload.encode(), digest_size=10).hexdigest()


def fit_and_price(
    con,
    as_of: datetime,
    *,
    model_name: str = "dixon_coles",
    competition_id: str | None = None,
    season_id: str | None = None,
    half_life_days: float | None = 180.0,
    embargo: timedelta = timedelta(0),
    horizon: timedelta = timedelta(days=8),
    rho: float | None = None,
    min_train: int = 60,
) -> FitWindow | None:
    """Fit at ``as_of`` and price the fixtures in the following ``horizon``.

    Returns None when there is not enough settled history to fit, which is the
    normal state at the start of a season and must not be an error.
    """
    boundary = as_of - embargo
    view = PointInTimeView.at(con, boundary)
    training = view.results(competition_id)
    if len(training) < min_train:
        return None

    model = PenaltyblogModel(model_name, half_life_days=half_life_days)
    fit = model.fit(training)
    # The model's own rho unless the caller overrides it. Passing a hand-picked
    # value by default would discard what was fitted.
    effective_rho = model.fitted_rho if rho is None else rho

    upcoming = [
        m for m in PointInTimeView.at(con, as_of).upcoming_matches(competition_id)
        if m["kickoff_utc"] <= as_of + horizon
    ]
    if not upcoming:
        return None

    model_run_id = _model_run_id(model_name, competition_id, season_id, as_of)
    if con.execute(
        "SELECT 1 FROM model_runs WHERE model_run_id = ?", [model_run_id]
    ).fetchone():
        return None

    rows, n_prior = [], 0
    for match in upcoming:
        pair = model.expected_goals(match["home_team_id"], match["away_team_id"])
        if pair.used_prior:
            n_prior += 1
        grid = grid_from_lambdas(pair, rho=effective_rho)
        for priced in price_grid(grid):
            row = priced.as_row()
            rows.append([
                model_run_id, match["match_id"], row["market_type"], row["line"],
                row["selection"], as_of, row["prob_win"], row["prob_half_win"],
                row["prob_push"], row["prob_half_lose"], row["prob_lose"],
                pair.home, pair.away, pair.used_prior,
            ])

    con.execute(
        """INSERT INTO model_runs
           (model_run_id, model_name, model_version, competition_id, season_id,
            trained_through, embargo_seconds, n_matches, n_teams, n_prior_teams,
            params, loglikelihood, aic, fit_seconds)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [model_run_id, model_name, "1", competition_id, season_id, boundary,
         int(embargo.total_seconds()), fit.n_matches, fit.n_teams, n_prior,
         json.dumps({**fit.params, "rho": effective_rho,
                     "library_fallbacks": model.fallback_count}),
         fit.loglikelihood, fit.aic, fit.fit_seconds],
    )
    con.executemany(
        """INSERT INTO predictions
           (model_run_id, match_id, market_type, line, selection, as_of,
            prob_win, prob_half_win, prob_push, prob_half_lose, prob_lose,
            lambda_home, lambda_away, used_prior)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    return FitWindow(as_of, model_run_id, fit.n_matches, len(upcoming), n_prior,
                     fit.fit_seconds)


def walk_forward(
    con,
    *,
    model_name: str = "dixon_coles",
    competition_id: str | None = None,
    season_id: str | None = None,
    step: timedelta = timedelta(days=7),
    **kwargs,
) -> list[FitWindow]:
    """Refit every ``step`` across the whole history, pricing forward each time.

    The refit cadence is a real trade-off: refitting per match is correct and
    slow, per season is fast and stale. Weekly matches how a league actually
    updates — one round of fixtures — and keeps the fit count linear in weeks
    rather than in matches.
    """
    bounds = con.execute(
        """SELECT min(kickoff_utc), max(kickoff_utc) FROM v_analytic_matches
           WHERE (? IS NULL OR competition_id = ?)""",
        [competition_id, competition_id],
    ).fetchone()
    if not bounds or bounds[0] is None:
        return []

    windows, current, end = [], bounds[0], bounds[1]
    while current <= end:
        window = fit_and_price(
            con, current, model_name=model_name, competition_id=competition_id,
            season_id=season_id, **kwargs,
        )
        if window:
            windows.append(window)
        current = current + step
    return windows
