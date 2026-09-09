"""Signal classification and scoring. The part of the system whose job is to say no."""

from .score import GATES, GRADED_WEIGHTS, SignalScore, score_signal
from .signal import (
    LEVELS,
    Decision,
    Reason,
    SignalLevel,
    classify,
    promoted_strategies,
)

__all__ = ["SignalLevel", "LEVELS", "Reason", "Decision", "classify",
           "promoted_strategies", "SignalScore", "score_signal",
           "GRADED_WEIGHTS", "GATES"]
