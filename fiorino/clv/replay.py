"""
Replay instruments — ways to populate the measurement ledger without a model.

These are NOT strategies. They exist so the CLV machinery can be validated,
and so later work has a baseline to beat. Each answers a question that is
interesting on its own:

  take_prematch   Struck the pre-match price on every selection. Does the line
                  drift in your favour on average? Expected: no. The close is
                  the more efficient price, so an indiscriminate pre-match
                  taker should show CLV near zero and slightly negative once
                  the market's own margin is accounted for. If this comes out
                  strongly positive, the pipeline is wrong, not the market.

  take_closing    Struck the closing price itself. CLV must be almost exactly
                  the negative of the closing overround, by construction. It
                  is the calibration check: a number we can predict in advance.
"""

from __future__ import annotations

from fiorino.clv.compute import record_bet

__all__ = ["take_prematch", "take_closing", "take_selection"]


def _observations(con, precision, selection=None, market_type="ONE_X_TWO"):
    sql = """SELECT o.match_id, o.bookmaker_id, o.market_type, o.line, o.selection,
                    o.price_decimal, o.observed_before
             FROM odds_observations o
             JOIN v_analytic_matches m ON m.match_id = o.match_id
             WHERE o.capture_precision = ? AND o.market_type = ?"""
    params = [precision, market_type]
    if selection:
        sql += " AND o.selection = ?"
        params.append(selection)
    return con.execute(sql + " ORDER BY o.match_id, o.selection", params).fetchall()


def _replay(con, run_id, precision, selection=None, market_type="ONE_X_TWO", note=None) -> int:
    n = 0
    for match_id, book, market, line, sel, price, before in _observations(
        con, precision, selection, market_type
    ):
        record_bet(
            con, run_id=run_id, match_id=match_id, bookmaker_id=book,
            market_type=market, line=line, selection=sel, price_taken=price,
            price_precision=precision, observed_before=before, note=note,
        )
        n += 1
    return n


def take_prematch(con, run_id="replay_prematch", selection=None) -> int:
    """Take every pre-match price. The baseline every model must beat."""
    return _replay(con, run_id, "PREMATCH", selection,
                   note="replay instrument, not a strategy")


def take_closing(con, run_id="replay_closing", selection=None) -> int:
    """Take the closing price itself. CLV must equal minus the overround."""
    return _replay(con, run_id, "CLOSING", selection,
                   note="calibration check: CLV should be -overround")


def take_selection(con, selection: str, run_id=None, precision="PREMATCH") -> int:
    """Take one side everywhere — always the home team, say."""
    return _replay(con, run_id or f"replay_{selection.lower()}", precision, selection,
                   note=f"replay instrument: always {selection}")
