"""
Typed settings and registries.

settings.py    — Pydantic settings: db path, sources, credentials, run params.
registries.py  — competition, bookmaker and market registries loaded into the
                 reference tables at bootstrap.

Nothing else in the codebase reads environment variables directly.
"""
