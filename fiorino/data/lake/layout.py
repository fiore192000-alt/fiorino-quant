"""Bronze path convention.

    <root>/raw/source=<source>/competition=<comp>/season=<season>/run=<run_id>.parquet

Hive-style, so DuckDB can read a whole source, competition or season with one
glob and recover the partition keys as columns.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["BronzePath", "bronze_path", "source_glob", "RAW_PREFIX"]

RAW_PREFIX = "raw"


@dataclass(frozen=True)
class BronzePath:
    root: Path
    source: str
    competition_id: str
    season_id: str
    ingestion_run_id: str

    @property
    def directory(self) -> Path:
        return (
            Path(self.root)
            / RAW_PREFIX
            / f"source={self.source}"
            / f"competition={self.competition_id}"
            / f"season={self.season_id}"
        )

    @property
    def file(self) -> Path:
        return self.directory / f"run={self.ingestion_run_id}.parquet"


def bronze_path(root, source, competition_id, season_id, ingestion_run_id) -> BronzePath:
    return BronzePath(Path(root), source, competition_id, season_id, ingestion_run_id)


def source_glob(root, source="*", competition_id="*", season_id="*") -> str:
    return str(
        Path(root)
        / RAW_PREFIX
        / f"source={source}"
        / f"competition={competition_id}"
        / f"season={season_id}"
        / "*.parquet"
    )
