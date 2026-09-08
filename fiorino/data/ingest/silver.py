"""
Bronze -> silver: resolve identity, mint canonical ids, quarantine the rest.

This is the only writer of `teams`, `matches`, `match_results` and the source-id
bridges, so rule 9 has exactly one enforcement point:

    a match whose home or away identity is not APPROVED is written to
    match_quarantine and NOT to matches.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fiorino.core.ids import match_id as make_match_id
from fiorino.core.ids import quarantine_id
from fiorino.data.identity.resolver import IdentityResolver, MatchMethod

from .base import parse_date, parse_ts

__all__ = [
    "TransformResult",
    "transform_bronze",
    "resolve_match_id",
    "merge_matches",
    "MATCH_DURATION",
]

#: How long after kickoff a result is treated as knowable when the source does
#: not say. Conservative on purpose: erring late costs a little training data,
#: erring early is leakage.
MATCH_DURATION = timedelta(hours=2)


@dataclass
class TransformResult:
    matches_written: int = 0
    results_written: int = 0
    teams_created: int = 0
    quarantined: int = 0
    proposals: int = 0
    merged: int = 0

    def __add__(self, other: "TransformResult") -> "TransformResult":
        return TransformResult(
            self.matches_written + other.matches_written,
            self.results_written + other.results_written,
            self.teams_created + other.teams_created,
            self.quarantined + other.quarantined,
            self.proposals + other.proposals,
            self.merged + other.merged,
        )


def resolve_match_id(con, mid: str) -> str:
    """Follow the merge chain to the surviving match id."""
    seen = {mid}
    while True:
        row = con.execute(
            "SELECT surviving_match_id FROM match_merges WHERE merged_match_id = ?", [mid]
        ).fetchone()
        if not row:
            return mid
        mid = row[0]
        if mid in seen:
            raise RuntimeError(f"cycle in match_merges at {mid}")
        seen.add(mid)


def transform_bronze(
    con,
    rows: list[dict],
    *,
    country_of: dict,
    ingestion_run_id: str | None = None,
    resolver: IdentityResolver | None = None,
    auto_register_unknown: bool = False,
) -> TransformResult:
    """Promote bronze rows into the analytic tables.

    ``auto_register_unknown`` is for SEEDING ONLY: it mints a canonical team
    for a name that resolves to nothing. It is off by default because in normal
    operation an unknown name is a decision for a human, not for the pipeline.
    """
    resolver = resolver or IdentityResolver(con)
    out = TransformResult()

    # Preload the existence sets once. Per-row SELECTs turned a 10k-row
    # partition into tens of thousands of round trips; this is the same
    # information in four queries.
    known_matches: dict[str, object] = dict(
        con.execute("SELECT match_id, kickoff_utc FROM matches").fetchall()
    )
    known_source_ids: set = {
        tuple(r) for r in con.execute("SELECT source, source_id FROM match_source_ids").fetchall()
    }
    known_results: set = {
        r[0] for r in con.execute("SELECT match_id FROM match_results").fetchall()
    }
    known_membership: set = {
        tuple(r) for r in con.execute(
            "SELECT team_id, competition_id, season_id FROM team_season_membership").fetchall()
    }
    known_team_source_ids: dict = dict(
        (tuple(r[:2]), r[2]) for r in
        con.execute("SELECT source, source_id, team_id FROM team_source_ids").fetchall()
    )
    known_quarantine: set = {
        r[0] for r in con.execute("SELECT quarantine_id FROM match_quarantine").fetchall()
    }

    for row in rows:
        competition = row["competition"]
        season = row["season"]
        source = row["source"]
        country = country_of.get(competition)
        if country is None:
            raise KeyError(f"no country registered for competition {competition!r}")

        home = resolver.resolve(row["home_name_raw"], source, country)
        away = resolver.resolve(row["away_name_raw"], source, country)

        for side in (home, away):
            if side.method is MatchMethod.FUZZY_PROPOSAL:
                resolver.record_proposal(side, ingestion_run_id)
                out.proposals += 1

        if auto_register_unknown:
            for side_name, side in (("home", home), ("away", away)):
                if side.method is MatchMethod.UNRESOLVED and side.note and "no candidate" in side.note:
                    tid = resolver.register_team(side.raw_name, country, ingestion_run_id=ingestion_run_id)
                    resolver.add_alias(side.raw_name, source, country, tid,
                                       MatchMethod.SEED, ingestion_run_id=ingestion_run_id)
                    out.teams_created += 1
            home = resolver.resolve(row["home_name_raw"], source, country)
            away = resolver.resolve(row["away_name_raw"], source, country)

        # Rule 9. Unapproved identity never reaches `matches`.
        if not (home.approved and away.approved):
            side = ("BOTH" if not home.approved and not away.approved
                    else "HOME" if not home.approved else "AWAY")
            reason = "; ".join(
                filter(None, [
                    None if home.approved else f"home: {home.method.value} {home.note or ''}".strip(),
                    None if away.approved else f"away: {away.method.value} {away.note or ''}".strip(),
                ])
            )
            qid = quarantine_id(source, str(row.get("source_id")),
                                row["home_name_raw"], row["away_name_raw"])
            if qid not in known_quarantine:
                known_quarantine.add(qid)
                con.execute(
                    """INSERT INTO match_quarantine
                       (quarantine_id, source, source_id, competition_id, season_id,
                        match_date_utc, raw_home_name, raw_away_name, unresolved_side,
                        reason, ingestion_run_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [qid, source, str(row.get("source_id")), competition, season,
                     parse_date(row["match_date"]), row["home_name_raw"],
                     row["away_name_raw"], side, reason, ingestion_run_id],
                )
                out.quarantined += 1
            continue

        match_date = parse_date(row["match_date"])
        kickoff = parse_ts(row.get("kickoff_utc"), match_date)
        mid = make_match_id(competition, season, match_date, home.team_id, away.team_id)
        mid = resolve_match_id(con, mid)

        existing = known_matches.get(mid)
        if existing is not None:
            # The same match seen again, possibly with a corrected kickoff time.
            # The correction is appended as a revision rather than written over
            # the row: it keeps the history rule R1 depends on, and it is the
            # only option anyway, since DuckDB refuses to UPDATE a row that a
            # foreign key still references.
            if existing != kickoff:
                con.execute(
                    """INSERT INTO match_kickoff_revisions
                       (match_id, kickoff_utc, source, ingestion_run_id)
                       VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING""",
                    [mid, kickoff, source, ingestion_run_id],
                )
        else:
            con.execute(
                """INSERT INTO matches
                   (match_id, competition_id, season_id, match_date_utc, kickoff_utc,
                    home_team_id, away_team_id, neutral_venue, status, ingestion_run_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [mid, competition, season, match_date, kickoff, home.team_id, away.team_id,
                 str(row.get("neutral_venue") or "").lower() in ("1", "true", "yes"),
                 "FINISHED" if row.get("goals_home") not in (None, "") else "SCHEDULED",
                 ingestion_run_id],
            )
            known_matches[mid] = kickoff
            out.matches_written += 1

        sid = str(row.get("source_id"))
        if sid and (source, sid) not in known_source_ids:
            known_source_ids.add((source, sid))
            con.execute(
                """INSERT INTO match_source_ids (source, source_id, match_id, ingestion_run_id)
                   VALUES (?, ?, ?, ?)""", [source, sid, mid, ingestion_run_id],
            )

        for side, team_id in ((("home"), home.team_id), (("away"), away.team_id)):
            src_team_id = row.get(f"{side}_source_id")
            if src_team_id:
                key = (source, str(src_team_id))
                mapped = known_team_source_ids.get(key)
                if mapped is None:
                    known_team_source_ids[key] = team_id
                    con.execute(
                        "INSERT INTO team_source_ids (source, source_id, team_id) VALUES (?, ?, ?)",
                        [source, str(src_team_id), team_id],
                    )
                elif mapped != team_id:
                    raise ValueError(
                        f"source id collision: {source}:{src_team_id} already maps to "
                        f"{mapped}, cannot remap to {team_id}"
                    )
            mkey = (team_id, competition, season)
            if mkey not in known_membership:
                known_membership.add(mkey)
                con.execute(
                    """INSERT INTO team_season_membership (team_id, competition_id, season_id, source)
                       VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING""",
                    [team_id, competition, season, source],
                )

        if row.get("goals_home") not in (None, "", "None"):
            settled = row.get("result_settled_at")
            if settled:
                settled_at = datetime.fromisoformat(str(settled).replace("Z", "+00:00"))
            else:
                # Rule R1: a result becomes knowable when the match ENDS, not at
                # kickoff. Two hours covers 90 minutes plus stoppage and the
                # reporting lag; sources that give a real timestamp override it.
                settled_at = kickoff + MATCH_DURATION
            if mid not in known_results:
                known_results.add(mid)
                con.execute(
                    """INSERT INTO match_results
                       (match_id, goals_home, goals_away, goals_home_ht, goals_away_ht,
                        settled_at, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    [mid, int(row["goals_home"]), int(row["goals_away"]),
                     _opt_int(row.get("goals_home_ht")), _opt_int(row.get("goals_away_ht")),
                     settled_at, source],
                )
                out.results_written += 1

    return out


def _opt_int(v):
    return None if v in (None, "", "None") else int(v)


def _upsert_team_source_id(con, source, source_id, team_id) -> None:
    row = con.execute(
        "SELECT team_id FROM team_source_ids WHERE source = ? AND source_id = ?",
        [source, source_id],
    ).fetchone()
    if row is None:
        con.execute(
            "INSERT INTO team_source_ids (source, source_id, team_id) VALUES (?, ?, ?)",
            [source, source_id, team_id],
        )
    elif row[0] != team_id:
        raise ValueError(
            f"source id collision: {source}:{source_id} already maps to {row[0]}, "
            f"cannot remap to {team_id}"
        )
    else:
        con.execute(
            "UPDATE team_source_ids SET last_seen_at = now() WHERE source = ? AND source_id = ?",
            [source, source_id],
        )


def merge_matches(con, merged: str, surviving: str, reason: str, created_by: str) -> None:
    """Controlled merge for a correction that crossed a date boundary."""
    if merged == surviving:
        raise ValueError("cannot merge a match into itself")
    if not con.execute("SELECT 1 FROM matches WHERE match_id = ?", [surviving]).fetchone():
        raise ValueError(f"surviving match {surviving} does not exist")
    con.execute(
        """INSERT INTO match_merges (merged_match_id, surviving_match_id, reason, created_by)
           VALUES (?, ?, ?, ?)""", [merged, surviving, reason, created_by],
    )
    con.execute("UPDATE match_source_ids SET match_id = ? WHERE match_id = ?", [surviving, merged])
    con.execute("DELETE FROM match_results WHERE match_id = ?", [merged])
    con.execute("DELETE FROM matches WHERE match_id = ?", [merged])
