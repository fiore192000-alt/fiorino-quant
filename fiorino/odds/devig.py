"""
Overround removal.

Always on a COMPLETE market, never on a single selection: the margin is a
property of the book's whole price set, and a lone price carries no information
about how it was loaded.

Shin is the default. It models the margin as compensation for informed traders
rather than as a flat tax, which matters because bookmakers do not spread the
margin evenly — they load it onto longshots. Multiplicative de-vigging
therefore overstates favourites and understates longshots, exactly where a
value bettor looks. penaltyblog supplies the implementations; this module
decides when they apply and records which was used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

__all__ = ["DevigResult", "devig", "overround", "banner",
           "method_in_force", "DEFAULT_METHOD", "METHODS"]

DEFAULT_METHOD = "SHIN"
METHODS = ("SHIN", "MULTIPLICATIVE", "POWER", "ADDITIVE", "ODDS_RATIO", "LOGARITHMIC")


@dataclass(frozen=True)
class DevigResult:
    selections: tuple[str, ...]
    fair_probs: tuple[float, ...]
    raw_implied: tuple[float, ...]
    overround: float
    #: What was actually applied.
    method: str
    #: What the caller asked for. Differs from `method` when the solver failed
    #: to converge, or when penaltyblog is not importable.
    requested_method: str
    n_selections: int

    @property
    def fell_back(self) -> bool:
        return self.method != self.requested_method

    def as_map(self) -> dict[str, float]:
        return dict(zip(self.selections, self.fair_probs))


def overround(prices: Sequence[float]) -> float:
    """Book margin: the amount by which implied probabilities exceed one."""
    if any(p <= 1.0 for p in prices):
        raise ValueError(f"decimal prices must exceed 1.0, got {list(prices)}")
    return sum(1.0 / p for p in prices) - 1.0


def devig(selections: Sequence[str], prices: Sequence[float], method: str = DEFAULT_METHOD) -> DevigResult:
    """Fair probabilities for one complete market.

    Raises rather than guessing when the market looks incomplete: a two-price
    "1X2" is a missing draw, and silently normalising it would produce
    confident nonsense that nothing downstream could detect.
    """
    if len(selections) != len(prices):
        raise ValueError("selections and prices must be the same length")
    if len(prices) < 2:
        raise ValueError(f"a market needs at least two selections, got {len(prices)}")
    if len(set(selections)) != len(selections):
        raise ValueError(f"duplicate selections in one market: {list(selections)}")

    method = method.upper()
    if method not in METHODS:
        raise ValueError(f"unknown de-vig method {method!r}; expected one of {METHODS}")

    book_margin = overround(prices)
    if book_margin < -1e-9:
        # Sum below 1.0 is an arbitrage or, far more often, a data error.
        # Either way it is not a market to de-vig silently.
        raise ValueError(
            f"implied probabilities sum to {book_margin + 1:.4f} (< 1); "
            "this is an arbitrage or a corrupt row, not a normal market"
        )

    raw = tuple(1.0 / p for p in prices)
    fair, method_used = _apply(method, list(prices))

    total = sum(fair)
    if abs(total - 1.0) > 1e-6:
        fair = [f / total for f in fair]

    return DevigResult(
        selections=tuple(selections),
        fair_probs=tuple(fair),
        raw_implied=raw,
        overround=book_margin,
        # The method ACTUALLY applied, which is not always the one requested.
        # Recording the request instead would be a lie with consequences: M3
        # established that the CLV calibration identity holds under
        # multiplicative de-vig and NOT under Shin, so a multiplicative result
        # wearing a SHIN label would quietly invalidate every check built on it.
        method=method_used,
        requested_method=method,
        n_selections=len(prices),
    )



def method_in_force(requested: str = DEFAULT_METHOD) -> tuple[str, str]:
    """The method `devig` would really apply, and why it differs if it does.

    Callers that publish numbers are expected to print this. The failure this
    prevents is specific and has already happened: every figure in the
    project's laboratory scripts was produced with MULTIPLICATIVE while being
    documented as SHIN, because the fallback was silent and `fell_back` was
    never read. A method mismatch is not a detail — the Shin/multiplicative gap
    on a longshot reaches 18 points of CLV, wider than any edge ever claimed.
    """
    requested = requested.upper()
    if requested not in METHODS:
        raise ValueError(f"unknown de-vig method: {requested}")
    if requested == "MULTIPLICATIVE":
        return "MULTIPLICATIVE", ""
    if _solver():
        return requested, ""
    return "MULTIPLICATIVE", _SOLVER_ERROR or "penaltyblog non importabile"


def banner(requested: str = DEFAULT_METHOD) -> str:
    """One line naming the de-vig actually in force. Print it above results."""
    applied, why = method_in_force(requested)
    if not why:
        return f"DE-VIG: {applied}"
    return (f"DE-VIG: {applied}  ***RIPIEGO***  richiesto {requested}, "
            f"non disponibile ({why}). I numeri sotto NON sono {requested}.")


def _multiplicative(prices: list[float]) -> list[float]:
    probs = [1.0 / p for p in prices]
    total = sum(probs)
    return [p / total for p in probs]


#: Resolved once per process, not per call.
#:
#: Probing on every call is not merely wasteful, it is NON-DETERMINISTIC. A
#: failed `import penaltyblog` can leave successfully-imported submodules in
#: sys.modules, so a second attempt succeeds where the first failed — and the
#: de-vig method then depends on import history rather than on configuration.
#: Observed directly: one rebuild produced rows tagged SHIN and MULTIPLICATIVE,
#: the next produced only SHIN, from identical input.
#:
#: Rule A of the M1 decisions requires rebuilds to be SEMANTICALLY identical.
#: A de-vig that flips method between runs breaks that, and it breaks it
#: quietly: both runs look successful and their fair probabilities differ.
_SOLVER: dict | None = None


#: Why the solver is unavailable, when it is. Kept because "penaltyblog is
#: missing" and "penaltyblog is present but its extensions were built for
#: another Python" are different failures with different fixes, and a caller
#: that only learns "no solver" cannot tell them apart.
_SOLVER_ERROR: str = ""


def _solver():
    global _SOLVER, _SOLVER_ERROR
    if _SOLVER is None:
        try:
            from penaltyblog.implied import ImpliedMethod, calculate_implied

            _SOLVER = {"calculate": calculate_implied, "methods": ImpliedMethod}
        except Exception as error:
            _SOLVER = {}
            _SOLVER_ERROR = f"{type(error).__name__}: {error}"
    return _SOLVER


def _apply(method: str, prices: list[float]) -> tuple[list[float], str]:
    """Delegate to penaltyblog, and report which method actually ran.

    penaltyblog is a dependency and not the core, which has a consequence this
    function has to own: it can be absent. In this repository the package
    directory shadows any installed copy and its Cython extensions are not
    built in a fresh clone, so `import penaltyblog` fails there — verified in a
    clean virtualenv, not assumed.

    Falling back to multiplicative is defensible; failing the whole ingest is
    not; and silently labelling the fallback as the requested method is worse
    than either.
    """
    solver = _solver()
    if not solver:
        return _multiplicative(prices), "MULTIPLICATIVE"
    ImpliedMethod = solver["methods"]
    calculate_implied = solver["calculate"]

    mapping = {
        "SHIN": ImpliedMethod.SHIN,
        "MULTIPLICATIVE": ImpliedMethod.MULTIPLICATIVE,
        "POWER": ImpliedMethod.POWER,
        "ADDITIVE": ImpliedMethod.ADDITIVE,
        "ODDS_RATIO": ImpliedMethod.ODDS_RATIO,
        "LOGARITHMIC": ImpliedMethod.LOGARITHMIC,
    }
    try:
        result = calculate_implied(prices, method=mapping[method])
        probs = list(result.probabilities)
    except Exception:
        # A solver can fail to converge on a degenerate market.
        return _multiplicative(prices), "MULTIPLICATIVE"

    if any(p <= 0.0 or p >= 1.0 for p in probs) or not all(map(_finite, probs)):
        return _multiplicative(prices), "MULTIPLICATIVE"
    return probs, method


def _finite(x: float) -> bool:
    return x == x and x not in (float("inf"), float("-inf"))
