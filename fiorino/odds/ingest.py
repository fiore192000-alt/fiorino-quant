"""
Bronze odds -> odds_observations -> odds_closing -> fair_probabilities.

Three stages, deliberately separate, because each can be wrong in a different
way and each must be inspectable on its own.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta

from fiorino.config.registries import reference_bookmaker
from fiorino.odds.devig import DEFAULT_METHOD, devig

__all__ = ["OddsIngestResult", "ingest_odds", "materialise_closing", "compute_fair_probabilities"]

#: A "closing" price captured long before kickoff is not a close. Football-Data
#: declares its C columns as closing without a clock, so this only bites on
#: TIMESTAMPED sources — but it must exist before one is added, not after.
CLOSING_STALENESS = timedelta(hours=6)


@dataclass
class OddsIngestResult:
    observations: int = 0
    skipped_unknown_match: int = 0
    skipped_unknown_book: int = 0
    closing_rows: int = 0
    fair_rows: int = 0
    devig_failures: int = 0


def _observation_id(match_id, book, market, line, selection, precision, captured_at) -> str:
    payload = "|".join(
        str(x) for x in (match_id, book, market, line, selection, precision, captured_at or "")
    )
    return "o_" + hashlib.blake2b(payload.encode(), digest_size=12).hexdigest()


def ingest_odds(con, bronze_rows, *, ingestion_run_id=None) -> OddsIngestResult:
    """Read the odds carried on bronze match rows into odds_observations.

    Runs AFTER the match transform, so `match_source_ids` already links each
    source row to its canonical match. A row whose match was quarantined is
    skipped: an identity we refused to guess cannot acquire a market, and
    attaching prices to a guess is how a market reconstruction goes wrong
    invisibly.
    """
    result = OddsIngestResult()

    known_books = {r[0] for r in con.execute("SELECT bookmaker_id FROM bookmakers").fetchall()}
    existing = {
        r[0] for r in con.execute("SELECT observation_id FROM odds_observations").fetchall()
    }
    # Resolve (source, source_id) -> canonical match and its kickoff in one pass.
    resolved = {
        (r[0], r[1]): (r[2], r[3])
        for r in con.execute(
            """SELECT si.source, si.source_id, m.match_id, m.kickoff_utc
               FROM match_source_ids si
               JOIN v_analytic_matches m ON m.match_id = si.match_id"""
        ).fetchall()
    }

    payload = []
    for row in bronze_rows:
        odds_json = row.get("odds_json")
        if not odds_json or odds_json == "None":
            continue
        source = row["source"]
        key = (source, str(row.get("source_id")))
        if key not in resolved:
            result.skipped_unknown_match += 1
            continue
        match_id, kickoff = resolved[key]
        for entry in json.loads(odds_json):
            book = entry["bookmaker"]
            if book not in known_books:
                result.skipped_unknown_book += 1
                continue
            precision = entry["capture_precision"]
            # Rule: only TIMESTAMPED carries a clock. Everything else records
            # the bound that IS known — the kickoff — and nothing more.
            captured_at = entry.get("captured_at") if precision == "TIMESTAMPED" else None
            oid = _observation_id(match_id, book, entry["market_type"], entry["line"],
                                  entry["selection"], precision, captured_at)
            if oid in existing:
                continue
            existing.add(oid)
            payload.append([
                oid, match_id, book, entry["market_type"], float(entry["line"]),
                entry["selection"], float(entry["price_decimal"]), precision,
                captured_at, kickoff, source, ingestion_run_id,
            ])

    if payload:
        con.executemany(
            """INSERT INTO odds_observations
               (observation_id, match_id, bookmaker_id, market_type, line, selection,
                price_decimal, capture_precision, captured_at, observed_before,
                source, ingestion_run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            payload,
        )
        result.observations = len(payload)
    return result


def materialise_closing(con) -> int:
    """Establish the closing line for every market.

    Two bases, and the difference is recorded because it matters to M3:

      DECLARED  the source labelled it closing (Football-Data's C columns).
      LATEST    the last timestamped price we hold. Only as good as the poll
                that produced it; a thin poll makes a weak benchmark.

    DECLARED wins wherever both exist.
    """
    con.execute("DELETE FROM odds_closing")
    con.execute(
        """INSERT INTO odds_closing
           (match_id, bookmaker_id, market_type, line, selection, price_decimal,
            observation_id, closing_basis, seconds_to_kickoff, is_trusted)
           SELECT match_id, bookmaker_id, market_type, line, selection,
                  price_decimal, observation_id, 'DECLARED', NULL, TRUE
           FROM odds_observations WHERE capture_precision = 'CLOSING'"""
    )
    con.execute(
        f"""INSERT INTO odds_closing
            (match_id, bookmaker_id, market_type, line, selection, price_decimal,
             observation_id, closing_basis, seconds_to_kickoff, is_trusted)
            SELECT match_id, bookmaker_id, market_type, line, selection,
                   arg_max(price_decimal, captured_at),
                   arg_max(observation_id, captured_at),
                   'LATEST',
                   date_diff('second', max(captured_at), any_value(observed_before)),
                   date_diff('second', max(captured_at), any_value(observed_before))
                       <= {int(CLOSING_STALENESS.total_seconds())}
            FROM odds_observations
            WHERE capture_precision = 'TIMESTAMPED'
              AND (observed_before IS NULL OR captured_at <= observed_before)
              AND NOT EXISTS (
                  SELECT 1 FROM odds_closing c
                  WHERE c.match_id = odds_observations.match_id
                    AND c.bookmaker_id = odds_observations.bookmaker_id
                    AND c.market_type = odds_observations.market_type
                    AND c.line = odds_observations.line
                    AND c.selection = odds_observations.selection)
            GROUP BY match_id, bookmaker_id, market_type, line, selection"""
    )
    return con.execute("SELECT count(*) FROM odds_closing").fetchone()[0]


def compute_fair_probabilities(con, method: str = DEFAULT_METHOD) -> tuple[int, int]:
    """De-vig every complete market. Returns (rows written, markets skipped).

    A market is de-vigged as a whole or not at all. An incomplete one — a 1X2
    missing its draw because the book pulled a price — is skipped and counted,
    never normalised, because normalising two thirds of a market produces a
    confident number that nothing downstream could tell apart from a real one.
    """
    con.execute("DELETE FROM fair_probabilities WHERE devig_method = ?", [method])

    markets = con.execute(
        """SELECT match_id, bookmaker_id, market_type, line, capture_precision,
                  list(selection ORDER BY selection)      AS selections,
                  list(price_decimal ORDER BY selection)  AS prices
           FROM odds_observations
           GROUP BY match_id, bookmaker_id, market_type, line, capture_precision"""
    ).fetchall()

    expected = {"ONE_X_TWO": 3, "BTTS": 2, "TOTALS": 2, "ASIAN_HANDICAP": 2, "DOUBLE_CHANCE": 3}
    payload, skipped = [], 0

    for match_id, book, market, line, precision, selections, prices in markets:
        want = expected.get(market)
        if want is not None and len(selections) != want:
            skipped += 1
            continue
        try:
            result = devig(selections, prices, method)
        except ValueError:
            skipped += 1
            continue
        for selection, fair, raw in zip(result.selections, result.fair_probs, result.raw_implied):
            payload.append([
                match_id, book, market, float(line), selection, precision,
                result.method, fair, raw, result.overround, result.n_selections,
            ])

    if payload:
        con.executemany(
            """INSERT INTO fair_probabilities
               (match_id, bookmaker_id, market_type, line, selection, capture_precision,
                devig_method, fair_prob, raw_implied_prob, overround, n_selections)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            payload,
        )
    return len(payload), skipped


def run_odds_pipeline(con, *, ingestion_run_id=None, method: str = DEFAULT_METHOD) -> OddsIngestResult:
    """The three stages in order."""
    result = ingest_odds(con, ingestion_run_id=ingestion_run_id)
    result.closing_rows = materialise_closing(con)
    result.fair_rows, result.devig_failures = compute_fair_probabilities(con, method)
    return result
