"""Read back from bronze."""

from __future__ import annotations

from pathlib import Path

from .layout import RAW_PREFIX, source_glob

__all__ = ["read_bronze", "list_bronze"]


def read_bronze(con, root, source="*", competition_id="*", season_id="*") -> list[dict]:
    """Bronze rows matching the partition filters, in canonical order.

    Deterministic ordering is not cosmetic: the rebuild guarantee requires that
    the same bronze produces the same silver, and insertion order affects which
    source wins a first-writer-wins conflict.
    """
    if not list_bronze(root):
        return []
    pattern = source_glob(root, source, competition_id, season_id)
    rel = con.execute(
        f"SELECT * FROM read_parquet('{pattern}', hive_partitioning=true, union_by_name=true)"
    )
    columns = [d[0] for d in rel.description]
    rows = [dict(zip(columns, r)) for r in rel.fetchall()]
    rows.sort(key=_canonical_key)
    return rows


def _canonical_key(row: dict):
    return (
        str(row.get("source", "")),
        str(row.get("competition", "")),
        str(row.get("season", "")),
        str(row.get("source_id", "")),
    )


def list_bronze(root) -> list[Path]:
    return sorted(Path(root).glob(f"{RAW_PREFIX}/**/*.parquet"))
