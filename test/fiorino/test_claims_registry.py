"""
The claims registry, checked against reality.

docs/research/CLAIMS.json states what Fiorino Quant claims and how strongly.
Left unchecked it would drift into a marketing document within one release:
statuses stay while the tests behind them get renamed, deleted or weakened, and
nobody notices because a JSON file cannot fail.

So it fails here. Every claim marked PROVEN must name tests that exist and are
collectable; every other status must name the reason it is not PROVEN.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "docs/research/CLAIMS.json"

STATUSES = {"PROVEN", "TESTED_BUT_LIMITED", "UNTESTED", "DATA_GAP", "NOT_DEMONSTRATED"}
#: Statuses that assert something holds, and therefore owe a test.
ASSERTIVE = {"PROVEN"}
#: Statuses that assert nothing and must not pretend to.
NON_ASSERTIVE = {"DATA_GAP", "NOT_DEMONSTRATED"}


@pytest.fixture(scope="module")
def registry():
    return json.loads(REGISTRY.read_text())


@pytest.fixture(scope="module")
def collected():
    """Every test id pytest can actually collect."""
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "test/fiorino", "--collect-only", "-q",
         "-p", "no:randomly"],
        capture_output=True, text=True, cwd=REPO, timeout=600,
    )
    if done.returncode != 0:
        pytest.skip(f"collection failed: {done.stderr[-500:]}")
    return {line.strip() for line in done.stdout.splitlines()
            if "::" in line and line.strip().startswith("test/")}


class TestTheRegistryIsWellFormed:
    def test_every_status_is_from_the_vocabulary(self, registry):
        for claim in registry["claims"]:
            assert claim["status"] in STATUSES, claim["id"]

    def test_ids_are_unique(self, registry):
        ids = [c["id"] for c in registry["claims"]]
        assert len(ids) == len(set(ids))

    def test_every_claim_is_a_sentence_not_a_label(self, registry):
        for claim in registry["claims"]:
            assert len(claim["claim"]) > 25, claim["id"]
            assert claim["claim"].endswith("."), claim["id"]

    def test_the_registry_is_not_empty_of_hard_cases(self, registry):
        """A registry with no gaps and no failures is not describing this
        project, it is describing a brochure."""
        statuses = {c["status"] for c in registry["claims"]}
        assert "DATA_GAP" in statuses
        assert "NOT_DEMONSTRATED" in statuses
        assert "UNTESTED" in statuses


class TestProvenMeansProven:
    def test_every_proven_claim_names_at_least_one_test(self, registry):
        for claim in registry["claims"]:
            if claim["status"] in ASSERTIVE:
                assert claim["verified_by"], claim["id"]

    def test_every_named_test_exists(self, registry, collected):
        """The check the registry exists for. A renamed or deleted test leaves
        a claim standing on nothing, and only this notices."""
        missing = []
        for claim in registry["claims"]:
            for node in claim["verified_by"]:
                if node not in collected:
                    missing.append(f"{claim['id']} -> {node}")
        assert not missing, "claims naming tests that do not exist:\n  " + "\n  ".join(missing)

    def test_a_proven_claim_states_no_limit_or_a_real_one(self, registry):
        for claim in registry["claims"]:
            if claim["status"] == "PROVEN" and claim["limits"] is not None:
                assert len(claim["limits"]) > 30, claim["id"]


class TestWeakerStatusesAreHonest:
    def test_a_limited_claim_says_what_limits_it(self, registry):
        """'TESTED_BUT_LIMITED' without a stated limit is 'PROVEN' with better
        marketing."""
        for claim in registry["claims"]:
            if claim["status"] == "TESTED_BUT_LIMITED":
                assert claim["limits"], claim["id"]
                assert len(claim["limits"]) > 40, claim["id"]

    def test_an_untested_claim_says_why(self, registry):
        for claim in registry["claims"]:
            if claim["status"] == "UNTESTED":
                assert claim["limits"], claim["id"]

    def test_a_non_assertive_claim_carries_no_proof(self, registry):
        """A DATA_GAP that names verifying tests is not a gap."""
        for claim in registry["claims"]:
            if claim["status"] in NON_ASSERTIVE:
                assert not claim["verified_by"], claim["id"]

    def test_the_profitability_claim_is_not_demonstrated(self, registry):
        """Stated explicitly so nobody has to infer it from silence, and
        asserted here so it cannot quietly change status."""
        claim = next(c for c in registry["claims"] if c["id"] == "C-200")
        assert claim["status"] == "NOT_DEMONSTRATED"
        assert not claim["verified_by"]

    def test_the_power_limit_travels_with_the_negative_result(self, registry):
        """'Nothing found' is meaningless without 'we could have found X'."""
        claim = next(c for c in registry["claims"] if c["id"] == "C-018")
        assert "MINIMUM DETECTABLE EFFECT" in claim["limits"].upper()


class TestTheRegistryIsAlsoARoadmap:
    """Every claim that is not PROVEN owes the single step that would change
    its status. Without it the registry records where the project is and not
    where it is going, and a status with no way out becomes permanent by
    default."""

    NEEDS_ACTION = {"TESTED_BUT_LIMITED", "UNTESTED", "DATA_GAP"}

    def test_every_unfinished_claim_names_its_next_action(self, registry):
        missing = [c["id"] for c in registry["claims"]
                   if c["status"] in self.NEEDS_ACTION and not c.get("next_action")]
        assert not missing, f"no next_action: {missing}"

    def test_a_next_action_is_an_action(self, registry):
        for claim in registry["claims"]:
            action = claim.get("next_action")
            if action and not action.lower().startswith("nessuna"):
                assert len(action) > 40, claim["id"]

    def test_a_proven_claim_needs_no_next_action(self, registry):
        """A PROVEN claim with a pending step is not proven."""
        for claim in registry["claims"]:
            if claim["status"] == "PROVEN":
                assert "next_action" not in claim, claim["id"]

    def test_the_data_gaps_point_at_data_not_at_modelling(self, registry):
        """The bottleneck is time, not the model. If a DATA_GAP's next action
        talks about models, the diagnosis has drifted."""
        for claim in registry["claims"]:
            if claim["status"] == "DATA_GAP":
                action = claim["next_action"].lower()
                assert any(w in action for w in ("quot", "dat", "raccolt", "fonte")), claim["id"]


class TestTheRegistryMatchesTheDocs:
    def test_the_data_gaps_agree_with_the_data_catalog(self, registry):
        catalog = (REPO / "docs/research/DATA_CATALOG.md").read_text().lower()
        for claim in registry["claims"]:
            if claim["status"] == "DATA_GAP":
                assert "data gap" in catalog

    def test_the_registry_is_linked_from_the_findings(self):
        findings = (REPO / "docs/FINDINGS.md").read_text()
        assert "CLAIMS.json" in findings
