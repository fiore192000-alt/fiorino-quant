"""Hypothesis generation, scanning, and the lineup event study."""

from .event_study import (
    CATEGORIES,
    Category,
    difference_in_differences,
    formation_shock,
    measure_windows,
    require_timestamped,
)
from .hypotheses import HYPOTHESES, Hypothesis, label_matches
from .scan import ScanResult, benjamini_hochberg, scan

__all__ = [
    "HYPOTHESES", "Hypothesis", "label_matches",
    "scan", "ScanResult", "benjamini_hochberg",
    "Category", "CATEGORIES", "formation_shock", "require_timestamped",
    "measure_windows", "difference_in_differences",
]
