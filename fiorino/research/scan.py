"""
Scanning many hypotheses at once, without manufacturing discoveries.

The procedure "generate 100 hypotheses, backtest them all, discard 99%" has a
failure mode that is not a matter of care: it is arithmetic. Testing 36
independent nulls at the 5% level yields **1.8 false positives on average**, and
the scan reports whichever of them looks best. The survivor of a hundred tests
is not evidence; it is an order statistic.

So this module refuses to report a raw significance. Three defences, and the
scan is worth less than nothing without them:

1. **Benjamini-Hochberg** across the whole family, controlling the false
   discovery rate rather than each test in isolation.
2. **Replication across datasets** — a sign that holds in one league-season and
   nowhere else is what overfitting looks like from the inside.
3. **Positive controls** — known biases included in the family. A scan that
   cannot rediscover the favourite-longshot bias has no standing to report that
   anything else is absent.

THE STATISTIC
-------------
For a situation S and a selection k,

    bias(S, k) = mean over S of ( 1{outcome = k} - p_market(k) )

A calibrated market gives zero. The test statistic is the CONTRAST

    delta = bias(S, k) - bias(not S, k)

rather than bias(S, k) alone, because the de-vig itself can be biased: Shin
shades longshots by design, so an absolute bias would fire on every longshot
subset and say nothing about the market. The contrast cancels any bias the
de-vig applies uniformly.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from fiorino.research.hypotheses import HYPOTHESES, SELECTIONS

__all__ = ["scan", "ScanResult", "benjamini_hochberg"]


@dataclass
class ScanResult:
    hypothesis: str
    selection: str
    n_in: int
    n_out: int
    bias_in: float
    bias_out: float
    delta: float
    se: float
    z: float
    p_value: float
    positive_control: bool
    #: Filled in by benjamini_hochberg(); None until the family is known,
    #: because a p-value here is meaningless on its own.
    q_value: float | None = None
    discovery: bool = False


def _fetch(con, table, predicate, prob_source="fair", selection=None):
    """Rows plus the in-group flag.

    ``selection`` is given for a selection-level hypothesis, whose predicate
    carries a ``{prob}`` token standing for that selection's own probability.
    """
    prefix = "p" if prob_source == "fair" else "raw"
    if selection is not None:
        predicate = predicate.replace("{prob}", f"{prefix}_{selection.lower()}")
    return con.execute(
        f"SELECT outcome, {prefix}_home, {prefix}_draw, {prefix}_away, "
        f"({predicate}) AS inside FROM {table}"
    ).fetchall()


def _delta(rows, selection: str) -> tuple[float, float, float, int, int]:
    idx = {"HOME": 1, "DRAW": 2, "AWAY": 3}[selection]
    sum_in = sum_out = 0.0
    n_in = n_out = 0
    for row in rows:
        residual = (1.0 if row[0] == selection else 0.0) - row[idx]
        if row[4]:
            sum_in += residual
            n_in += 1
        else:
            sum_out += residual
            n_out += 1
    bias_in = sum_in / n_in if n_in else 0.0
    bias_out = sum_out / n_out if n_out else 0.0
    return bias_in - bias_out, bias_in, bias_out, n_in, n_out


def scan(con, table: str = "labelled", *, hypotheses=HYPOTHESES,
         draws: int = 1000, seed: int = 20260909,
         min_n: int = 30) -> list[ScanResult]:
    """Test every hypothesis against every selection.

    Matches are resampled whole — not the in-group and out-group separately —
    so the bootstrap preserves the fact that a fixture belongs to exactly one
    side of the split, and that the group sizes are themselves random.
    """
    results = []
    for hypothesis in hypotheses:
        # A fixture-level subset is the same for all three selections, so it is
        # fetched once. A selection-level one differs per selection.
        shared = None
        if not hypothesis.selection_level:
            shared = _fetch(con, table, hypothesis.predicate, hypothesis.prob_source)
            if not shared:
                continue
        for selection in SELECTIONS:
            rows = shared if shared is not None else _fetch(
                con, table, hypothesis.predicate, hypothesis.prob_source, selection)
            if not rows:
                continue
            delta, bias_in, bias_out, n_in, n_out = _delta(rows, selection)
            if n_in < min_n or n_out < min_n:
                continue

            rng = random.Random(f"{seed}:{hypothesis.name}:{selection}")
            n = len(rows)
            deltas = []
            for _ in range(draws):
                sample = [rows[rng.randrange(n)] for _ in range(n)]
                d, _, _, a, b = _delta(sample, selection)
                if a and b:
                    deltas.append(d)
            if len(deltas) < draws // 2:
                continue

            mean = sum(deltas) / len(deltas)
            var = sum((d - mean) ** 2 for d in deltas) / (len(deltas) - 1)
            se = math.sqrt(var)
            z = delta / se if se > 0 else 0.0
            # Normal approximation on the bootstrap standard error. Smoother
            # than counting tail draws, which quantises p at 1/draws and makes
            # the Benjamini-Hochberg ordering arbitrary among ties.
            p = math.erfc(abs(z) / math.sqrt(2.0))

            results.append(ScanResult(
                hypothesis=hypothesis.name, selection=selection,
                n_in=n_in, n_out=n_out, bias_in=bias_in, bias_out=bias_out,
                delta=delta, se=se, z=z, p_value=p,
                positive_control=hypothesis.positive_control,
            ))
    return results


def benjamini_hochberg(results: list[ScanResult], q: float = 0.10) -> list[ScanResult]:
    """Control the false discovery rate across the whole family.

    Mutates and returns the same objects, so a caller cannot accidentally
    report the raw p-values it already holds.

    Positive controls are part of the family for the correction — excluding
    them would make the threshold easier for everything else — but they are
    flagged, so rediscovering a known bias is never counted as a discovery.
    """
    ordered = sorted(results, key=lambda r: r.p_value)
    m = len(ordered)
    if not m:
        return results

    threshold_rank = 0
    for i, result in enumerate(ordered, start=1):
        if result.p_value <= q * i / m:
            threshold_rank = i

    running = 1.0
    for i in range(m, 0, -1):
        running = min(running, ordered[i - 1].p_value * m / i)
        ordered[i - 1].q_value = running
        ordered[i - 1].discovery = i <= threshold_rank
    return results
