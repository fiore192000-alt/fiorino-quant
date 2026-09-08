"""
Team identity resolution.

Every external name maps to a stable, opaque ``team_id``. The precedence
ladder is: human override, exact raw + source, exact normalized + country,
fuzzy (proposal only), unresolved (pipeline blocks).

Rule 9 is absolute: a fuzzy match never feeds the analytic dataset. Proposals
sit in quarantine until a human decides, and any match referencing an
unapproved identity is held out of `matches` entirely.
"""

from .audit import Finding, run_identity_audit
from .normalize import normalize_team_name, tokenize
from .overrides import add_override, list_overrides
from .resolver import IdentityResolver, MatchMethod, Resolution

__all__ = [
    "IdentityResolver",
    "MatchMethod",
    "Resolution",
    "normalize_team_name",
    "tokenize",
    "add_override",
    "list_overrides",
    "run_identity_audit",
    "Finding",
]
