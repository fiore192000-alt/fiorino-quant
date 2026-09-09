"""
SportMonks v3 — the first adapter, and the reason it is the first.

WHY THIS SOURCE
---------------
The audit of free sources rejected the alternatives for reasons that are about
terms, not technology:

    football-data.org   free tier carries no lineups at all
    API-Football        free tier is ~100 calls a day; polling needs ~300
    SofaScore/FotMob    unofficial endpoints, terms not read — the same
                        objection this project raised against OddsPortal, and
                        it would be incoherent to raise it there and ignore it
                        here

SportMonks publishes confirmed lineups on its free plan through a documented,
official API with a token the user registers for. Narrow — the free plan
covers two competitions, one of which is the Scottish Premiership — but two
competitions collected honestly beat twelve collected on terms nobody read.

THIS ADAPTER IS UNVERIFIED
--------------------------
No request has ever been made from it. Every external API is blocked by this
environment's egress policy, so the field names below come from the published
API surface and not from a response anyone has seen. That is why
`scripts/record_lineups.py --verify` exists and why the first scheduled run is
a verification run: it reports the shape the API actually returned instead of
assuming this file got it right.

Nothing here fabricates an instant. If the response carries no usable eleven,
the poll records that it found none — which is itself the evidence that makes
the next gap measurable.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from fiorino.data.ingest.lineups.recorder import CONFIRMED, PREDICTED, Lineup, Poll, utcnow

BASE = "https://api.sportmonks.com/v3/football"
#: SportMonks type ids: 11 = lineup (the official eleven), 12 = bench.
#: A response carrying only forecast types is PREDICTED and must not be
#: mistaken for the eleven itself.
STARTER_TYPE_IDS = {11}
TIMEOUT = 30


class SourceError(RuntimeError):
    pass


def _get(path: str, token: str, **params) -> dict:
    params["api_token"] = token
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode())


def _lineups_from_fixture(fixture: dict) -> list[Lineup]:
    """Map one fixture's lineup block. Returns [] when there is nothing to map,
    never a half-populated eleven."""
    match_key = str(fixture.get("id", ""))
    if not match_key:
        return []
    rows = fixture.get("lineups") or []
    by_team: dict[str, list[str]] = {}
    for row in rows:
        if row.get("type_id") not in STARTER_TYPE_IDS:
            continue
        team = row.get("team_id")
        # Explicit None checks, not truthiness: a player_id of 0 is a valid id
        # and an `or` chain silently drops it, producing a ten-man eleven that
        # the >= 11 guard below then discards as a partial response. The eleven
        # would simply never be recorded, and nothing would say why.
        player = row.get("player_id")
        if player is None:
            player = row.get("player_name")
        if team is None or player is None or player == "":
            continue
        team, player = str(team), str(player)
        by_team.setdefault(team, []).append(player)

    # An eleven with fewer than eleven starters is a partially-delivered
    # response, not a small team. Recording it CONFIRMED would set known_at on
    # a fact that had not fully appeared yet.
    return [
        Lineup(match_key=match_key, team=team, status=CONFIRMED,
               players=tuple(sorted(players)))
        for team, players in sorted(by_team.items())
        if len(players) >= 11
    ]


def fetch(token: str, date: str) -> Poll:
    """One poll: every fixture on `date` (YYYY-MM-DD), with its lineups.

    Errors are captured into the Poll rather than raised, because a failed poll
    is data: it is what stops the next sighting from claiming a gap it did not
    close.
    """
    observed_at = utcnow()
    try:
        payload = _get(f"fixtures/date/{date}", token, include="lineups")
    except Exception as exc:  # noqa: BLE001 — every failure is the same fact
        return Poll(source="sportmonks", observed_at=observed_at,
                    scope=(), error=f"{type(exc).__name__}: {exc}")

    fixtures = payload.get("data") or []
    scope = tuple(str(f.get("id")) for f in fixtures if f.get("id"))
    lineups: list[Lineup] = []
    for fixture in fixtures:
        lineups.extend(_lineups_from_fixture(fixture))
    return Poll(source="sportmonks", observed_at=observed_at,
                scope=scope, lineups=tuple(lineups))


__all__ = ["fetch", "SourceError", "PREDICTED"]
