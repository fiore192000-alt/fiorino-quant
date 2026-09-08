"""
Bet sizing.

kelly.py     — Kelly with push. For win/push/lose the growth-optimal
                fraction has a closed form:
                    f* = (p_win*b - p_lose) / (b * (p_win + p_lose))
                which reduces to standard Kelly when p_push = 0. Quarter
                lines (half-win/half-lose) need the numeric solve.
shrinkage.py — penalises the edge by its own estimation error,
                edge_used = max(0, edge - k * sigma_edge), before any
                fraction is applied. Kelly on an over-estimated edge is
                how bankrolls die.
"""
