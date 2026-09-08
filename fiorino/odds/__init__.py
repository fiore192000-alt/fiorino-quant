"""
Odds processing (M2).

devig.py   overround removal, always on a complete market. Shin by default.
ingest.py  bronze odds -> observations -> closing line -> fair probabilities.

The governing rule: never invent a timestamp for an observation that has none.
`captured_at` is populated only for TIMESTAMPED rows; CLOSING and PREMATCH
record the bound that is genuinely known (the kickoff) and nothing more.
"""

from .devig import DEFAULT_METHOD, DevigResult, devig, overround
from .ingest import (
    OddsIngestResult,
    compute_fair_probabilities,
    ingest_odds,
    materialise_closing,
    run_odds_pipeline,
)

__all__ = [
    "devig",
    "overround",
    "DevigResult",
    "DEFAULT_METHOD",
    "ingest_odds",
    "materialise_closing",
    "compute_fair_probabilities",
    "run_odds_pipeline",
    "OddsIngestResult",
]
