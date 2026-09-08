"""
Repository hygiene — what the working tree holds must reach the repository.

This file exists because of a real incident. The .gitignore inherited from
penaltyblog carried an unanchored ``data/`` rule and a ``/scripts`` rule. Both
are harmless for penaltyblog; in this tree ``data/`` also matches the package
directory ``fiorino/data/``. Seven migrations (0006..0012), the identity ledger,
the lake manifest and both validation scripts were written, exercised by the
test suite and never committed. ``git add -A`` reported nothing wrong, because
skipping an ignored file is exactly what it is supposed to do.

Nothing in the test suite could catch it: the tests read the working tree, and
the working tree was complete. Only the repository was missing the schema its
own code depends on. So the check has to be about git, not about Python.
"""

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: Directories whose source is, without exception, part of the deliverable.
SOURCE_TREES = ("fiorino", "test", "scripts")

#: Extensions that carry meaning a checkout cannot reconstruct.
SOURCE_SUFFIXES = {".py", ".sql", ".toml", ".md", ".json", ".yaml", ".yml"}

#: Generated or transient, and legitimately ignored inside those trees.
TRANSIENT_PARTS = {"__pycache__", ".pytest_cache", ".hypothesis", "build", ".ruff_cache"}


def _git(*args: str) -> str:
    done = subprocess.run(
        ("git", "-C", str(REPO), *args),
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode not in (0, 1):  # 1 == "no match", not a failure here
        pytest.skip(f"git unavailable or not a repository: {done.stderr.strip()}")
    return done.stdout


@pytest.fixture(scope="module")
def source_files() -> list[Path]:
    files = []
    for tree in SOURCE_TREES:
        root = REPO / tree
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            if TRANSIENT_PARTS & set(path.relative_to(REPO).parts):
                continue
            files.append(path)
    return files


def test_the_source_trees_are_not_empty(source_files):
    """Guard the guard: an empty list would make every test below vacuous."""
    assert len(source_files) > 50


def test_no_source_file_is_git_ignored(source_files):
    """
    The check that would have caught the incident.

    An ignored source file is invisible to ``git add -A``, so it is invisible to
    every commit, every CI run and every fresh clone — while the local suite
    stays green because the file is right there on disk.
    """
    rel = sorted(str(p.relative_to(REPO)) for p in source_files)
    # check-ignore exits 1 when nothing matches, which is the healthy case.
    ignored = _git("check-ignore", "--no-index", *rel).split()
    assert not ignored, (
        "these source files are excluded by .gitignore and can never be "
        "committed:\n  " + "\n  ".join(sorted(ignored))
    )


def test_every_migration_is_tracked():
    """
    The schema is the one thing a checkout cannot rebuild from anything else.

    A missing migration does not fail loudly: the database is simply built
    without the tables, and the first query against them is the error message.
    """
    on_disk = sorted(p.name for p in (REPO / "fiorino/data/db/migrations").glob("*.sql"))
    tracked = set(
        Path(line).name
        for line in _git("ls-files", "fiorino/data/db/migrations").splitlines()
        if line.endswith(".sql")
    )
    missing = [name for name in on_disk if name not in tracked]
    assert not missing, f"migrations present on disk but untracked: {missing}"


def test_migration_numbering_has_no_gaps_or_duplicates():
    """Ordering is the contract; migrate() applies them in lexical order."""
    numbers = sorted(
        int(p.name.split("_", 1)[0])
        for p in (REPO / "fiorino/data/db/migrations").glob("*.sql")
    )
    assert numbers == list(range(1, len(numbers) + 1)), numbers
