"""
penaltyblog behind fiorino's own interface.

The only module in the system that names penaltyblog. Everything downstream —
pricing, strategy, backtest — talks to :class:`GoalModel`, so the statistical
engine can be replaced without touching ingestion, CLV or the backtest.

Two things the library does not do, added here:

* **Unseen teams.** `penaltyblog` raises ValueError for a team absent from the
  training data. In a walk-forward backtest that is every promoted side in
  August, and every team in the first fitted week of a season. Refusing to
  predict them would silently delete the hardest fixtures from the sample,
  which is the same bias as deleting the ones you got wrong. They are priced
  from a league prior and flagged.

* **A stable parameter view.** The library exposes attack/defence by position
  in a flat array; this maps them to team ids so a caller never indexes by
  offset into someone else's array.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol, Sequence

import numpy as np

__all__ = ["GoalModel", "PenaltyblogModel", "MODELS", "FitResult", "LambdaPair"]

#: Model name -> penaltyblog class. Names are ours, not the library's, so a
#: migration to another engine keeps the same vocabulary in the database.
MODELS = {
    "poisson": "PoissonGoalsModel",
    "dixon_coles": "DixonColesGoalModel",
    "bivariate_poisson": "BivariatePoissonGoalModel",
    "negative_binomial": "NegativeBinomialGoalModel",
    "zero_inflated_poisson": "ZeroInflatedPoissonGoalsModel",
    "weibull_copula": "WeibullCopulaGoalsModel",
}


@dataclass(frozen=True)
class LambdaPair:
    """Expected goals for one fixture, and whether a prior had to be used."""

    home: float
    away: float
    used_prior: bool = False


@dataclass
class FitResult:
    model_name: str
    n_matches: int
    n_teams: int
    loglikelihood: float | None
    aic: float | None
    fit_seconds: float
    params: dict = field(default_factory=dict)


class GoalModel(Protocol):
    """What the rest of the system needs from a model. Nothing more."""

    name: str

    def fit(self, matches: Sequence[dict]) -> FitResult: ...
    def expected_goals(self, home_team_id: str, away_team_id: str) -> LambdaPair: ...
    @property
    def teams(self) -> set[str]: ...


class PenaltyblogModel:
    """Adapter over one penaltyblog goals model."""

    def __init__(self, model_name: str = "dixon_coles", *, half_life_days: float | None = 180.0):
        if model_name not in MODELS:
            raise ValueError(f"unknown model {model_name!r}; expected one of {sorted(MODELS)}")
        self.name = model_name
        #: Exponential time decay. None disables weighting entirely.
        #: A half-life makes the parameter interpretable — "a match this old
        #: counts half" — where penaltyblog's xi does not.
        self.half_life_days = half_life_days
        self._model = None
        self._teams: set[str] = set()
        self._league_mean_goals = (1.35, 1.15)
        #: Times the library refused to produce a grid and the parameters were
        #: used instead. Not zero in practice — see `_predict_lambdas`.
        self.fallback_count = 0

    # -- fitting ------------------------------------------------------
    def fit(self, matches: Sequence[dict]) -> FitResult:
        """Fit on already-settled matches.

        ``matches`` must come from a point-in-time reader. This method does not
        and cannot check that: it sees rows, not clocks. The boundary is the
        caller's to hold, which is why the fitting driver records it.
        """
        if len(matches) < 20:
            raise ValueError(
                f"refusing to fit on {len(matches)} matches; the parameters would be "
                "noise wearing a model's clothes"
            )

        home_goals = np.array([m["goals_home"] for m in matches], dtype=np.int64)
        away_goals = np.array([m["goals_away"] for m in matches], dtype=np.int64)
        home_teams = np.array([m["home_team_id"] for m in matches], dtype=str)
        away_teams = np.array([m["away_team_id"] for m in matches], dtype=str)
        weights = self._weights(matches)

        import penaltyblog as pb

        cls = getattr(pb.models, MODELS[self.name])
        started = time.perf_counter()
        model = cls(home_goals, away_goals, home_teams, away_teams, weights=weights)
        model.fit()
        elapsed = time.perf_counter() - started

        self._model = model
        self._teams = set(model.teams)
        # Last-resort baseline for a prior team: the observed mean score of the
        # training window, not a hardcoded constant, so it tracks the
        # competition. _prior_lambdas prefers the model's own predictions and
        # only falls back here when there is nothing fitted to average.
        self._league_mean_goals = (
            float(np.mean(home_goals)), float(np.mean(away_goals))
        )
        return FitResult(
            model_name=self.name,
            n_matches=len(matches),
            n_teams=len(self._teams),
            loglikelihood=getattr(model, "loglikelihood", None),
            aic=getattr(model, "aic", None),
            fit_seconds=elapsed,
            params={"half_life_days": self.half_life_days},
        )

    def _weights(self, matches) -> np.ndarray:
        """Exponential decay on match age, expressed as a half-life."""
        if not self.half_life_days:
            return np.ones(len(matches), dtype=float)
        dates = [m["match_date_utc"] for m in matches]
        newest = max(dates)
        ages = np.array([(newest - d).days for d in dates], dtype=float)
        return np.power(0.5, ages / float(self.half_life_days))

    # -- prediction ---------------------------------------------------
    @property
    def teams(self) -> set[str]:
        return set(self._teams)

    def expected_goals(self, home_team_id: str, away_team_id: str) -> LambdaPair:
        """Expected goals for a fixture, falling back to a league prior.

        A team absent from training gets league-average attack and defence.
        That is a genuinely weaker prediction, not a hidden one: `used_prior`
        travels with it and the caller decides whether to bet on it.
        """
        if self._model is None:
            raise RuntimeError("model has not been fitted")

        home_known = home_team_id in self._teams
        away_known = away_team_id in self._teams
        if home_known and away_known:
            return LambdaPair(*self._predict_lambdas(home_team_id, away_team_id),
                              used_prior=False)

        return LambdaPair(*self._prior_lambdas(home_team_id, away_team_id), used_prior=True)

    def _predict_lambdas(self, home_team_id: str, away_team_id: str) -> tuple[float, float]:
        """Expected goals for a known pair.

        Asks the library first, then falls back to its own fitted parameters.
        The fallback is not defensive padding: penaltyblog's optimiser bounds
        rho to (-2.5, 2.5), but the range in which the Dixon-Coles correction
        keeps the grid a distribution depends on the lambdas —

            max(-1/lambda_home, -1/lambda_away)  <=  rho  <=  min(1, 1/(lh*la))

        — so a fitted rho can be legal for most fixtures and drive a cell
        negative for a few. The library then raises "goal_matrix contains
        negative probabilities" and the whole walk-forward dies on one fixture.

        Only the lambdas are needed here; fiorino.pricing.grid builds the grid
        itself and clamps rho into the valid range. The identity used is the
        model's own, verified against its output:

            lambda_home = exp(attack_home + defence_away + hfa)
            lambda_away = exp(attack_away + defence_home)
        """
        try:
            grid = self._model.predict(home_team_id, away_team_id)
            return float(grid.home_goal_expectation), float(grid.away_goal_expectation)
        except ValueError:
            self.fallback_count += 1

        indices = self._model.param_indices()
        params = self._model.params_array
        n = self._model.n_teams
        position = {t: i for i, t in enumerate(self._model.teams)}
        h, a = position[home_team_id], position[away_team_id]
        hfa = float(params[indices["home_advantage"]]) if "home_advantage" in indices else 0.0
        return (
            float(np.exp(params[h] + params[n + a] + hfa)),
            float(np.exp(params[a] + params[n + h])),
        )

    @property
    def fitted_rho(self) -> float:
        """The model's own low-score correction, 0.0 when it has none.

        Taken from the fit rather than from the caller: Dixon-Coles estimates
        rho, and passing a hand-picked value would discard what was fitted.
        """
        if self._model is None:
            return 0.0
        indices = self._model.param_indices()
        if "rho" not in indices:
            return 0.0
        return float(self._model.params_array[indices["rho"]])

    def _prior_lambdas(self, home_team_id: str, away_team_id: str) -> tuple[float, float]:
        """Price an unseen side at league average, keeping the known side's own
        strength where there is one.

        Built by averaging the model's own predictions against every team it
        knows: that captures home advantage and the league's scoring level
        without assuming either.
        """
        known = sorted(self._teams)
        if not known:
            return self._league_mean_goals

        sample = known[: min(len(known), 12)]
        if home_team_id in self._teams:
            # Known home side against an average opponent.
            pairs = [self._predict_lambdas(home_team_id, t) for t in sample if t != home_team_id]
        elif away_team_id in self._teams:
            # Average opponent against a known away side.
            pairs = [self._predict_lambdas(t, away_team_id) for t in sample if t != away_team_id]
        else:
            # Neither known: the league's average fixture.
            pairs = [
                self._predict_lambdas(a, b)
                for a, b in zip(sample, sample[1:] + sample[:1]) if a != b
            ]
        if not pairs:
            return self._league_mean_goals

        return (
            float(np.mean([p[0] for p in pairs])),
            float(np.mean([p[1] for p in pairs])),
        )

    # -- introspection ------------------------------------------------
    def team_strengths(self) -> dict[str, dict[str, float]]:
        """Attack and defence by team id, rather than by array offset."""
        if self._model is None:
            raise RuntimeError("model has not been fitted")
        params = self._model.params_array
        n = self._model.n_teams
        return {
            team: {"attack": float(params[i]), "defence": float(params[i + n])}
            for i, team in enumerate(self._model.teams)
        }
