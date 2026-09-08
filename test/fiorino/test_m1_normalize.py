"""M1 — team-name normalisation, including property tests."""

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from fiorino.data.identity.normalize import (
    AFFIXES,
    normalize_team_name,
    strip_diacritics,
    tokenize,
)


class TestBasics:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Manchester United", "manchester united"),
            ("Manchester Utd", "manchester utd"),
            ("FC Barcelona", "barcelona"),
            ("Real Madrid CF", "real madrid"),
            ("AC Milan", "milan"),
            ("Bayern München", "bayern munchen"),
            ("Borussia Mönchengladbach", "borussia monchengladbach"),
            ("Nott'm Forest", "nottm forest"),
            ("Brighton & Hove Albion", "brighton and hove albion"),
            ("  Ajax  ", "ajax"),
        ],
    )
    def test_known_cases(self, raw, expected):
        assert normalize_team_name(raw) == expected

    def test_diacritics_removed(self):
        assert strip_diacritics("Atlético Peñarol") == "Atletico Penarol"


class TestNumericTokensSurvive:
    """The trap: dropping numbers merges distinct clubs."""

    def test_1860_munchen_does_not_collapse_to_munchen(self):
        assert normalize_team_name("1860 München") == "1860 munchen"
        assert normalize_team_name("1860 München") != normalize_team_name("Bayern München")

    @pytest.mark.parametrize(
        "raw,expected",
        [("Schalke 04", "schalke 04"), ("TSG 1899 Hoffenheim", "1899 hoffenheim")],
    )
    def test_numbers_are_kept(self, raw, expected):
        assert normalize_team_name(raw) == expected


class TestDistinctnessPreserved:
    """Names that must never normalise to the same key."""

    @pytest.mark.parametrize(
        "a,b",
        [
            ("Sporting CP", "Sporting Gijon"),
            ("Vitoria Guimaraes", "Vitoria Setubal"),
            ("Real Madrid", "Real Sociedad"),
            ("Atletico Madrid", "Athletic Club"),
            ("Manchester United", "Manchester City"),
            ("Milton Keynes Dons", "MK Dons"),
            ("Inter", "Inter Milan"),
        ],
    )
    def test_distinct_clubs_stay_distinct(self, a, b):
        assert normalize_team_name(a) != normalize_team_name(b)


class TestAffixes:
    def test_club_type_affixes_are_dropped(self):
        assert normalize_team_name("FC Porto") == normalize_team_name("Porto")

    def test_distinguishing_words_are_kept(self):
        """"real", "sporting", "athletic" separate real clubs and must survive."""
        for word in ("real", "sporting", "athletic", "atletico", "deportivo", "olympique"):
            assert word not in AFFIXES

    def test_a_name_of_only_affixes_is_not_emptied(self):
        assert normalize_team_name("FC SC") == "fc sc"

    def test_empty_name_is_rejected(self):
        with pytest.raises(ValueError):
            normalize_team_name("   ")


class TestProperties:
    """Hypothesis: invariants that must hold for any input."""

    #: Latin letters, digits, spaces and hyphens — the scripts the sources
    #: actually emit for European club names.
    names = st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),
            whitelist_characters=" -\'",
            max_codepoint=0x24F,          # Latin-1 Supplement + Latin Extended-A/B
        ),
        min_size=1, max_size=40,
    )

    @given(names)
    def test_idempotent(self, raw):
        assume(raw.strip())
        try:
            once = normalize_team_name(raw)
        except ValueError:
            return
        assert normalize_team_name(once) == once

    @given(names)
    def test_never_returns_empty_or_padded(self, raw):
        assume(raw.strip())
        try:
            out = normalize_team_name(raw)
        except ValueError:
            return
        assert out and out == out.strip()
        assert "  " not in out

    @given(names)
    def test_output_is_lowercase(self, raw):
        assume(raw.strip())
        try:
            out = normalize_team_name(raw)
        except ValueError:
            return
        assert out == out.casefold()

    @given(names)
    def test_whitespace_and_case_are_irrelevant(self, raw):
        """Holds for Latin scripts, which is what the sources emit.

        It is NOT a universal Unicode property and must not be stated as one:
        upper-casing is neither length-preserving nor reversible in general
        (ss/SS, the Greek iota subscript expanding to a full iota, the fi
        ligature). Hypothesis found each of those; none of them is reachable
        from a European club name, so the precondition is the honest fix
        rather than a heroic normalisation nobody benefits from.
        """
        assume(raw.strip())
        try:
            base = normalize_team_name(raw)
        except ValueError:
            return
        assert normalize_team_name(f"  {raw.upper()}  ") == base

    @given(st.lists(names, min_size=1, max_size=4))
    def test_tokenize_never_yields_blank_tokens(self, parts):
        raw = " ".join(parts)
        assume(raw.strip())
        assert all(t for t in tokenize(raw))


class TestKnownUnicodeLimits:
    """The boundary of the case-insensitivity guarantee, stated explicitly."""

    def test_turkish_dotless_i_is_handled(self):
        """Transliterated deliberately: it would otherwise break the invariant."""
        assert normalize_team_name("ı") == normalize_team_name("I") == "i"

    def test_nordic_letters_are_transliterated(self):
        assert normalize_team_name("Brøndby") == "brondby"
        assert normalize_team_name("Łódź") == "lodz"

    def test_non_latin_case_expansion_is_out_of_scope(self):
        """Documented, not fixed: no source emits Greek club names untransliterated."""
        assert normalize_team_name("ᾳ") != normalize_team_name("ᾳ".upper())
