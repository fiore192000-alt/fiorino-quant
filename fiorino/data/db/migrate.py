"""
Forward-only migration runner.

Migrations are numbered SQL files applied in order and recorded with a
checksum. Re-applying is a no-op; a file that changed after being applied is a
hard error, because a silently edited migration means two databases built from
the same repository are no longer the same database.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .connection import connect, installed_version

__all__ = ["Migration", "discover", "migrate", "MIGRATIONS_DIR"]

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_NAME_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text()

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode()).hexdigest()[:16]


def discover(directory: Path | None = None) -> list[Migration]:
    """All migrations on disk, ordered, with gaps and duplicates rejected."""
    directory = directory or MIGRATIONS_DIR
    found: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        m = _NAME_RE.match(path.name)
        if not m:
            raise ValueError(f"malformed migration filename: {path.name}")
        found.append(Migration(int(m.group(1)), m.group(2), path))

    versions = [f.version for f in found]
    if len(set(versions)) != len(versions):
        raise ValueError(f"duplicate migration versions: {versions}")
    if versions and versions != list(range(1, len(versions) + 1)):
        raise ValueError(f"migration versions must be contiguous from 1: {versions}")
    return found


def migrate(con, directory: Path | None = None, *, target: int | None = None) -> list[int]:
    """Apply every pending migration. Returns the versions applied."""
    migrations = discover(directory)
    current = installed_version(con)

    # Views are CREATE OR REPLACE, so re-running them on an up-to-date database
    # is safe and keeps derived objects in step with the code.
    applied: list[int] = []
    for mig in migrations:
        if target is not None and mig.version > target:
            break
        if mig.version <= current:
            _verify_checksum(con, mig)
            continue
        con.execute("BEGIN")
        try:
            con.execute(mig.sql)
            con.execute(
                "INSERT INTO schema_migrations (version, name, checksum) VALUES (?, ?, ?)",
                [mig.version, mig.name, mig.checksum],
            )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        applied.append(mig.version)
    return applied


def _verify_checksum(con, mig: Migration) -> None:
    row = con.execute(
        "SELECT checksum FROM schema_migrations WHERE version = ?", [mig.version]
    ).fetchone()
    if row and row[0] != mig.checksum:
        raise RuntimeError(
            f"migration {mig.version}_{mig.name} changed after being applied "
            f"(recorded {row[0]}, on disk {mig.checksum}). Add a new migration "
            f"instead of editing an applied one."
        )


def bootstrap(path=None, directory: Path | None = None):
    """Open a database and bring it fully up to date."""
    con = connect(path)
    migrate(con, directory)
    return con
