"""DuckDB connection factory and schema-version guard."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import duckdb

__all__ = ["connect", "open_db", "SCHEMA_VERSION"]

#: Highest migration this build knows about. A database ahead of this was
#: written by newer code and must not be opened read-write.
SCHEMA_VERSION = 5


def connect(path: str | Path | None = None, *, read_only: bool = False):
    """Open a DuckDB connection. ``None`` gives an in-memory database."""
    target = ":memory:" if path is None else str(path)
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(target, read_only=read_only)
    con.execute("SET TimeZone='UTC'")
    return con


@contextmanager
def open_db(path: str | Path | None = None, *, read_only: bool = False) -> Iterator:
    con = connect(path, read_only=read_only)
    try:
        yield con
    finally:
        con.close()


def installed_version(con) -> int:
    """Highest applied migration, or 0 on a database with no schema."""
    tables = con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'schema_migrations'"
    ).fetchall()
    if not tables:
        return 0
    row = con.execute("SELECT max(version) FROM schema_migrations").fetchone()
    return int(row[0]) if row and row[0] is not None else 0
