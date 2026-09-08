"""
Source adapters. Each writes to exactly one table family and is
idempotent: re-running an ingest for a period must not create duplicate rows.

Every adapter records the instant a fact became knowable (captured_at /
settled_at). An adapter that cannot supply that timestamp is not admissible.
"""
