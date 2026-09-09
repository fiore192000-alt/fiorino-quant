"""Hypothesis generation and scanning. Phase 2 to phase 6, automated."""

from .hypotheses import HYPOTHESES, Hypothesis, label_matches
from .scan import ScanResult, benjamini_hochberg, scan

__all__ = ["HYPOTHESES", "Hypothesis", "label_matches", "scan", "ScanResult",
           "benjamini_hochberg"]
