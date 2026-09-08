"""
Closing Line Value — the primary edge signal.

compute.py — scores each bet against the REFERENCE book's de-vigged close
             for the identical (market_type, line, selection):
               clv_price = price_taken / closing_price - 1
               clv_ev    = closing_fair_prob * price_taken - 1   <- headline
               clv_log   = ln(closing_fair_prob * price_taken)
report.py  — rollups and the CLV t-stat.

Why this module exists: CLV converges on the truth in hundreds of bets;
P&L needs thousands. A strategy with negative CLV and positive P&L is
lucky, and knowing that early is worth more than the P&L.
"""
