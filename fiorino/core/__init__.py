"""
Primitives shared by every layer. Depends on nothing inside fiorino.

types.py    — MarketType, Selection, Price, Probability, FixtureRef.
ids.py      — deterministic id derivation (fixture_id, bet_id, market_key);
              re-ingesting the same fact must yield the same id.
money.py    — Decimal money arithmetic; floats never touch a stake or a P&L.
markets.py  — the (market_type, line, selection) vocabulary and the
              home-perspective normalisation rule (schema rule R3).
errors.py   — the exception hierarchy.
"""
