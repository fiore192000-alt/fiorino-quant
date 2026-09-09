"""
The no-bet engine.

Most betting systems are built to produce bets and occasionally decline. This
one is built to decline and, one day, occasionally not.

That is not modesty. It is what the measurements say: across M5, M6 and the
situation scan, **no strategy has ever produced a positive out-of-sample CLV
that was not definitional**. Until one does, a display that shows "BET" would
be showing something the evidence does not support, and the display is the part
a person acts on.

THE CEILING
-----------
:data:`PROMOTED` is empty. While it is empty, :func:`classify` cannot return
anything above WATCH — not by convention, by construction, with a test that
fails if the ceiling is ever lifted without a promotion record.

This is the same shape as `require_timestamped`: a rule that refuses rather
than warns, put where it cannot be forgotten. A UI can be rewritten in an
afternoon; this cannot be worked around by rewriting a template.

THE BLACK BOX
-------------
Every decision carries the reasons that produced it, both the ones that argued
for and the ones that argued against. "The model likes it" is not a reason. A
reason names a measurement and a threshold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

__all__ = ["SignalLevel", "LEVELS", "Reason", "Decision", "classify",
           "promoted_strategies", "PROMOTED", "STALE_AFTER"]


class SignalLevel:
    """Four levels. There is deliberately no BET.

    A fifth level exists in the roadmap and does not exist in this code. Adding
    it is a decision that requires a promotion record, not a constant.
    """

    #: Not on the ladder. "I could not evaluate this" is not a weaker verdict
    #: than "I evaluated it and found nothing" — it is a different kind of
    #: statement, and putting it at the bottom of the same scale would let a
    #: missing price read as a measured absence of edge.
    DATA_GAP = "DATA_GAP"

    NO_SIGNAL = "NO_SIGNAL"
    WATCH = "WATCH"
    CANDIDATE = "CANDIDATE"
    QUALIFIED = "QUALIFIED"


#: Ordered weakest to strongest, so a ceiling is `min(level, ceiling)`.
LEVELS = (SignalLevel.NO_SIGNAL, SignalLevel.WATCH,
          SignalLevel.CANDIDATE, SignalLevel.QUALIFIED)

#: Strategies that have passed all six promotion gates.
#:
#: EMPTY, and that is the current state of the evidence rather than an
#: oversight. Filling it requires an experiment record showing positive
#: out-of-sample CLV, replicated across two leagues and two periods, that
#: survives the adversarial suite. See docs/research/PROMOTION_GATES.md.
PROMOTED: dict[str, dict] = {}

#: Beyond this, a price is not a price any more. Odds go stale fast near
#: kickoff, and a dashboard showing a two-hour-old number as current is worse
#: than one showing nothing.
STALE_AFTER = timedelta(minutes=30)

#: Below this, a sample cannot support a claim. Matches the backtest metrics
#: threshold, so the dashboard and the validation report agree.
MIN_SETTLED = 30


@dataclass(frozen=True)
class Reason:
    """One factor, and which way it pointed."""

    code: str
    detail: str
    #: True when it argued for a signal, False when against.
    supports: bool


@dataclass
class Decision:
    level: str
    reasons: list[Reason] = field(default_factory=list)
    #: The level the evidence alone would have supported, before the ceiling.
    uncapped_level: str = SignalLevel.NO_SIGNAL
    capped_by: str | None = None

    @property
    def blocking(self) -> list[Reason]:
        return [r for r in self.reasons if not r.supports]

    def explain(self) -> str:
        """The black box, in the form a person can check."""
        lines = [f"{self.level}"]
        if self.capped_by:
            lines.append(f"  evidenza: {self.uncapped_level} — limitato da {self.capped_by}")
        for reason in self.reasons:
            lines.append(f"  {'+' if reason.supports else '-'} {reason.code}: {reason.detail}")
        return "\n".join(lines)


def promoted_strategies() -> dict[str, dict]:
    return dict(PROMOTED)


def _ceiling() -> tuple[str, str | None]:
    if PROMOTED:
        return SignalLevel.QUALIFIED, None
    return SignalLevel.WATCH, (
        "nessuna strategia promossa: il CLV positivo fuori campione non è mai "
        "stato dimostrato (M5, M6, scansione situazioni)"
    )


def classify(
    *,
    edge: float | None,
    strategy: str | None = None,
    n_settled: int = 0,
    historical_clv: float | None = None,
    clv_t_stat: float | None = None,
    data_age: timedelta | None = None,
    pit_violations: int = 0,
    used_prior: bool = False,
    min_edge: float = 0.02,
    now: datetime | None = None,
) -> Decision:
    """Classify one opportunity, and say why.

    Order matters: the disqualifiers run first, so a stale price is reported as
    stale rather than as a small edge. A reader who stops at the first line
    should not be misled.
    """
    reasons: list[Reason] = []

    if pit_violations:
        reasons.append(Reason("PIT_VIOLATION",
                              f"{pit_violations} violazioni point-in-time nell'audit",
                              False))
        return Decision(SignalLevel.NO_SIGNAL, reasons)

    if data_age is not None and data_age > STALE_AFTER:
        minutes = int(data_age.total_seconds() // 60)
        reasons.append(Reason("STALE_DATA",
                              f"prezzo vecchio di {minutes} min (limite "
                              f"{int(STALE_AFTER.total_seconds() // 60)})", False))
        return Decision(SignalLevel.NO_SIGNAL, reasons)

    if edge is None:
        # DATA_GAP, not NO_SIGNAL. Without a price there is nothing to evaluate
        # against, and reporting that as "no signal" would assert a measurement
        # that was never made.
        reasons.append(Reason("NO_ODDS",
                              "nessuna quota disponibile: non valutabile, "
                              "che è diverso da valutato e senza vantaggio",
                              False))
        return Decision(SignalLevel.DATA_GAP, reasons)

    if edge <= min_edge:
        reasons.append(Reason("EDGE_BELOW_THRESHOLD",
                              f"EV {edge:+.4f} sotto la soglia {min_edge:+.4f}", False))
        return Decision(SignalLevel.NO_SIGNAL, reasons)

    reasons.append(Reason("EDGE", f"EV {edge:+.4f} sopra {min_edge:+.4f}", True))

    level = SignalLevel.WATCH

    if used_prior:
        reasons.append(Reason("LEAGUE_PRIOR",
                              "una delle due squadre non era nel training: "
                              "previsione da prior di lega", False))
    elif n_settled < MIN_SETTLED:
        reasons.append(Reason("THIN_SAMPLE",
                              f"{n_settled} scommesse regolate per questa classe "
                              f"di segnale (minimo {MIN_SETTLED})", False))
    elif historical_clv is None:
        reasons.append(Reason("NO_CLV_HISTORY",
                              "nessuna storia di CLV per questa classe di segnale",
                              False))
    elif historical_clv <= 0:
        # Not WATCH. A negative CLV history is evidence AGAINST, not absence of
        # evidence, and the two must not share a colour on a screen. M6 found
        # model_edge negative in 30 cases out of 30: showing all of those as
        # "watch" would fill the dashboard with things already disproved.
        reasons.append(Reason("NEGATIVE_CLV",
                              f"CLV storico {historical_clv:+.4f}"
                              + (f", t={clv_t_stat:+.1f}" if clv_t_stat is not None else "")
                              + " — questa classe di segnale ha gia perso contro la chiusura",
                              False))
        return Decision(SignalLevel.NO_SIGNAL, reasons)
    else:
        reasons.append(Reason("POSITIVE_CLV",
                              f"CLV storico {historical_clv:+.4f}"
                              + (f", t={clv_t_stat:+.1f}" if clv_t_stat is not None else ""),
                              True))
        level = SignalLevel.CANDIDATE
        if strategy in PROMOTED:
            reasons.append(Reason("PROMOTED",
                                  f"la strategia {strategy} ha superato tutti i gate",
                                  True))
            level = SignalLevel.QUALIFIED

    ceiling, capped_by = _ceiling()
    final = LEVELS[min(LEVELS.index(level), LEVELS.index(ceiling))]
    if final != level:
        reasons.append(Reason("NOT_PROMOTED", capped_by, False))
    return Decision(final, reasons, uncapped_level=level,
                    capped_by=capped_by if final != level else None)
