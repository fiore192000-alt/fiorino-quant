"""
The source registry, and the misclassification it exists to prevent.

BeatTheBookie ships two artefacts from the same database. One carries a real
`odds_datetime` per observation; the other resamples it onto a 72-point hourly
grid and anonymises the bookmaker into a row index. They are equally easy to
download and they are NOT equally usable: an hourly grid cannot resolve a
lineup published 60-75 minutes before kickoff, which is the whole experiment.

Nothing in a description distinguishes them. So the distinction lives here.
"""

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "docs/research/SOURCES.json"

STATUSES = {"USABLE_NOW", "USABLE_WITH_EXTERNAL_INGEST",
            "PROMISING_BUT_UNVERIFIED", "NOT_SUITABLE"}

#: Only this one supports a point-in-time claim. RESAMPLED_GRID does not: the
#: instant was thrown away when the grid was built, and no downstream code can
#: recover it.
PIT_QUALITY = {"ABSOLUTE_PER_OBSERVATION"}
ALL_QUALITY = PIT_QUALITY | {"RESAMPLED_GRID", "NONE", "UNKNOWN"}


@pytest.fixture(scope="module")
def sources():
    return json.loads(REGISTRY.read_text())["sources"]


class TestVocabulary:
    def test_statuses_are_from_the_list(self, sources):
        for s in sources:
            assert s["status"] in STATUSES, s["id"]

    def test_timestamp_qualities_are_from_the_list(self, sources):
        for s in sources:
            assert s["timestamp_quality"] in ALL_QUALITY, s["id"]

    def test_ids_are_unique(self, sources):
        ids = [s["id"] for s in sources]
        assert len(ids) == len(set(ids))


class TestPitUsabilityCannotBeClaimedLoosely:
    """The three conditions the audit brief named, enforced."""

    def test_unknown_timestamp_quality_can_never_be_pit_usable(self, sources):
        for s in sources:
            if s["timestamp_quality"] == "UNKNOWN":
                assert not s["pit_usable"], (
                    f"{s['id']}: a provider's promise is not a verification"
                )

    def test_an_unidentifiable_bookmaker_can_never_be_pit_usable(self, sources):
        for s in sources:
            if not s["bookmaker_identifiable"]:
                assert not s["pit_usable"], s["id"]

    def test_an_undocumented_acquisition_can_never_be_pit_usable(self, sources):
        for s in sources:
            if not s.get("access_documented"):
                assert not s["pit_usable"], s["id"]

    def test_pit_usability_requires_an_absolute_instant(self, sources):
        for s in sources:
            if s["pit_usable"]:
                assert s["timestamp_quality"] in PIT_QUALITY, s["id"]

    def test_a_resampled_grid_is_never_pit_usable(self, sources):
        """The specific error: a grid looks like a series and is not one."""
        for s in sources:
            if s["timestamp_quality"] == "RESAMPLED_GRID":
                assert not s["pit_usable"], s["id"]
                assert s["status"] == "NOT_SUITABLE", s["id"]


class TestStatusFollowsFromTheFacts:
    def test_usable_now_requires_accessibility(self, sources):
        for s in sources:
            if s["status"] == "USABLE_NOW":
                assert s["accessible_here"], s["id"]

    def test_external_ingest_means_the_data_is_fine_and_the_network_is_not(self, sources):
        """The distinction the brief insisted on: environment access
        limitation, not source unavailable."""
        for s in sources:
            if s["status"] == "USABLE_WITH_EXTERNAL_INGEST":
                assert s["pit_usable"], s["id"]
                assert not s["accessible_here"], s["id"]
                assert "environment access limitation" in s["inaccessibility_reason"], s["id"]

    def test_unverified_sources_are_not_promoted(self, sources):
        for s in sources:
            if s["status"] == "PROMISING_BUT_UNVERIFIED":
                assert not s["pit_usable"], s["id"]
                assert s["timestamp_quality"] == "UNKNOWN", s["id"]

    def test_every_inaccessible_source_says_why(self, sources):
        for s in sources:
            if not s["accessible_here"]:
                assert s["inaccessibility_reason"], s["id"]

    def test_every_source_states_its_main_limitation(self, sources):
        for s in sources:
            assert len(s["main_limitation"]) > 40, s["id"]


class TestTheEvidenceIsRecorded:
    def test_every_timestamp_claim_cites_how_it_was_checked(self, sources):
        for s in sources:
            assert s["timestamp_evidence"], s["id"]
            assert len(s["timestamp_evidence"]) > 25, s["id"]

    def test_the_two_beatthebookie_artefacts_are_separate_entries(self, sources):
        """They come from one database and are not interchangeable. Merging
        them into one row is how the resampled grid would get credit for the
        dump's timestamps."""
        ids = {s["id"] for s in sources}
        assert {"beatthebookie-sql", "beatthebookie-txt"} <= ids
        sql = next(s for s in sources if s["id"] == "beatthebookie-sql")
        txt = next(s for s in sources if s["id"] == "beatthebookie-txt")
        assert sql["pit_usable"] and not txt["pit_usable"]

    def test_at_most_one_source_is_pit_usable_today(self, sources):
        """Asserted so that adding a second one is a deliberate act with
        evidence, not an edit."""
        usable = [s["id"] for s in sources if s["pit_usable"]]
        assert usable == ["beatthebookie-sql"], usable


class TestTheDocumentAgrees:
    def test_the_markdown_audit_exists_and_names_every_source(self, sources):
        text = (REPO / "docs/research/FREE_SOURCES_AUDIT.md").read_text().lower()
        for s in sources:
            token = s["name"].split("—")[0].split("(")[0].strip().lower()
            assert token[:12] in text, s["id"]

    def test_no_source_is_called_unavailable_when_it_is_blocked(self, sources):
        """'Source unavailable' would be a claim about the dataset. The dataset
        is fine; this environment is not."""
        text = (REPO / "docs/research/FREE_SOURCES_AUDIT.md").read_text()
        assert "environment access limitation" in text
