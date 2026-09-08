"""Write raw rows into bronze. Append-only; an existing file is never touched."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .layout import BronzePath

__all__ = ["write_bronze"]


def write_bronze(con, rows: Sequence[dict], target: BronzePath) -> Path:
    """Persist ``rows`` as one immutable Parquet file.

    Values are stored as text. Bronze records what the source said, not what we
    think it meant; parsing and typing belong to the silver transform, where a
    mistake can be corrected by rebuilding rather than by re-fetching.
    """
    if not rows:
        raise ValueError("refusing to write an empty bronze file")

    path = target.file
    if path.exists():
        raise FileExistsError(
            f"bronze is immutable and {path.name} already exists; "
            "start a new ingestion run instead"
        )

    columns = list(rows[0].keys())
    for i, row in enumerate(rows):
        if list(row.keys()) != columns:
            raise ValueError(f"bronze row {i} has columns inconsistent with the file")

    path.parent.mkdir(parents=True, exist_ok=True)
    col_defs = ", ".join(f'"{c}" VARCHAR' for c in columns)

    con.execute("DROP TABLE IF EXISTS _bronze_stage")
    con.execute(f"CREATE TEMP TABLE _bronze_stage ({col_defs})")
    try:
        con.executemany(
            f"INSERT INTO _bronze_stage VALUES ({', '.join('?' for _ in columns)})",
            [[None if row[c] is None else str(row[c]) for c in columns] for row in rows],
        )
        con.execute(f"COPY _bronze_stage TO '{path}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    finally:
        con.execute("DROP TABLE IF EXISTS _bronze_stage")
    return path
