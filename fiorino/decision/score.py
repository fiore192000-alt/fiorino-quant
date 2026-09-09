"""
Signal quality, which is not the same thing as edge size.

A +30% edge on nine bets should score below a +2% edge on six thousand, and an
arithmetic average of components cannot express that: it lets a large edge buy
back a missing sample. So the score has two kinds of component.

    GATES        pass or fail, multiplied in. A zero anywhere zeroes the score.
                 Point-in-time confidence, data freshness, execution
                 feasibility. These are not qualities a signal can have "some
                 of" — a stale price is not a slightly worse price, it is not a
                 price.

    GRADED       a weighted mean. Edge, CLV, sample, replication, liquidity,
                 model uncertainty, adversarial robustness. Here more really is
                 better, and one weak component can be offset.

    score = (product of gates) x (weighted mean of graded)

The shape is the argument. Anything that averages a gate with a grade will,
sooner or later, recommend a bet on a two-hour-old price because the edge
looked big.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

__all__ = ["SignalScore", "score_signal", "GRADED_WEIGHTS", "GATES"]

#: Relative importance of the graded components. CLV outweighs edge on purpose:
#: M4 measured the CLV verdict correct 30 times out of 30 and the yield verdict
#: 23 out of 30, and edge is closer in kind to yield than to CLV.
GRADED_WEIGHTS = {
    "clv": 0.30,
    "replication": 0.25,
    "sample": 0.20,
    "edge": 0.10,
    "adversarial": 0.10,
    "liquidity": 0.05,
}

GATES = ("pit_confidence", "freshness", "execution")


def _clamp(x: float) -> float:
    return min(max(float(x), 0.0), 1.0)


@dataclass
class SignalScore:
    #: None when the signal could not be scored at all.
    #:
    #: This is NOT zero, and the difference is the whole point. Zero means
    #: "evaluated, and found no advantage". None means "could not evaluate".
    #: Collapsing them turns a missing price into a measured absence of edge,
    #: which is a falsification: the system would be claiming to have looked.
    value: float | None
    gates: dict[str, float] = field(default_factory=dict)
    graded: dict[str, float] = field(default_factory=dict)
    #: Which gate, if any, collapsed the score. The most useful single field:
    #: a score of zero is not informative, the reason for it is.
    failed_gate: str | None = None
    #: Why it could not be scored. Set exactly when value is None.
    data_gap: str | None = None

    @property
    def scorable(self) -> bool:
        return self.value is not None

    @property
    def weakest(self) -> str | None:
        if self.failed_gate:
            return self.failed_gate
        if not self.graded:
            return None
        return min(self.graded, key=self.graded.get)

    def explain(self) -> list[tuple[str, float, str]]:
        """(component, value, kind), worst first — the order a reader needs."""
        if not self.scorable:
            return []
        rows = [(k, v, "gate") for k, v in self.gates.items()]
        rows += [(k, v, "graded") for k, v in self.graded.items()]
        return sorted(rows, key=lambda r: r[1])


def score_signal(
    *,
    price: float | None = None,
    edge: float | None = None,
    historical_clv: float | None = None,
    n_settled: int = 0,
    replications: int = 0,
    replications_required: int = 2,
    data_age: timedelta | None = None,
    stale_after: timedelta = timedelta(minutes=30),
    pit_violations: int = 0,
    liquidity: float | None = None,
    adversarial_passed: int = 0,
    adversarial_total: int = 10,
    executable: bool = True,
) -> SignalScore:
    """Score one opportunity in [0, 1].

    Returns a score with ``value is None`` when there is no price to evaluate
    against. That case is a DATA GAP and must never be rendered as zero: zero
    says the opportunity was assessed and found worthless, which would be a
    claim the system has not earned.

    Every component saturates. A CLV of +20% does not score twice a CLV of
    +10%: past a plausible ceiling, a larger number is more likely to be a
    small sample than a bigger edge, and letting it dominate would reward
    exactly the wrong thing.
    """
    if price is None and edge is None:
        return SignalScore(value=None, data_gap="NO_ODDS")
    gates = {
        "pit_confidence": 0.0 if pit_violations else 1.0,
        "freshness": 0.0 if (data_age is not None and data_age > stale_after) else 1.0,
        "execution": 1.0 if executable else 0.0,
    }
    failed = next((name for name, v in gates.items() if v == 0.0), None)

    graded = {
        # 5% is treated as a full score. Above that, a bigger number on this
        # data means a bigger model error far more often than a bigger edge:
        # M5 found 1,037 selections claiming over 5% from a model that loses
        # to the close in every dataset.
        "edge": _clamp((edge or 0.0) / 0.05),
        # +3% CLV is an excellent result in this market. Nothing observed in
        # this project has come close.
        "clv": _clamp(((historical_clv or 0.0)) / 0.03),
        # 500 settled bets is where a CLV t-stat starts to mean something.
        "sample": _clamp(n_settled / 500.0),
        "replication": _clamp(replications / max(replications_required, 1)),
        "adversarial": _clamp(adversarial_passed / max(adversarial_total, 1)),
        # None, not 1.0. An unknown component must not count as a perfect one:
        # that silently inflates every score by the weight of whatever we
        # happen not to measure, and liquidity is never measured today.
        "liquidity": None if liquidity is None else _clamp(liquidity),
    }

    gate_product = 1.0
    for value in gates.values():
        gate_product *= value

    # Unknown components are EXCLUDED and the weights renormalised over what
    # is actually known. Imputing a value would be inventing a measurement.
    known = {k: v for k, v in graded.items() if v is not None}
    total_weight = sum(GRADED_WEIGHTS[k] for k in known)
    if total_weight <= 0:
        return SignalScore(value=None, data_gap="NO_COMPONENTS_KNOWN")
    weighted = sum(GRADED_WEIGHTS[k] * known[k] for k in known) / total_weight

    return SignalScore(value=gate_product * weighted, gates=gates,
                       graded=known, failed_gate=failed)
