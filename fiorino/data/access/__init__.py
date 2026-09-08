"""
Point-in-time repositories — the enforcement point for schema rule R1.

point_in_time.py — PointInTimeView(as_of): the ONLY sanctioned reader for
                   strategy and backtest code. Every method it exposes is
                   bounded by as_of.
repositories.py  — unbounded readers, for ingestion and reporting only.

A test asserts that no module under fiorino/strategy or fiorino/backtest
imports repositories or names a raw table. That test is the difference
between a backtest and a fantasy.
"""
