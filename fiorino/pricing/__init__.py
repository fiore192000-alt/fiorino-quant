"""
One probability grid per fixture -> a coherent price for every market.

grid.py    — builds a penaltyblog FootballProbabilityGrid from model output.
markets.py — projects the grid onto (market_type, line, selection) rows that
             join directly to odds_snapshots, carrying prob_win / prob_push /
             prob_lose. Push is not optional: integer AH and totals lines are
             mispriced without it.
"""
