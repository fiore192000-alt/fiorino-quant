"""
Does lineup news leave a measurable residue in the price?

The question before any model, and the one that decides whether months of data
collection are worth starting. It is deliberately NOT "can we predict the
result": it is "does the market move when this information arrives, more than
it moves anyway".

THE RULE, ENFORCED AND NOT ADVISED
----------------------------------
If a fact is not timestamped, it does not enter this experiment. Not as a
fallback, not "approximately", not with the kickoff standing in for the
publication instant. :func:`require_timestamped` raises rather than returning a
degraded answer, because the whole measurement is a difference between two
moments and a fabricated moment fabricates the result.

This is the one place in the system where refusing to compute is the correct
behaviour.

THE DESIGN: DIFFERENCE IN DIFFERENCES
-------------------------------------
Two confounders make a naive "how much did the price move after the lineup"
useless:

* prices move anyway, and
* they move FASTER as kickoff approaches, so any window nearer kickoff shows
  more movement whatever happens in it.

So the statistic is a double difference:

    within a match   post_move - pre_move       (kills match-level volatility)
    between matches  treated - untreated        (kills clock acceleration,
                                                 because both groups are
                                                 measured in the same window
                                                 relative to publication)

    ┌──────────── pre ────────────┬──────────── post ────────────┐
    │                             │                              │
  T_pub - w                    T_pub                        T_pub + w
                                  ▲
                          lineup published

A match where the eleven is exactly as expected is the control. It has a
publication instant too, so it has both windows; it simply has no shock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta

__all__ = [
    "Category", "CATEGORIES", "ShockScore", "formation_shock",
    "require_timestamped", "measure_windows", "difference_in_differences",
    "MatchWindows", "DiDResult",
]


class Category:
    """The news taxonomy. One match can carry several."""

    GOALKEEPER_OUT = "GOALKEEPER_OUT"
    KEY_FORWARD_OUT = "KEY_FORWARD_OUT"
    KEY_DEFENDER_OUT = "KEY_DEFENDER_OUT"
    MULTIPLE_ABSENCES = "MULTIPLE_ABSENCES"
    SURPRISE_XI = "SURPRISE_XI"
    NONE = "NONE"


CATEGORIES = (
    Category.GOALKEEPER_OUT,
    Category.KEY_FORWARD_OUT,
    Category.KEY_DEFENDER_OUT,
    Category.MULTIPLE_ABSENCES,
    Category.SURPRISE_XI,
)

#: How much a position is worth to a scoreline, used only to WEIGHT a shock,
#: never to price one. Deliberately coarse: a single goalkeeper matters more
#: than a single midfielder, and pretending to know the ratio to two decimals
#: would be a model wearing a constant's clothes.
POSITION_WEIGHT = {
    "GOALKEEPER": 1.0,
    "DEFENDER": 0.6,
    "MIDFIELDER": 0.5,
    "FORWARD": 0.8,
}


@dataclass(frozen=True)
class ShockScore:
    """A simple, legible score. Not a model — a ruler.

    ``importance`` is the share of recent starts the absent player had, which
    is the only importance measure derivable without a rating system. A player
    who started every match carries 1.0; a rotation player carries less.

    Building CatBoost before knowing whether this crude version moves with the
    market would hide the answer rather than find it: if the signal does not
    exist in a form this simple, a complex model mostly learns to fit noise.
    """

    value: float
    n_absent: int
    categories: tuple[str, ...]
    detail: dict


def formation_shock(absences, *, expected_xi_size: int = 11) -> ShockScore:
    """Score a set of unexpected absences.

    ``absences`` is a sequence of dicts with ``position``, ``start_share``
    (0..1) and ``replacement_share`` (the replacement's own start share, so a
    like-for-like swap scores near zero).
    """
    total = 0.0
    categories = []
    for absence in absences:
        position = absence["position"]
        weight = POSITION_WEIGHT.get(position, 0.5)
        importance = float(absence.get("start_share", 0.0))
        replacement = float(absence.get("replacement_share", 0.0))
        # A replacement who also starts most weeks is not a shock. The gap is
        # clipped at zero: an upgrade is not a negative shock, it is a
        # different event, and lumping the two would cancel real signal.
        gap = max(importance - replacement, 0.0)
        total += weight * gap
        if position == "GOALKEEPER":
            categories.append(Category.GOALKEEPER_OUT)
        elif position == "FORWARD" and importance >= 0.6:
            categories.append(Category.KEY_FORWARD_OUT)
        elif position == "DEFENDER" and importance >= 0.6:
            categories.append(Category.KEY_DEFENDER_OUT)

    n = len(absences)
    if n >= 3:
        categories.append(Category.MULTIPLE_ABSENCES)
    if n >= expected_xi_size // 2:
        categories.append(Category.SURPRISE_XI)
    if not categories:
        categories.append(Category.NONE)

    return ShockScore(value=total, n_absent=n,
                      categories=tuple(dict.fromkeys(categories)),
                      detail={"expected_xi_size": expected_xi_size})


def require_timestamped(con) -> None:
    """Refuse to run on data that cannot answer the question.

    Raises rather than warning. Every other audit in this system reports and
    continues, because a report over incomplete data is still informative. Here
    it is not: an event study on prices with no instants measures nothing, and
    a number produced anyway would be indistinguishable from a real one.
    """
    stamped = con.execute(
        """SELECT count(*) FROM odds_observations
           WHERE capture_precision = 'TIMESTAMPED' AND captured_at IS NOT NULL"""
    ).fetchone()[0]
    if not stamped:
        raise RuntimeError(
            "no TIMESTAMPED odds: an event study needs prices with instants. "
            "Using PREMATCH prices here would compare two moments that the data "
            "does not distinguish. See docs/architecture/data-acquisition.md."
        )
    undated = con.execute(
        "SELECT count(*) FROM lineups WHERE published_at IS NULL"
    ).fetchone()[0]
    if undated:
        raise RuntimeError(f"{undated} lineups carry no publication instant")


@dataclass(frozen=True)
class MatchWindows:
    match_id: str
    selection: str
    pre_move: float          # log-odds change before publication
    post_move: float         # log-odds change after publication
    did: float               # post - pre
    shock: float
    categories: tuple[str, ...]


def _logit(p: float) -> float:
    p = min(max(p, 1e-9), 1.0 - 1e-9)
    return math.log(p / (1.0 - p))


def measure_windows(con, *, window: timedelta = timedelta(minutes=45),
                    market_type: str = "ONE_X_TWO",
                    bookmaker_id: str | None = None) -> list[MatchWindows]:
    """Per match and selection, the movement each side of publication.

    Prices are converted to log-odds before differencing: a move from 1.10 to
    1.12 and one from 5.0 to 5.1 are not the same event on a probability scale,
    and averaging them there would let long prices dominate by arithmetic
    rather than by information.
    """
    require_timestamped(con)
    rows = con.execute(
        """
        WITH pub AS (
            SELECT match_id, min(published_at) AS t_pub
            FROM v_analytic_lineups GROUP BY match_id
        ),
        priced AS (
            SELECT o.match_id, o.selection, o.captured_at, o.price_decimal,
                   p.t_pub
            FROM odds_observations o
            JOIN pub p ON p.match_id = o.match_id
            WHERE o.capture_precision = 'TIMESTAMPED'
              AND o.market_type = ?
              AND (? IS NULL OR o.bookmaker_id = ?)
        )
        SELECT match_id, selection,
               arg_min(price_decimal, captured_at)
                   FILTER (WHERE captured_at <  t_pub)                AS pre_first,
               arg_max(price_decimal, captured_at)
                   FILTER (WHERE captured_at <  t_pub)                AS pre_last,
               arg_min(price_decimal, captured_at)
                   FILTER (WHERE captured_at >= t_pub)                AS post_first,
               arg_max(price_decimal, captured_at)
                   FILTER (WHERE captured_at >= t_pub)                AS post_last
        FROM priced
        WHERE captured_at BETWEEN t_pub - ? AND t_pub + ?
        GROUP BY match_id, selection
        """,
        [market_type, bookmaker_id, bookmaker_id, window, window],
    ).fetchall()

    out = []
    for match_id, selection, pre_first, pre_last, post_first, post_last in rows:
        if None in (pre_first, pre_last, post_first, post_last):
            continue
        # 1/price is the raw implied probability. The overround cancels in the
        # difference as long as it is stable across the window, which over
        # ninety minutes on one book it is.
        pre_move = _logit(1 / pre_last) - _logit(1 / pre_first)
        post_move = _logit(1 / post_last) - _logit(1 / post_first)
        out.append(MatchWindows(match_id, selection, pre_move, post_move,
                                post_move - pre_move, 0.0, ()))
    return out


@dataclass(frozen=True)
class DiDResult:
    category: str
    n_treated: int
    n_control: int
    treated_did: float
    control_did: float
    effect: float
    se: float
    z: float
    p_value: float


def difference_in_differences(windows, category_of, *,
                              category: str) -> DiDResult | None:
    """Treated minus control, on the within-match double difference.

    ``category_of`` maps a match_id to its categories. Absolute movement is
    used: lineup news should make the price move, and its DIRECTION is a
    different and much harder claim that this design does not attempt.
    """
    treated = [abs(w.did) for w in windows if category in category_of(w.match_id)]
    control = [abs(w.did) for w in windows
               if not set(CATEGORIES) & set(category_of(w.match_id))]
    if len(treated) < 2 or len(control) < 2:
        return None

    def mean(xs):
        return sum(xs) / len(xs)

    def var(xs):
        m = mean(xs)
        return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)

    effect = mean(treated) - mean(control)
    se = math.sqrt(var(treated) / len(treated) + var(control) / len(control))
    z = effect / se if se > 0 else 0.0
    return DiDResult(
        category=category, n_treated=len(treated), n_control=len(control),
        treated_did=mean(treated), control_did=mean(control),
        effect=effect, se=se, z=z,
        p_value=math.erfc(abs(z) / math.sqrt(2.0)),
    )
