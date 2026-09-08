"""
Odds processing.

devig.py      — overround removal (Shin by default; penaltyblog.implied
                supplies the implementations). Operates on a complete
                market, never on a single selection.
closing.py    — materialises odds_closing: the last snapshot strictly before
                kickoff per key, with a staleness gate (is_trusted).
best_price.py — best available price across the books you actually hold.
"""
