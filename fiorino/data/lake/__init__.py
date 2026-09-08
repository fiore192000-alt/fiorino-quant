"""
Parquet bronze layer — the immutable landing zone.

Raw source payloads land here exactly as received, partitioned by
source / competition / season / ingestion run. Nothing is ever rewritten.

DuckDB (silver/gold) is derived from this and is fully rebuildable: if the
database is lost or the schema changes, the rebuild reconstructs it without
re-fetching a single byte from the network.

The rebuild guarantee is SEMANTIC, not physical: same records, same keys, same
values, same relations, same canonical ordering. DuckDB's on-disk
representation legitimately varies across versions and builds, so byte
equality is not something this layer promises.
"""

from .layout import BronzePath, bronze_path, source_glob
from .reader import list_bronze, read_bronze
from .writer import write_bronze

__all__ = [
    "BronzePath",
    "bronze_path",
    "source_glob",
    "write_bronze",
    "read_bronze",
    "list_bronze",
]
