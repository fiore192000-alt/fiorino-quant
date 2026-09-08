"""
Cohort-level allocation.

allocator.py   — chooses stakes for all candidates in one cohort jointly,
                 maximising expected log growth subject to per-bet, per-
                 fixture and per-cohort exposure caps.
correlation.py — bets on the SAME fixture are functions of the same
                 scoreline and are not independent. Their joint growth is
                 evaluated exactly over the score grid rather than assumed
                 additive. Across fixtures, independence is assumed.
"""
