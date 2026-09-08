"""
DuckDB bootstrap and migrations.

schema.sql   — the DDL. Read it before changing anything here.
views.sql    — derived views plus the point-in-time macros.
connection.py— connection factory, pragmas, schema version check.
migrations/  — numbered forward-only migrations.
"""
