"""Signal classification. The part of the system whose job is to say no."""

from .signal import (
    LEVELS,
    Decision,
    Reason,
    SignalLevel,
    classify,
    promoted_strategies,
)

__all__ = ["SignalLevel", "LEVELS", "Reason", "Decision", "classify",
           "promoted_strategies"]
