"""
Team and competition identity resolution.

Every external name maps to a stable surrogate team_id via team_aliases.
The resolver proposes fuzzy matches with a confidence score; unverified
proposals are quarantined rather than silently accepted, because one bad
alias silently corrupts every join downstream.
"""
