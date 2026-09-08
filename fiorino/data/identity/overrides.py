"""Human identity decisions. Append-only, attributed, highest precedence."""

from __future__ import annotations

from fiorino.core.ids import override_id

__all__ = ["add_override", "list_overrides"]


def add_override(
    con, alias_raw: str, country: str, team_id: str, reason: str, created_by: str,
    source: str = "*", resolver=None,
) -> str:
    """Bind a raw name to a team by human decision.

    Pass ``resolver`` when one is live so its cache is invalidated; otherwise a
    long-running ingest would keep resolving against the pre-override answer.

    ``source='*'`` applies to every source, which is the usual case: a human
    who has decided that "Nott'm Forest" is Nottingham Forest has decided it
    for all of them.
    """
    if not reason.strip():
        raise ValueError("an override needs a reason; the audit trail depends on it")
    if not created_by.strip():
        raise ValueError("an override needs an author")
    exists = con.execute("SELECT 1 FROM teams WHERE team_id = ?", [team_id]).fetchone()
    if not exists:
        raise ValueError(f"cannot override onto unknown team {team_id}")

    oid = override_id(alias_raw, source, country)
    already = con.execute(
        "SELECT team_id FROM team_identity_overrides WHERE override_id = ?", [oid]
    ).fetchone()
    if already:
        if already[0] != team_id:
            raise ValueError(
                f"override {oid} already binds {alias_raw!r} to {already[0]}; "
                "overrides are append-only, add a new alias instead of rebinding"
            )
        return oid
    con.execute(
        """INSERT INTO team_identity_overrides
           (override_id, alias_raw, source, country, team_id, reason, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [oid, alias_raw, source, country, team_id, reason, created_by],
    )
    if resolver is not None:
        resolver.invalidate()
    return oid


def list_overrides(con) -> list[dict]:
    rel = con.execute(
        "SELECT * FROM team_identity_overrides ORDER BY created_at, override_id"
    )
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]
