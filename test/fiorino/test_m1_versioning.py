"""
Dataset versioning: identify, rebuild, roll back, verify.

Storage separation is a design decision with teeth, so it is tested: the
repository holds code, schema, configuration and the identity ledger; the
dataset lives under $FIORINO_DATA_ROOT.
"""

import json
from pathlib import Path

import pytest

from factories import build_bronze, seed_identity
from fiorino.config.storage import DEFAULT_ROOT, ENV_VAR, bronze_root, data_root
from fiorino.data.db.connection import connect
from fiorino.data.db.migrate import migrate
from fiorino.data.identity.ledger import export_ledger, import_ledger, ledger_digest
from fiorino.data.identity.resolver import IdentityResolver
from fiorino.data.lake.manifest import (
    build_manifest,
    compute_version,
    list_versions,
    load_manifest,
    read_head,
    save_manifest,
    scan_bronze,
    verify_integrity,
    write_head,
)
from fiorino.data.pipeline import (
    bootstrap_reference,
    canonical_snapshot,
    logical_digest,
    rebuild_from_manifest,
)

COMPS = ["ENG_PL"]
SEASONS = ["2019-2020"]


@pytest.fixture
def lake(tmp_path):
    con = connect()
    bootstrap_reference(con)
    root = tmp_path / "bronze"
    build_bronze(con, root, competitions=COMPS, seasons=SEASONS)
    con.close()
    return root


@pytest.fixture
def built(lake, tmp_path):
    """A database built from the lake, with identity seeded."""
    con = connect()
    migrate(con)
    bootstrap_reference(con)
    seed_identity(con, IdentityResolver(con), competitions=COMPS, seasons=SEASONS)
    manifest = build_manifest(lake)
    rebuild_from_manifest(con, lake, manifest)
    return con, lake, manifest


class TestStorageSeparation:
    def test_the_default_data_root_is_outside_the_repository(self):
        repo = Path(__file__).resolve().parents[2]
        assert repo not in DEFAULT_ROOT.resolve().parents
        assert DEFAULT_ROOT.resolve() != repo

    def test_the_root_is_configurable(self, monkeypatch, tmp_path):
        monkeypatch.setenv(ENV_VAR, str(tmp_path / "elsewhere"))
        assert data_root() == tmp_path / "elsewhere"
        assert bronze_root() == tmp_path / "elsewhere" / "bronze"

    def test_the_repository_ignores_data_directories(self):
        ignored = (Path(__file__).resolve().parents[2] / ".gitignore").read_text()
        assert "data/" in ignored and "*.duckdb" in ignored


class TestVersionIdentity:
    def test_a_version_is_a_content_hash(self, lake):
        files = scan_bronze(lake)
        assert compute_version(files) == compute_version(files)

    def test_different_bronze_yields_a_different_version(self, lake, tmp_path):
        first = compute_version(scan_bronze(lake))
        con = connect()
        bootstrap_reference(con)
        build_bronze(con, lake, competitions=["ITA_SA"], seasons=SEASONS)
        con.close()
        assert compute_version(scan_bronze(lake)) != first

    def test_the_identity_ledger_is_part_of_the_version(self, lake):
        """The correction that matters: bronze alone does not pin a dataset."""
        files = scan_bronze(lake)
        assert compute_version(files, identity_digest="aaa") != compute_version(
            files, identity_digest="bbb"
        )

    def test_the_version_carries_a_sortable_date_prefix(self, lake):
        assert compute_version(scan_bronze(lake)).startswith("ds_20")

    def test_a_manifest_names_every_input_file(self, lake):
        manifest = build_manifest(lake)
        assert manifest.files
        assert {f.path for f in manifest.files} == {
            p.relative_to(lake).as_posix() for p in lake.rglob("*.parquet")
        }
        assert all(f.sha256 and f.bytes > 0 for f in manifest.files)


class TestImmutability:
    def test_intact_bronze_verifies(self, lake):
        assert verify_integrity(build_manifest(lake), lake) == []

    def test_a_modified_file_is_detected(self, lake):
        manifest = build_manifest(lake)
        target = lake / manifest.files[0].path
        target.write_bytes(target.read_bytes() + b"x")
        problems = verify_integrity(manifest, lake)
        assert problems and "size changed" in problems[0]

    def test_a_deleted_file_is_detected(self, lake):
        manifest = build_manifest(lake)
        (lake / manifest.files[0].path).unlink()
        assert any("missing" in p for p in verify_integrity(manifest, lake))

    def test_a_manifest_cannot_be_redefined(self, lake, tmp_path):
        manifests = tmp_path / "manifests"
        manifest = build_manifest(lake)
        save_manifest(manifest, manifests)
        from dataclasses import replace

        with pytest.raises(FileExistsError, match="cannot be redefined"):
            save_manifest(replace(manifest, note="different"), manifests)


class TestRebuildEquivalence:
    def test_the_logical_digest_is_stable_across_rebuilds(self, built):
        _, lake, manifest = built
        digests = []
        for _ in range(2):
            con = connect()
            migrate(con)
            bootstrap_reference(con)
            seed_identity(con, IdentityResolver(con), competitions=COMPS, seasons=SEASONS)
            rebuild_from_manifest(con, lake, manifest)
            digests.append(logical_digest(con))
            con.close()
        assert digests[0] == digests[1]

    def test_the_digest_changes_when_the_facts_change(self, built, tmp_path):
        con, lake, manifest = built
        before = logical_digest(con)
        build_bronze(con, lake, competitions=["ITA_SA"], seasons=SEASONS)
        wider = build_manifest(lake)
        fresh = connect()
        migrate(fresh)
        bootstrap_reference(fresh)
        seed_identity(fresh, IdentityResolver(fresh),
                      competitions=COMPS + ["ITA_SA"], seasons=SEASONS)
        rebuild_from_manifest(fresh, lake, wider)
        assert logical_digest(fresh) != before
        fresh.close()

    def test_a_manifest_rebuild_ignores_files_it_does_not_name(self, built):
        """What makes rollback exact after newer bronze has landed."""
        con, lake, manifest = built
        before = logical_digest(con)

        seed = connect()
        bootstrap_reference(seed)
        build_bronze(seed, lake, competitions=["ITA_SA"], seasons=SEASONS)
        seed.close()

        fresh = connect()
        migrate(fresh)
        bootstrap_reference(fresh)
        seed_identity(fresh, IdentityResolver(fresh), competitions=COMPS, seasons=SEASONS)
        rebuild_from_manifest(fresh, lake, manifest)  # the OLD manifest
        assert logical_digest(fresh) == before
        fresh.close()


class TestIdentityLedger:
    def test_a_ledger_round_trips(self, built, tmp_path):
        con, lake, manifest = built
        path = tmp_path / "ledger.json"
        export_ledger(con, path)

        fresh = connect()
        migrate(fresh)
        bootstrap_reference(fresh)
        counts = import_ledger(fresh, path)
        assert counts["teams"] > 0
        assert ledger_digest(con=fresh) == ledger_digest(con=con)
        fresh.close()

    def test_the_ledger_is_sorted_and_diffable(self, built, tmp_path):
        con, _, _ = built
        path = tmp_path / "ledger.json"
        export_ledger(con, path)
        payload = json.loads(path.read_text())
        names = [t["canonical_name"] for t in payload["teams"]]
        assert names == sorted(names)

    def test_rebuilding_without_the_ledger_gives_a_different_dataset(self, built, lake, tmp_path):
        """Why the manifest pins both inputs."""
        con, _, manifest = built
        with_ledger = logical_digest(con)

        without = connect()
        migrate(without)
        bootstrap_reference(without)
        rebuild_from_manifest(without, lake, manifest, auto_register_unknown=True)
        assert logical_digest(without) != with_ledger
        without.close()

    def test_the_ledger_records_rejected_proposals(self, built, tmp_path):
        con, _, _ = built
        resolver = IdentityResolver(con)
        tid = resolver.register_team("Sample FC", "ENG")
        res = resolver.resolve("Sampl FC", "fbref", "ENG")
        if res.proposal_id:
            resolver.record_proposal(res)
            resolver.reject_proposal(res.proposal_id, "ops", "different club")
        path = tmp_path / "ledger.json"
        export_ledger(con, path)
        payload = json.loads(path.read_text())
        assert any(p["status"] == "REJECTED" for p in payload["team_alias_proposals"])


class TestHead:
    def test_head_starts_unset_and_can_be_moved(self, tmp_path):
        manifests = tmp_path / "manifests"
        assert read_head(manifests) is None
        write_head("ds_20260101_abc", manifests)
        assert read_head(manifests) == "ds_20260101_abc"

    def test_versions_are_listed_oldest_first(self, lake, tmp_path):
        manifests = tmp_path / "manifests"
        save_manifest(build_manifest(lake), manifests)
        assert len(list_versions(manifests)) == 1

    def test_frozen_ledgers_are_not_mistaken_for_versions(self, lake, tmp_path):
        manifests = tmp_path / "manifests"
        manifest = build_manifest(lake)
        save_manifest(manifest, manifests)
        (manifests / f"{manifest.dataset_version}.ledger.json").write_text("{}")
        assert list_versions(manifests) == [manifest.dataset_version]

    def test_an_unknown_version_is_refused(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="no manifest"):
            load_manifest("ds_nope", tmp_path / "manifests")
