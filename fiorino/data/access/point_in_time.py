"""
The point-in-time reader — enforcement of schema rule R1.

This is the ONLY sanctioned way for a model, a strategy or a backtest to read
history. Every method is bounded by ``as_of``; there is deliberately no method
that returns unbounded data, so a caller cannot accidentally see the future.

The guard is structural rather than advisory: a test asserts that no module
under fiorino/strategy, fiorino/backtest or fiorino/models names a raw table.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

__all__ = ["PointInTimeView"]


@dataclass(frozen=True)
class PointInTimeView:
    """A read-only window onto everything knowable at ``as_of``."""

    con: object
    as_of: datetime

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware; naive timestamps hide bugs")

    # -- reads --------------------------------------------------------
    def results(self, competition_id: str | None = None) -> list[dict]:
        """Every result knowable at ``as_of``. Training data, and nothing more."""
        sql = "SELECT * FROM results_as_of(?)"
        params = [self.as_of]
        if competition_id:
            sql += " WHERE competition_id = ?"
            params.append(competition_id)
        sql += " ORDER BY settled_at, match_id"
        return self._rows(sql, params)

    def upcoming_matches(self, competition_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM upcoming_matches_as_of(?)"
        params = [self.as_of]
        if competition_id:
            sql += " WHERE competition_id = ?"
            params.append(competition_id)
        sql += " ORDER BY kickoff_utc, match_id"
        return self._rows(sql, params)

    def team_membership(self) -> list[dict]:
        return self._rows(
            "SELECT * FROM team_membership_as_of(?) ORDER BY team_id, competition_id",
            [self.as_of],
        )

    def teams_seen(self, competition_id: str, season_id: str) -> set[str]:
        rows = self._rows(
            """SELECT DISTINCT team_id FROM team_membership_as_of(?)
               WHERE competition_id = ? AND season_id = ?""",
            [self.as_of, competition_id, season_id],
        )
        return {r["team_id"] for r in rows}

    def advance_to(self, new_as_of: datetime) -> "PointInTimeView":
        """A view further forward in time. Never backwards."""
        if new_as_of < self.as_of:
            raise ValueError("a point-in-time view cannot move backwards")
        return PointInTimeView(self.con, new_as_of)

    # -- internals ----------------------------------------------------
    def _rows(self, sql: str, params: list) -> list[dict]:
        rel = self.con.execute(sql, params)
        cols = [d[0] for d in rel.description]
        return [dict(zip(cols, r)) for r in rel.fetchall()]

    @classmethod
    def at(cls, con, as_of) -> "PointInTimeView":
        if isinstance(as_of, str):
            as_of = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        return cls(con, as_of)
