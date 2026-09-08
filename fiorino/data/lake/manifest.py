"""
Dataset versioning.

A dataset version is a CONTENT HASH over the exact set of bronze files that
produced it. Not a timestamp, not a counter: the same bronze content always
yields the same version, and a different version always means different inputs.

    ds_20260908_4f1a9c2b7e03
       └ date  └ blake2b over sorted "relpath:sha256" lines

That gives the four properties the pipeline needs:

  identify   a version names exactly which raw inputs were used
  rebuild    reading only the listed files reproduces that dataset, even after
             newer files have landed in bronze
  rollback   older manifests stay reconstructible for ever, because bronze is
             append-only and nothing is ever rewritten
  verify     `logical_digest` fingerprints the resulting silver/gold tables, so
             a rebuild can be proven equivalent without claiming byte equality
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "BronzeFile",
    "ledger_path_for",
    "DatasetManifest",
    "scan_bronze",
    "build_manifest",
    "save_manifest",
    "load_manifest",
    "list_versions",
    "read_head",
    "write_head",
    "verify_integrity",
    "HEAD_FILE",
]

HEAD_FILE = "HEAD"
_CHUNK = 1 << 20


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class BronzeFile:
    """One immutable bronze partition, identified by content."""

    path: str          # POSIX-relative to the bronze root
    sha256: str
    bytes: int
    source: str = ""
    competition: str = ""
    season: str = ""
    run_id: str = ""

    @classmethod
    def from_path(cls, path: Path, bronze_root: Path) -> "BronzeFile":
        rel = path.relative_to(bronze_root)
        parts = {
            piece.split("=", 1)[0]: piece.split("=", 1)[1]
            for piece in rel.parts
            if "=" in piece
        }
        return cls(
            path=rel.as_posix(),
            sha256=_sha256(path),
            bytes=path.stat().st_size,
            source=parts.get("source", ""),
            competition=parts.get("competition", ""),
            season=parts.get("season", ""),
            run_id=path.stem.split("=", 1)[-1] if "=" in path.stem else path.stem,
        )


@dataclass(frozen=True)
class DatasetManifest:
    dataset_version: str
    created_at: str
    files: tuple[BronzeFile, ...]
    parent_version: str | None = None
    code_version: str | None = None
    #: Hash of the identity ledger used. A dataset version pins BOTH inputs:
    #: the same bronze adjudicated differently is a different dataset, so a
    #: manifest that named only the bronze would not be reproducible.
    identity_digest: str | None = None
    #: Fingerprint of the silver/gold tables built from these files. Present
    #: once a rebuild has been run and verified.
    logical_digest: str | None = None
    audit_status: str | None = None
    n_blocking: int | None = None
    note: str | None = None

    @property
    def total_bytes(self) -> int:
        return sum(f.bytes for f in self.files)

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(sorted({f.source for f in self.files if f.source}))

    def to_json(self) -> str:
        payload = asdict(self)
        payload["files"] = [asdict(f) for f in self.files]
        return json.dumps(payload, indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "DatasetManifest":
        payload = json.loads(text)
        payload["files"] = tuple(BronzeFile(**f) for f in payload["files"])
        return cls(**payload)


def scan_bronze(bronze_root) -> tuple[BronzeFile, ...]:
    """Every bronze partition, hashed, in canonical path order."""
    root = Path(bronze_root)
    if not root.exists():
        return ()
    files = sorted(root.rglob("*.parquet"), key=lambda p: p.relative_to(root).as_posix())
    return tuple(BronzeFile.from_path(p, root) for p in files)


def compute_version(files, created: datetime | None = None, identity_digest=None) -> str:
    """Content-addressed version id over BOTH inputs.

    The date prefix makes versions sort chronologically for humans; the hash is
    what identifies them. It covers the bronze files AND the identity ledger,
    because re-adjudicating a club changes the dataset without changing a
    single byte of bronze.
    """
    digest = hashlib.blake2b(digest_size=6)
    for f in sorted(files, key=lambda x: x.path):
        digest.update(f"{f.path}:{f.sha256}\n".encode())
    digest.update(f"identity:{identity_digest or ''}\n".encode())
    stamp = (created or datetime.now(timezone.utc)).strftime("%Y%m%d")
    return f"ds_{stamp}_{digest.hexdigest()}"


def build_manifest(
    bronze_root, *, parent_version=None, code_version=None, note=None, identity_digest=None
) -> DatasetManifest:
    files = scan_bronze(bronze_root)
    return DatasetManifest(
        dataset_version=compute_version(files, identity_digest=identity_digest),
        identity_digest=identity_digest,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        files=files,
        parent_version=parent_version,
        code_version=code_version,
        note=note,
    )


def save_manifest(manifest: DatasetManifest, manifest_root) -> Path:
    root = Path(manifest_root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{manifest.dataset_version}.json"
    # A manifest is as immutable as the bronze it describes.
    if path.exists() and path.read_text() != manifest.to_json():
        raise FileExistsError(
            f"manifest {manifest.dataset_version} already exists with different "
            "content; a version is a content hash and cannot be redefined"
        )
    path.write_text(manifest.to_json())
    return path


def load_manifest(version: str, manifest_root) -> DatasetManifest:
    path = Path(manifest_root) / f"{version}.json"
    if not path.exists():
        raise FileNotFoundError(f"no manifest for version {version}")
    return DatasetManifest.from_json(path.read_text())


def list_versions(manifest_root) -> list[str]:
    """Published versions, oldest first.

    Frozen ledgers sit beside their manifests as `<version>.ledger.json` and
    must not be mistaken for versions: the glob matches them, so they are
    filtered by suffix rather than by pattern.
    """
    root = Path(manifest_root)
    if not root.exists():
        return []
    return sorted(
        p.stem for p in root.glob("ds_*.json") if not p.name.endswith(".ledger.json")
    )


def read_head(manifest_root) -> str | None:
    path = Path(manifest_root) / HEAD_FILE
    return path.read_text().strip() if path.exists() else None


def write_head(version: str, manifest_root) -> None:
    root = Path(manifest_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / HEAD_FILE).write_text(version + "\n")


def verify_integrity(manifest: DatasetManifest, bronze_root) -> list[str]:
    """Re-hash every listed file. Empty result means bronze is intact.

    This is what makes "immutable" a checked claim rather than a convention.
    """
    root = Path(bronze_root)
    problems: list[str] = []
    for entry in manifest.files:
        path = root / entry.path
        if not path.exists():
            problems.append(f"missing: {entry.path}")
            continue
        if path.stat().st_size != entry.bytes:
            problems.append(f"size changed: {entry.path}")
            continue
        if _sha256(path) != entry.sha256:
            problems.append(f"content changed: {entry.path}")
    return problems


def ledger_path_for(version: str, manifest_root) -> Path:
    """Where a version's frozen identity ledger is kept.

    A dataset has two inputs. Pinning only the bronze makes rollback a
    half-measure: replaying old bronze under today's identity decisions
    produces a dataset that is neither the old one nor the new one. The
    manifest stores the ledger's hash so a mismatch is detected; this file
    stores its content so the mismatch can be fixed.
    """
    return Path(manifest_root) / f"{version}.ledger.json"
