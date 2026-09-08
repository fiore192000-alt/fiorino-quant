"""
Where data lives — deliberately not in the git repository.

    repository            data root  ($FIORINO_DATA_ROOT)
    ├── fiorino/          ├── bronze/      immutable raw partitions
    ├── test/fixtures/    ├── manifests/   dataset versions + HEAD
    ├── migrations/       └── warehouse/   rebuilt DuckDB files
    └── .github/

The repository holds code, schema, configuration and the few tiny bronze
fixtures the offline test suite needs. Everything else is a dataset, and a
dataset in git is a git repository slowly turning into a bad database: every
daily refresh is a commit, history is unprunable, and a clone eventually costs
gigabytes to obtain code that is measured in kilobytes.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["data_root", "bronze_root", "manifest_root", "warehouse_root", "ENV_VAR"]

ENV_VAR = "FIORINO_DATA_ROOT"

#: Used when the variable is unset. Outside the repository on purpose: a
#: default that lands inside the working tree is a default that ends up
#: committed by somebody in a hurry.
DEFAULT_ROOT = Path.home() / ".fiorino" / "data"


def data_root(override=None) -> Path:
    """Root of the dataset tree.

    Local paths today. The layout is storage-agnostic: DuckDB reads and writes
    Parquet over s3:// and gs:// through httpfs, so moving the root to object
    storage changes this function and nothing else.
    """
    if override:
        return Path(override)
    configured = os.environ.get(ENV_VAR)
    return Path(configured) if configured else DEFAULT_ROOT


def bronze_root(override=None) -> Path:
    return data_root(override) / "bronze"


def manifest_root(override=None) -> Path:
    return data_root(override) / "manifests"


def warehouse_root(override=None) -> Path:
    return data_root(override) / "warehouse"
