"""
The identity ledger — human decisions, persisted apart from derived data.

A correction to an earlier assumption in this design. "Rebuild from bronze
reproduces the dataset" is FALSE as stated: the same bronze adjudicated
differently produces a different dataset. Bronze is raw input; the identity
decisions taken over it are a SECOND input, and they are not derived from
anything, so nothing can regenerate them.

    bronze  +  identity ledger  ->  silver/gold

That changes where things live:

    bronze          bulk, megabytes a day, machine-generated  -> data storage
    identity ledger curated, kilobytes, human-authored        -> git

The ledger belongs in the repository for the same reason migrations do: it is
a small, reviewable record of decisions, and losing it means re-adjudicating
every club by hand. It is exported as sorted JSON so a diff shows exactly which
identity call changed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

__all__ = ["export_ledger", "import_ledger", "ledger_digest", "LEDGER_TABLES", "LEDGER_SORT_KEYS"]

#: What is genuinely human input. `team_source_ids` and
#: `team_season_membership` are excluded on purpose: both are derived from
#: bronze and would be regenerated identically anyway.
LEDGER_TABLES = {
    "teams": ("team_id", "canonical_name", "country"),
    "team_aliases": (
        "alias_raw", "source", "country", "alias_normalized", "team_id",
        "match_method", "confidence", "status",
    ),
    "team_identity_overrides": (
        "override_id", "alias_raw", "source", "country", "team_id", "reason", "created_by",
    ),
    "team_alias_proposals": (
        "proposal_id", "alias_raw", "source", "country", "alias_normalized",
        "candidate_team_id", "score", "method", "status", "decided_by", "decision_note",
    ),
}

#: How each table is ordered on export. Deliberately NOT the column order:
#: `teams` would then sort by `team_id`, a random surrogate, so the file would
#: reshuffle on every rebuild and the diff — the entire reason this lives in
#: git — would be unreadable. Sort by what a human recognises.
LEDGER_SORT_KEYS = {
    "teams": ("canonical_name", "country"),
    "team_aliases": ("country", "source", "alias_raw"),
    "team_identity_overrides": ("country", "alias_raw", "source"),
    "team_alias_proposals": ("country", "alias_raw", "source"),
}


def _dump(con) -> dict:
    payload: dict[str, list] = {}
    for table, columns in LEDGER_TABLES.items():
        listed = ", ".join(columns)
        order = ", ".join(LEDGER_SORT_KEYS.get(table, columns))
        rows = con.execute(f"SELECT {listed} FROM {table} ORDER BY {order}").fetchall()
        payload[table] = [
            {c: (v if not hasattr(v, "isoformat") else v.isoformat())
             for c, v in zip(columns, row)}
            for row in rows
        ]
    return payload


def export_ledger(con, path) -> Path:
    """Write the ledger as sorted, diffable JSON."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_dump(con), indent=2, sort_keys=True) + "\n")
    return target


def import_ledger(con, path) -> dict[str, int]:
    """Load a ledger into a migrated, empty-identity database.

    Insert order matters: `teams` first, because everything else has a foreign
    key into it.
    """
    payload = json.loads(Path(path).read_text())
    counts: dict[str, int] = {}
    for table in ("teams", "team_aliases", "team_identity_overrides", "team_alias_proposals"):
        rows = payload.get(table, [])
        if not rows:
            counts[table] = 0
            continue
        columns = list(LEDGER_TABLES[table])
        placeholders = ", ".join("?" for _ in columns)
        con.executemany(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            [[row.get(c) for c in columns] for row in rows],
        )
        counts[table] = len(rows)
    return counts


def ledger_digest(con=None, path=None) -> str:
    """Content hash of the identity decisions.

    Recorded in the dataset manifest alongside the bronze hashes, because a
    dataset version is only reproducible if BOTH inputs are pinned.
    """
    if (con is None) == (path is None):
        raise ValueError("pass exactly one of con or path")
    payload = _dump(con) if con is not None else json.loads(Path(path).read_text())
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.blake2b(canonical.encode(), digest_size=8).hexdigest()
