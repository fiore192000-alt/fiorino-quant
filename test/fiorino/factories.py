"""
Deterministic synthetic bronze, built to be nasty in the ways real football
data is nasty.

No network: the offline environment cannot reach football-data.co.uk or
FBref, so the acceptance run exercises the pipeline against generated bronze
rather than scraped bronze. The shape, the name variance and the failure modes
are modelled on the real sources; the volume is reduced (10 clubs per league,
double round robin) so the suite stays fast.

Deliberate hazards planted in the data:

  * per-source name variants     Man United / Manchester Utd / Manchester United
  * same-country homonym         Vitoria Guimaraes vs Vitoria Setubal, one
                                 source emitting a bare "Vitoria" for both
  * cross-country same name      Sporting (PRT) vs Sporting Gijon (ESP)
  * a rename mid-timeline        Milton Keynes Dons -> MK Dons
  * promotion and relegation     one club moving between ENG_PL and ENG_CH
  * a typo triggering fuzzy      "Manchestr United" -> proposal, quarantine
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone

from fiorino.config.registries import COMPETITIONS, SEASONS, SOURCE_COVERAGE
from fiorino.data.ingest.base import RawMatch
from fiorino.data.lake import bronze_path, write_bronze

MATCH_SOURCES = ("footballdata", "fbref", "understat")

#: Canonical squads. Ten per league keeps a double round robin at 90 matches.
SQUADS: dict[str, list[str]] = {
    "ENG_PL": ["Arsenal", "Chelsea", "Liverpool", "Manchester United", "Manchester City",
               "Tottenham Hotspur", "Everton", "Newcastle United", "Aston Villa", "Norwich City"],
    "ENG_CH": ["Leeds United", "Sheffield Wednesday", "Bristol City", "Cardiff City",
               "Hull City", "Preston North End", "Queens Park Rangers", "Swansea City",
               "Milton Keynes Dons", "Luton Town"],
    "ESP_LL": ["Real Madrid", "Barcelona", "Atletico Madrid", "Sevilla", "Valencia",
               "Villarreal", "Real Sociedad", "Athletic Club", "Real Betis", "Sporting Gijon"],
    "ITA_SA": ["Juventus", "Internazionale", "AC Milan", "Napoli", "Roma",
               "Lazio", "Fiorentina", "Atalanta", "Torino", "Sampdoria"],
    "DEU_BL1": ["Bayern Munchen", "Borussia Dortmund", "RB Leipzig", "Bayer Leverkusen",
                "Borussia Monchengladbach", "Werder Bremen", "Schalke 04", "VfB Stuttgart",
                "TSG 1899 Hoffenheim", "1860 Munchen"],
    "FRA_L1": ["Paris Saint Germain", "Marseille", "Lyon", "Monaco", "Lille",
               "Rennes", "Nice", "Saint Etienne", "Bordeaux", "Nantes"],
    "NLD_ED": ["Ajax", "PSV Eindhoven", "Feyenoord", "AZ Alkmaar", "FC Utrecht",
               "Vitesse", "FC Twente", "Heerenveen", "Groningen", "RKC Waalwijk"],
    "PRT_L1": ["Benfica", "Porto", "Sporting CP", "Braga", "Vitoria Guimaraes",
               "Vitoria Setubal", "Maritimo", "Boavista", "Rio Ave", "Pacos de Ferreira"],
}

#: Hand-written per-source variants. Everything not listed falls back to the
#: programmatic rules in `variant_for`.
EXPLICIT_VARIANTS: dict[tuple[str, str], str] = {
    ("Manchester United", "footballdata"): "Man United",
    ("Manchester City", "footballdata"): "Man City",
    ("Tottenham Hotspur", "footballdata"): "Tottenham",
    ("Newcastle United", "footballdata"): "Newcastle",
    ("Queens Park Rangers", "footballdata"): "QPR",
    ("Internazionale", "footballdata"): "Inter",
    ("Bayern Munchen", "footballdata"): "Bayern Munich",
    ("Borussia Monchengladbach", "footballdata"): "M'gladbach",
    ("TSG 1899 Hoffenheim", "footballdata"): "Hoffenheim",
    ("Paris Saint Germain", "footballdata"): "Paris SG",
    ("PSV Eindhoven", "footballdata"): "PSV",
    ("Sporting CP", "footballdata"): "Sp Lisbon",
    ("Sporting Gijon", "footballdata"): "Sp Gijon",
    ("Pacos de Ferreira", "footballdata"): "Pacos Ferreira",
    ("Manchester United", "understat"): "Manchester Utd",
    ("Internazionale", "understat"): "Inter Milan",
    ("Bayern Munchen", "understat"): "Bayern Munich",
    ("Athletic Club", "understat"): "Athletic Bilbao",
}

#: The rename. Same club, a materially different name from 2019-2020 on, so
#: exact and normalised matching both miss and a human override is required.
RENAMES: dict[str, tuple[str, str]] = {
    "Milton Keynes Dons": ("MK Dons", "2019-2020"),
}

#: Promotion and relegation: the two swap divisions from 2019-2020.
PROMOTED, RELEGATED, SWAP_SEASON = "Luton Town", "Norwich City", "2019-2020"

#: A typo one source emits for a single season. Fuzzy will suggest it;
#: nothing may accept it automatically.
TYPO_SEASON = "2017-2018"
TYPO = ("Manchester United", "Manchestr United", "fbref", "ENG_PL")


def variant_for(canonical: str, source: str, season: str) -> str:
    """The name a given source uses for a club in a given season."""
    if canonical in RENAMES:
        new_name, from_season = RENAMES[canonical]
        if season >= from_season:
            canonical = new_name
    if (canonical, source) in EXPLICIT_VARIANTS:
        return EXPLICIT_VARIANTS[(canonical, source)]
    if source == "footballdata":
        return canonical.replace(" United", " Utd").replace(" Wanderers", "")
    return canonical


def squad_for(competition_id: str, season: str) -> list[str]:
    """The squad, after applying promotion and relegation."""
    squad = list(SQUADS[competition_id])
    if competition_id == "ENG_PL" and season >= SWAP_SEASON:
        squad[squad.index(RELEGATED)] = PROMOTED
    if competition_id == "ENG_CH" and season >= SWAP_SEASON:
        squad[squad.index(PROMOTED)] = RELEGATED
    return squad


def _fixture_dates(season: str, n: int) -> list[date]:
    start = date(int(season.split("-")[0]), 8, 12)
    return [start + timedelta(days=7 * (i % 38)) for i in range(n)]


def generate_matches(competition_id: str, season: str, source: str, seed: int = 0) -> list[RawMatch]:
    """A double round robin for one competition-season as one source sees it."""
    squad = squad_for(competition_id, season)
    rng = random.Random(f"{competition_id}|{season}|{seed}")

    pairings = [(h, a) for h in squad for a in squad if h != a]
    pairings.sort()
    dates = _fixture_dates(season, len(pairings))

    rows: list[RawMatch] = []
    for idx, ((home, away), match_date) in enumerate(zip(pairings, dates)):
        home_raw = variant_for(home, source, season)
        away_raw = variant_for(away, source, season)

        # Plant the typo in exactly one source, competition and season.
        canonical, typo, typo_source, typo_comp = TYPO
        if source == typo_source and competition_id == typo_comp and season == TYPO_SEASON:
            if home == canonical:
                home_raw = typo
            if away == canonical:
                away_raw = typo

        gh, ga = rng.randint(0, 4), rng.randint(0, 3)
        kickoff = datetime.combine(match_date, time(15, 0), tzinfo=timezone.utc)
        rows.append(
            RawMatch(
                source=source,
                source_id=f"{source}:{competition_id}:{season}:{idx:04d}",
                competition=competition_id,
                season=season,
                match_date=match_date.isoformat(),
                kickoff_utc=kickoff.isoformat(),
                home_name_raw=home_raw,
                away_name_raw=away_raw,
                goals_home=str(gh),
                goals_away=str(ga),
                goals_home_ht=str(min(gh, rng.randint(0, 2))),
                goals_away_ht=str(min(ga, rng.randint(0, 2))),
                home_source_id=f"{source}-{abs(hash(home)) % 100000}",
                away_source_id=f"{source}-{abs(hash(away)) % 100000}",
                neutral_venue="false",
                result_settled_at=(kickoff + timedelta(hours=2)).isoformat(),
            )
        )
    return rows


def build_bronze(
    con, root, *, competitions=None, seasons=None, sources=MATCH_SOURCES
) -> int:
    """Write the whole synthetic lake. Returns rows written."""
    competitions = competitions or list(COMPETITIONS)
    seasons = seasons or list(SEASONS)
    written = 0
    for source in sources:
        covered = SOURCE_COVERAGE.get(source, {})
        for competition_id in competitions:
            if competition_id not in covered:
                continue  # honest gap: Understat does not publish this league
            for season in seasons:
                rows = generate_matches(competition_id, season, source)
                target = bronze_path(root, source, competition_id, season, "seed")
                write_bronze(con, [r.as_row() for r in rows], target)
                written += len(rows)
    return written


def seed_identity(con, resolver, *, competitions=None, seasons=None, sources=MATCH_SOURCES):
    """Register canonical teams and their approved aliases.

    Mirrors what an operator does once per league: create the club, then
    approve the name each source uses for it. The rename and the typo are
    deliberately NOT seeded, so the tests can watch the pipeline handle them.
    """
    competitions = competitions or list(COMPETITIONS)
    seasons = seasons or list(SEASONS)
    country = {cid: meta[1] for cid, meta in COMPETITIONS.items()}

    canonical_to_id: dict[tuple[str, str], str] = {}
    for competition_id in competitions:
        ctry = country[competition_id]
        # Union across seasons, not the base squad: a promoted club plays in a
        # division whose base squad never listed it, and an operator seeding a
        # league seeds everyone who actually appears in it.
        squad = sorted({t for s in seasons for t in squad_for(competition_id, s)})
        for canonical in squad:
            key = (canonical, ctry)
            if key not in canonical_to_id:
                canonical_to_id[key] = resolver.register_team(canonical, ctry)
            team_id = canonical_to_id[key]
            for source in sources:
                if competition_id not in SOURCE_COVERAGE.get(source, {}):
                    continue
                for season in seasons:
                    alias = variant_for(canonical, source, season)
                    if canonical in RENAMES and alias == RENAMES[canonical][0]:
                        continue  # the rename must be resolved, not pre-seeded
                    try:
                        resolver.add_alias(alias, source, ctry, team_id)
                    except ValueError:
                        pass  # alias already bound to this team
    return canonical_to_id
