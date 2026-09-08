"""
Closing Line Value — the arithmetic, isolated.

Three numbers, all measured against the REFERENCE book's de-vigged closing
price for the identical (market_type, line, selection). Never against the book
the bet was struck with: comparing a soft book to itself measures nothing.

Pure specification: no IO, no database. The M3 module will wrap these.
"""

from __future__ import annotations

import math

__all__ = ["clv_price", "clv_ev", "clv_log", "beat_close"]


def _check(price_taken: float, *, closing_price: float | None = None) -> None:
    if price_taken <= 1.0:
        raise ValueError(f"price_taken must exceed 1.0, got {price_taken}")
    if closing_price is not None and closing_price <= 1.0:
        raise ValueError(f"closing_price must exceed 1.0, got {closing_price}")


def clv_price(price_taken: float, closing_price: float) -> float:
    """Pure price improvement: ``price_taken / closing_price - 1``.

    Ignores the overround, so it flatters a bet struck against a market with a
    wide margin. Use it for reporting, not for deciding.
    """
    _check(price_taken, closing_price=closing_price)
    return price_taken / closing_price - 1.0


def clv_ev(closing_fair_prob: float, price_taken: float) -> float:
    """Expected ROI if the closing fair probability is the truth.

    ``closing_fair_prob * price_taken - 1``. The headline number: it is on the
    same scale as yield, so a mean CLV of +2% and a yield of -1% is a
    legible statement about luck rather than two incomparable quantities.
    """
    _check(price_taken)
    if not 0.0 < closing_fair_prob < 1.0:
        raise ValueError(f"closing_fair_prob must lie in (0, 1), got {closing_fair_prob}")
    return closing_fair_prob * price_taken - 1.0


def clv_log(closing_fair_prob: float, price_taken: float) -> float:
    """``ln(closing_fair_prob * price_taken)``.

    Additive across bets, so a sequence of CLVs aggregates without the upward
    bias that the arithmetic mean of ratios carries.
    """
    _check(price_taken)
    if not 0.0 < closing_fair_prob < 1.0:
        raise ValueError(f"closing_fair_prob must lie in (0, 1), got {closing_fair_prob}")
    return math.log(closing_fair_prob * price_taken)


def beat_close(price_taken: float, closing_price: float) -> bool:
    """Whether the struck price was better than the reference close."""
    _check(price_taken, closing_price=closing_price)
    return price_taken > closing_price
