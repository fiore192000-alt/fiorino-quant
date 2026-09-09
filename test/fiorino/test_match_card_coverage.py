"""
The match-card coverage table, tied to the code it describes.

docs/research/MATCH_CARD_COVERAGE.md says two blocks out of nine can be filled
today and that the other six close with one input. Both halves are claims about
this repository, and both would quietly become false the moment a source is
ingested or a signal family is promoted — which is exactly when a stale
"DATA_GAP" would be most misleading, because it would understate progress
instead of overstating it.

So the document's premises are asserted here, not in prose.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs/research/MATCH_CARD_COVERAGE.md"
MIGRATION = REPO / "fiorino/data/db/migrations/0016_market_path.sql"


def test_no_signal_family_has_been_promoted():
    """Block 8 reads NO_SIGNAL because PROMOTED is empty. If a family is ever
    promoted this fails, and the table has to be rewritten rather than left
    saying nothing has replicated."""
    from fiorino.decision.signal import PROMOTED

    assert PROMOTED == {}, (
        "a signal family was promoted; MATCH_CARD_COVERAGE.md block 8 is stale"
    )


def test_the_market_views_still_require_a_real_instant():
    """Blocks 2-4 are DATA_GAP because these views filter on TIMESTAMPED. If
    that filter were ever relaxed the views would fill up with prices carrying
    no instant, which is the failure the whole point-in-time rule exists to
    prevent — and the table would be wrong for the worst possible reason."""
    sql = MIGRATION.read_text()
    assert sql.count("capture_precision = 'TIMESTAMPED'") == 4


def test_lineups_cannot_be_stored_without_a_publication_instant():
    """Block 5. `published_at` carries no default on purpose: a lineup without
    a known_at cannot be inserted at all, rather than being inserted with a
    fabricated one."""
    sql = (REPO / "fiorino/data/db/migrations/0014_lineups.sql").read_text()
    declaration = re.search(r"published_at\s+TIMESTAMPTZ[^,\n]*", sql)
    assert declaration, "published_at is no longer declared in the lineups table"
    assert "NOT NULL" in declaration.group(0)
    assert "DEFAULT" not in declaration.group(0).upper()


def test_the_document_does_not_present_the_model_edge_as_usable():
    """Block 7 is the only filled block that can do harm."""
    text = DOC.read_text()
    assert "disponibile e fuorviante" in text
