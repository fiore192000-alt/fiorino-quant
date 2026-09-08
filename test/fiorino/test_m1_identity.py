"""
M1 — identity resolution: precedence, quarantine, collisions, homonyms,
renames, promotion and relegation.
"""

import pytest

from fiorino.data.identity.audit import BLOCKING, run_identity_audit
from fiorino.data.identity.overrides import add_override, list_overrides
from fiorino.data.identity.resolver import IdentityResolver, MatchMethod


@pytest.fixture
def arsenal(seeded_db, resolver):
    tid = resolver.register_team("Arsenal", "ENG")
    resolver.add_alias("Arsenal", "footballdata", "ENG", tid)
    return tid


class TestPrecedenceLadder:
    def test_exact_raw_wins_for_the_registered_source(self, resolver, arsenal):
        r = resolver.resolve("Arsenal", "footballdata", "ENG")
        assert r.team_id == arsenal
        assert r.method is MatchMethod.EXACT_RAW
        assert r.approved

    def test_normalized_match_crosses_sources(self, resolver, arsenal):
        """A source we never registered still resolves through the normal form."""
        r = resolver.resolve("Arsenal FC", "fbref", "ENG")
        assert r.team_id == arsenal
        assert r.method is MatchMethod.EXACT_NORMALIZED
        assert r.approved

    def test_override_beats_everything(self, seeded_db, resolver, arsenal):
        other = resolver.register_team("Arsenal Reserves", "ENG")
        add_override(seeded_db, "Arsenal", "ENG", other, "test decision", "ops", resolver=resolver)
        r = resolver.resolve("Arsenal", "footballdata", "ENG")
        assert r.method is MatchMethod.OVERRIDE
        assert r.team_id == other

    def test_unknown_name_is_unresolved(self, resolver, arsenal):
        r = resolver.resolve("Wolverhampton Wanderers", "fbref", "ENG")
        assert r.method is MatchMethod.UNRESOLVED
        assert not r.approved
        assert r.blocks_pipeline


class TestFuzzyIsQuarantined:
    """Rule 9: a fuzzy match never feeds the analytic dataset."""

    def test_typo_produces_a_proposal_not_a_match(self, resolver, arsenal):
        r = resolver.resolve("Arsenol", "fbref", "ENG")
        assert r.method is MatchMethod.FUZZY_PROPOSAL
        assert r.team_id == arsenal, "the suggestion is recorded for audit"
        assert not r.approved, "but it is NOT usable"
        assert r.blocks_pipeline

    def test_proposal_is_filed_in_quarantine(self, seeded_db, resolver, arsenal):
        r = resolver.resolve("Arsenol", "fbref", "ENG")
        resolver.record_proposal(r)
        rows = seeded_db.execute(
            "SELECT status, candidate_team_id FROM team_alias_proposals"
        ).fetchall()
        assert rows == [("PROPOSED", arsenal)]

    def test_recording_a_proposal_creates_no_alias(self, seeded_db, resolver, arsenal):
        resolver.record_proposal(resolver.resolve("Arsenol", "fbref", "ENG"))
        n = seeded_db.execute(
            "SELECT count(*) FROM team_aliases WHERE alias_raw = 'Arsenol'"
        ).fetchone()[0]
        assert n == 0

    def test_a_fuzzy_alias_can_never_be_written_directly(self, resolver, arsenal):
        with pytest.raises(ValueError, match="approve it first"):
            resolver.add_alias("Arsenol", "fbref", "ENG", arsenal, MatchMethod.FUZZY_PROPOSAL)

    def test_schema_itself_rejects_a_fuzzy_alias(self, seeded_db, arsenal):
        """Defence in depth: the CHECK constraint, not just the Python guard."""
        with pytest.raises(Exception):
            seeded_db.execute(
                """INSERT INTO team_aliases (alias_raw, source, country, alias_normalized,
                   team_id, match_method, confidence, status)
                   VALUES ('Arsenol','fbref','ENG','arsenol', ?, 'FUZZY', 0.9, 'APPROVED')""",
                [arsenal],
            )

    def test_approval_promotes_the_proposal(self, seeded_db, resolver, arsenal):
        r = resolver.resolve("Arsenol", "fbref", "ENG")
        resolver.record_proposal(r)
        resolver.approve_proposal(r.proposal_id, "ops", "confirmed by hand")
        after = resolver.resolve("Arsenol", "fbref", "ENG")
        assert after.approved and after.team_id == arsenal
        assert seeded_db.execute(
            "SELECT status FROM team_alias_proposals WHERE proposal_id = ?", [r.proposal_id]
        ).fetchone()[0] == "APPROVED"

    def test_rejection_leaves_it_unusable(self, seeded_db, resolver, arsenal):
        r = resolver.resolve("Arsenol", "fbref", "ENG")
        resolver.record_proposal(r)
        resolver.reject_proposal(r.proposal_id, "ops", "different club")
        assert not resolver.resolve("Arsenol", "fbref", "ENG").approved

    def test_open_proposals_block_the_audit(self, seeded_db, resolver, arsenal):
        resolver.record_proposal(resolver.resolve("Arsenol", "fbref", "ENG"))
        blocking = [f for f in run_identity_audit(seeded_db) if f.severity == BLOCKING]
        assert any(f.check_name == "open_fuzzy_proposal" for f in blocking)


class TestHomonyms:
    def test_same_name_different_countries_stays_distinct(self, seeded_db, resolver):
        prt = resolver.register_team("Sporting CP", "PRT")
        esp = resolver.register_team("Sporting Gijon", "ESP")
        resolver.add_alias("Sporting", "footballdata", "PRT", prt)
        resolver.add_alias("Sporting", "footballdata", "ESP", esp)
        assert resolver.resolve("Sporting", "footballdata", "PRT").team_id == prt
        assert resolver.resolve("Sporting", "footballdata", "ESP").team_id == esp
        assert not [f for f in run_identity_audit(seeded_db) if f.severity == BLOCKING]

    def test_ambiguous_name_inside_one_country_is_never_auto_merged(self, seeded_db, resolver):
        """Vitoria Guimaraes and Vitoria Setubal both abbreviate to "Vitoria"."""
        g = resolver.register_team("Vitoria Guimaraes", "PRT")
        s = resolver.register_team("Vitoria Setubal", "PRT")
        resolver.add_alias("Vitoria", "fbref", "PRT", g)
        resolver.add_alias("Vitoria", "understat", "PRT", s)

        r = resolver.resolve("Vitoria", "footballdata", "PRT")
        assert r.method is MatchMethod.UNRESOLVED
        assert not r.approved
        assert "ambiguous" in (r.note or "")

    def test_ambiguity_is_reported_as_blocking(self, seeded_db, resolver):
        g = resolver.register_team("Vitoria Guimaraes", "PRT")
        s = resolver.register_team("Vitoria Setubal", "PRT")
        resolver.add_alias("Vitoria", "fbref", "PRT", g)
        resolver.add_alias("Vitoria", "understat", "PRT", s)
        names = {f.check_name for f in run_identity_audit(seeded_db) if f.severity == BLOCKING}
        assert "homonym" in names

    def test_an_override_settles_the_ambiguity(self, seeded_db, resolver):
        g = resolver.register_team("Vitoria Guimaraes", "PRT")
        s = resolver.register_team("Vitoria Setubal", "PRT")
        resolver.add_alias("Vitoria", "fbref", "PRT", g)
        resolver.add_alias("Vitoria", "understat", "PRT", s)
        add_override(seeded_db, "Vitoria", "PRT", g, "footballdata means Guimaraes",
                     "ops", source="footballdata", resolver=resolver)
        r = resolver.resolve("Vitoria", "footballdata", "PRT")
        assert r.approved and r.team_id == g


class TestAliasCollisions:
    def test_rebinding_an_alias_is_refused(self, resolver, arsenal):
        other = resolver.register_team("Arsenal Reserves", "ENG")
        with pytest.raises(ValueError, match="alias collision"):
            resolver.add_alias("Arsenal", "footballdata", "ENG", other)

    def test_rebinding_to_the_same_team_is_idempotent(self, seeded_db, resolver, arsenal):
        resolver.add_alias("Arsenal", "footballdata", "ENG", arsenal)
        n = seeded_db.execute(
            "SELECT count(*) FROM team_aliases WHERE alias_raw='Arsenal'"
        ).fetchone()[0]
        assert n == 1

    def test_duplicate_aliases_across_sources_are_fine(self, seeded_db, resolver, arsenal):
        resolver.add_alias("Arsenal", "fbref", "ENG", arsenal)
        resolver.add_alias("Arsenal", "understat", "ENG", arsenal)
        assert not [f for f in run_identity_audit(seeded_db) if f.check_name == "alias_collision"]


class TestRenames:
    def test_a_rename_maps_to_the_same_team(self, seeded_db, resolver):
        tid = resolver.register_team("Milton Keynes Dons", "ENG")
        resolver.add_alias("Milton Keynes Dons", "footballdata", "ENG", tid)

        unresolved = resolver.resolve("MK Dons", "footballdata", "ENG")
        assert not unresolved.approved, "a rename is not guessable and must not be guessed"

        add_override(seeded_db, "MK Dons", "ENG", tid, "club renamed in 2019", "ops",
                     resolver=resolver)
        assert resolver.resolve("MK Dons", "footballdata", "ENG").team_id == tid
        assert resolver.resolve("Milton Keynes Dons", "footballdata", "ENG").team_id == tid

    def test_the_override_is_attributed(self, seeded_db, resolver):
        tid = resolver.register_team("Milton Keynes Dons", "ENG")
        add_override(seeded_db, "MK Dons", "ENG", tid, "club renamed in 2019", "ops")
        row = list_overrides(seeded_db)[0]
        assert row["reason"] and row["created_by"] == "ops"

    def test_an_override_needs_a_reason_and_an_author(self, seeded_db, resolver, arsenal):
        with pytest.raises(ValueError, match="reason"):
            add_override(seeded_db, "X", "ENG", arsenal, "  ", "ops")
        with pytest.raises(ValueError, match="author"):
            add_override(seeded_db, "X", "ENG", arsenal, "why", "  ")

    def test_overrides_are_append_only(self, seeded_db, resolver, arsenal):
        other = resolver.register_team("Other", "ENG")
        add_override(seeded_db, "X", "ENG", arsenal, "first", "ops")
        with pytest.raises(ValueError, match="append-only"):
            add_override(seeded_db, "X", "ENG", other, "second", "ops")
