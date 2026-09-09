"""
C-106's measurement, guarded against drifting away from its own numbers.

`scripts/scan_division_efficiency.py` needs a 44 MB download and several
minutes, so it is not in the suite. What IS in the suite is the artefact it
writes and the document that reads it: a registry entry can be edited, a
markdown table can be edited, and neither would fail on its own.

The specific failure this prevents is the one the measurement was rewritten to
avoid. Raw Brier is higher in the lower divisions and the calibration gap is
not, and those two facts support opposite conclusions. A later edit that leans
on the first and drops the second turns "less sharp" into "mispriced" without
any new data. So the test asserts the shape of the evidence, not just its
presence.
"""

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ARTEFACT = REPO / "docs/validation/division-efficiency.json"
REPORT = REPO / "docs/validation/division-efficiency.md"


@pytest.fixture(scope="module")
def measurement():
    return json.loads(ARTEFACT.read_text())


class TestTheArtefactSaysWhatItIs:
    def test_it_names_its_source_and_benchmark(self, measurement):
        assert measurement["source"] == "xgabora/Club-Football-Match-Data-2000-2025"
        assert "bet365" in measurement["benchmark"]

    def test_it_declares_that_it_carries_no_timestamps(self, measurement):
        """Not absent — declared. An absent key reads as 'not checked'; None
        reads as 'checked, there are none', and only the second one stops a
        later reader from mistaking this for a market path."""
        assert "timestamps" in measurement
        assert measurement["timestamps"] is None

    def test_every_division_counts_the_rows_the_devig_refused(self, measurement):
        """A market whose implied probabilities sum below one is an arbitrage
        or a corrupt row. Dropping those silently would hide a data-quality
        fact about the source."""
        for row in measurement["divisions"]:
            assert "refused_rows" in row, row["division"]
            assert "refused_fraction" in row, row["division"]


class TestTheEvidenceKeepsBothHalves:
    def test_skill_separates_the_tiers(self, measurement):
        skill = measurement["summary"]["brier_skill"]
        assert skill["delta_lower_minus_top"] < 0
        assert skill["p_permutation"] < 0.05

    def test_calibration_does_not(self, measurement):
        """The half that is easy to lose. Without it, a lower skill reads as a
        mispricing, which is exactly what this measurement cannot show."""
        gap = measurement["summary"]["calibration_gap"]
        assert gap["p_permutation"] >= 0.05

    def test_the_margin_moves_against_the_bettor(self, measurement):
        margin = measurement["summary"]["mean_overround"]
        assert margin["delta_lower_minus_top"] > 0

    def test_the_paired_comparison_survives_the_country_confound(self, measurement):
        """Every lower division in the sample is European while the top group
        spans five continents, so the unpaired contrast is partly geography."""
        paired = measurement["summary"]["paired_within_country"]
        assert len(paired) >= 6
        n_neg, n_total = measurement["summary"]["paired_skill_negative"]
        assert n_neg == n_total, "skill no longer falls in every paired country"


class TestTheReportDoesNotOverclaim:
    def test_it_states_that_less_sharp_is_not_mispriced(self):
        text = REPORT.read_text()
        assert "Non e una prova di prezzo sbagliato" in text

    def test_it_states_the_benchmark_is_not_comparable_with_m5_m6(self):
        assert "non sono confrontabili" in REPORT.read_text()

    def test_the_registry_does_not_promote_c106_to_proven(self):
        """C-106 cannot be PROVEN from a source with no timestamps and a
        measurement that cannot separate an uninformed market from an
        unpredictable one."""
        claims = json.loads((REPO / "docs/research/CLAIMS.json").read_text())["claims"]
        claim = next(c for c in claims if c["id"] == "C-106")
        assert claim["status"] != "PROVEN"
