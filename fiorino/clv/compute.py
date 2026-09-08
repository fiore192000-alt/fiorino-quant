"""
Score bets against the reference closing line.

The measurement, not the strategy. M3 answers one question — *did this price
beat the market's final word?* — and answers it honestly, which mostly means
refusing to answer when the comparison is not available.

Three exclusions, all counted rather than silently dropped:

  no_reference_close   the reference book never priced this market
  line_not_matched     it priced a DIFFERENT line; comparing across lines is
                       not a weaker measurement, it is a wrong one
  no_fair_probability  the close exists but its market was incomplete, so it
                       could not be de-vigged
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from fiorino.clv.formulas import beat_close, clv_ev, clv_log, clv_price
from fiorino.config.registries import reference_bookmaker

__all__ = ["ClvResult", "compute_clv", "record_bet", "bet_id_for"]


@dataclass
class ClvResult:
    scored: int = 0
    excluded: int = 0
    no_reference_close: int = 0
    line_not_matched: int = 0
    no_fair_probability: int = 0

    @property
    def total(self) -> int:
        return self.scored + self.excluded

    @property
    def scored_fraction(self) -> float:
        return self.scored / self.total if self.total else 0.0


def bet_id_for(run_id, match_id, bookmaker_id, market_type, line, selection, precision) -> str:
    payload = "|".join(
        str(x) for x in (run_id, match_id, bookmaker_id, market_type, line, selection, precision)
    )
    return "b_" + hashlib.blake2b(payload.encode(), digest_size=12).hexdigest()


def record_bet(
    con, *, run_id, match_id, bookmaker_id, market_type, line, selection,
    price_taken, price_precision, placed_at=None, observed_before=None,
    model_prob=None, note=None,
) -> str:
    """Add one bet to the measurement ledger.

    `placed_at` must be None unless the price was TIMESTAMPED. The schema
    enforces it; this is the friendly failure.
    """
    if (price_precision == "TIMESTAMPED") != (placed_at is not None):
        raise ValueError(
            "placed_at is set exactly when the price is TIMESTAMPED; a bet "
            "struck at an untimestamped price has no known instant"
        )
    bid = bet_id_for(run_id, match_id, bookmaker_id, market_type, line, selection, price_precision)
    if con.execute("SELECT 1 FROM bets WHERE bet_id = ?", [bid]).fetchone():
        return bid
    con.execute(
        """INSERT INTO bets
           (bet_id, run_id, match_id, bookmaker_id, market_type, line, selection,
            price_taken, price_precision, placed_at, observed_before, model_prob, note)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [bid, run_id, match_id, bookmaker_id, market_type, float(line), selection,
         float(price_taken), price_precision, placed_at, observed_before, model_prob, note],
    )
    return bid


def compute_clv(con, run_id: str | None = None) -> ClvResult:
    """Score every unscored bet against the reference book's de-vigged close.

    Measured against the REFERENCE book, never against the book the bet was
    struck with: comparing a soft book to itself measures nothing.
    """
    reference = reference_bookmaker()
    result = ClvResult()

    where = "WHERE c.bet_id IS NULL" + (" AND b.run_id = ?" if run_id else "")
    params = [run_id] if run_id else []

    rows = con.execute(
        f"""SELECT b.bet_id, b.match_id, b.market_type, b.line, b.selection, b.price_taken,
                   r.closing_price, r.closing_fair_prob, r.closing_basis,
                   EXISTS (SELECT 1 FROM reference_market x
                           WHERE x.match_id = b.match_id) AS has_any_close
            FROM bets b
            LEFT JOIN bet_clv c ON c.bet_id = b.bet_id
            LEFT JOIN reference_market r
                   ON  r.match_id    = b.match_id
                   AND r.market_type = b.market_type
                   AND r.line        = b.line
                   AND r.selection   = b.selection
            {where}""",
        params,
    ).fetchall()

    payload = []
    for (bid, match_id, market, line, selection, price,
         close_price, close_fair, basis, has_any_close) in rows:

        if close_price is None:
            reason = "line_not_matched" if has_any_close else "no_reference_close"
            if has_any_close:
                result.line_not_matched += 1
            else:
                result.no_reference_close += 1
            result.excluded += 1
            payload.append([bid, reference, None, None, None,
                            None, None, None, None, False, reason])
            continue

        if close_fair is None:
            result.no_fair_probability += 1
            result.excluded += 1
            payload.append([bid, reference, close_price, None, basis,
                            clv_price(price, close_price), None, None,
                            beat_close(price, close_price), False, "no_fair_probability"])
            continue

        result.scored += 1
        payload.append([
            bid, reference, close_price, close_fair, basis,
            clv_price(price, close_price),
            clv_ev(close_fair, price),
            clv_log(close_fair, price),
            beat_close(price, close_price),
            True, None,
        ])

    if payload:
        con.executemany(
            """INSERT INTO bet_clv
               (bet_id, ref_bookmaker_id, closing_price, closing_fair_prob, closing_basis,
                clv_price, clv_ev, clv_log, beat_close, line_matched, exclusion_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            payload,
        )
    return result
