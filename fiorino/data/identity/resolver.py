"""
Identity resolution — the precedence ladder.

    1. team_identity_overrides    human, deterministic, always wins
    2. exact on raw name + source
    3. exact on normalized name + country
    4. fuzzy                      PROPOSAL ONLY, never applied
    5. unresolved                 caller must block

Rule 9 is absolute and is enforced here rather than by convention: a
resolution whose ``approved`` flag is False can never be turned into a silver
row. ``Resolution.team_id`` is populated for a fuzzy proposal so the audit can
show what was suggested, but ``approved`` stays False and the ingest writer
refuses it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from fiorino.core.ids import new_team_id, proposal_id
from .fuzzy import rank_candidates
from .normalize import normalize_team_name

__all__ = ["MatchMethod", "Resolution", "IdentityResolver"]


class MatchMethod(str, Enum):
    OVERRIDE = "OVERRIDE"
    EXACT_RAW = "EXACT_RAW"
    EXACT_NORMALIZED = "EXACT_NORMALIZED"
    FUZZY_PROPOSAL = "FUZZY_PROPOSAL"
    UNRESOLVED = "UNRESOLVED"
    SEED = "SEED"


@dataclass(frozen=True)
class Resolution:
    """The outcome of resolving one raw name."""

    raw_name: str
    source: str
    country: str
    team_id: str | None
    method: MatchMethod
    confidence: float
    #: The only field the ingest writer is allowed to act on. False for
    #: anything fuzzy or unresolved.
    approved: bool
    #: True when this name genuinely has no identity yet and a caller in
    #: seeding mode may mint one. False when the name is merely *ambiguous* —
    #: a homonym, or a fuzzy candidate awaiting adjudication — because minting
    #: a team there would create the duplicate the whole layer exists to
    #: prevent. An explicit flag, never inferred from the note text.
    can_register: bool = False
    proposal_id: str | None = None
    note: str | None = None

    @property
    def blocks_pipeline(self) -> bool:
        return not self.approved


class IdentityResolver:
    """Resolves raw source names to canonical team ids against a database."""

    def __init__(self, con, *, fuzzy_threshold: float = 0.80):
        self.con = con
        self.fuzzy_threshold = fuzzy_threshold
        # The same handful of names recurs across thousands of rows. The cache
        # is invalidated by every write path below, so a newly approved alias
        # takes effect immediately rather than at the next process.
        self._cache: dict[tuple[str, str, str], Resolution] = {}

    def invalidate(self) -> None:
        self._cache.clear()

    # -- lookups ------------------------------------------------------
    def _override(self, raw: str, source: str, country: str) -> str | None:
        row = self.con.execute(
            """SELECT team_id FROM team_identity_overrides
               WHERE alias_raw = ? AND country = ? AND source IN (?, '*')
               ORDER BY CASE WHEN source = ? THEN 0 ELSE 1 END, created_at DESC
               LIMIT 1""",
            [raw, country, source, source],
        ).fetchone()
        return row[0] if row else None

    def _exact_raw(self, raw: str, source: str, country: str) -> str | None:
        row = self.con.execute(
            """SELECT team_id FROM team_aliases
               WHERE alias_raw = ? AND source = ? AND country = ? AND status = 'APPROVED'""",
            [raw, source, country],
        ).fetchone()
        return row[0] if row else None

    def _exact_normalized(self, raw: str, country: str) -> list[str]:
        norm = normalize_team_name(raw)
        rows = self.con.execute(
            """SELECT DISTINCT team_id FROM team_aliases
               WHERE alias_normalized = ? AND country = ? AND status = 'APPROVED'""",
            [norm, country],
        ).fetchall()
        return [r[0] for r in rows]

    def _country_candidates(self, country: str) -> list[tuple[str, str]]:
        return self.con.execute(
            "SELECT team_id, canonical_name FROM teams WHERE country = ?", [country]
        ).fetchall()

    # -- resolution ---------------------------------------------------
    def resolve(self, raw_name: str, source: str, country: str) -> Resolution:
        raw = str(raw_name).strip()
        if not raw:
            raise ValueError("cannot resolve an empty team name")

        key = (raw, source, country)
        if key in self._cache:
            return self._cache[key]
        resolution = self._resolve_uncached(raw, source, country)
        self._cache[key] = resolution
        return resolution

    def _resolve_uncached(self, raw: str, source: str, country: str) -> Resolution:
        team_id = self._override(raw, source, country)
        if team_id:
            return Resolution(raw, source, country, team_id, MatchMethod.OVERRIDE, 1.0, True)

        team_id = self._exact_raw(raw, source, country)
        if team_id:
            return Resolution(raw, source, country, team_id, MatchMethod.EXACT_RAW, 1.0, True)

        matches = self._exact_normalized(raw, country)
        if len(matches) == 1:
            return Resolution(
                raw, source, country, matches[0], MatchMethod.EXACT_NORMALIZED, 1.0, True
            )
        if len(matches) > 1:
            # Two distinct teams share a normalised name in one country. This
            # is exactly the homonym case, and only a human can settle it.
            return Resolution(
                raw, source, country, None, MatchMethod.UNRESOLVED, 0.0, False,
                can_register=False,
                note=f"normalised name is ambiguous across team_ids {sorted(matches)}; "
                     f"an override is required",
            )

        candidates = rank_candidates(
            raw, self._country_candidates(country), min_score=self.fuzzy_threshold
        )
        # A candidate a human already rejected must not be re-proposed for ever.
        # Without this the name stays wedged at FUZZY_PROPOSAL and can never be
        # registered as the distinct club it actually is — which, on real data,
        # is the common case: every proposal openfootball generates is a pair
        # that must stay separate (Manchester United vs Manchester City at
        # 0.926, Sporting Braga vs Sporting CP at 0.935).
        rejected = {
            r[0] for r in self.con.execute(
                """SELECT candidate_team_id FROM team_alias_proposals
                   WHERE alias_raw = ? AND source = ? AND country = ?
                     AND status = 'REJECTED'""",
                [raw, source, country],
            ).fetchall()
        }
        candidates = [c for c in candidates if c.team_id not in rejected]
        if candidates:
            best = candidates[0]
            pid = proposal_id(raw, source, country, best.team_id)
            return Resolution(
                raw, source, country, best.team_id, MatchMethod.FUZZY_PROPOSAL,
                best.score, False, can_register=False, proposal_id=pid,
                note=f"fuzzy suggestion {best.canonical_name!r} at {best.score:.3f}; "
                     f"quarantined pending approval",
            )

        note = (
            "fuzzy candidates were all rejected by hand; this is a distinct club"
            if rejected else "no candidate above the fuzzy threshold"
        )
        return Resolution(
            raw, source, country, None, MatchMethod.UNRESOLVED, 0.0, False,
            can_register=True, note=note,
        )

    # -- writes -------------------------------------------------------
    def record_proposal(self, res: Resolution, ingestion_run_id: str | None = None) -> None:
        """File a fuzzy suggestion in quarantine. Never touches team_aliases."""
        if res.method is not MatchMethod.FUZZY_PROPOSAL:
            raise ValueError("only fuzzy resolutions produce proposals")
        exists = self.con.execute(
            "SELECT 1 FROM team_alias_proposals WHERE proposal_id = ?", [res.proposal_id]
        ).fetchone()
        if exists:
            return
        self.con.execute(
            """INSERT INTO team_alias_proposals
               (proposal_id, alias_raw, source, country, alias_normalized,
                candidate_team_id, score, method, status, ingestion_run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PROPOSED', ?)""",
            [res.proposal_id, res.raw_name, res.source, res.country,
             normalize_team_name(res.raw_name), res.team_id, res.confidence,
             "FUZZY", ingestion_run_id],
        )

    def register_team(
        self, canonical_name: str, country: str, *, ingestion_run_id: str | None = None
    ) -> str:
        """Mint a new canonical team. Seeding and approved decisions only."""
        team_id = new_team_id()
        self.invalidate()
        self.con.execute(
            "INSERT INTO teams (team_id, canonical_name, country, created_by_run) VALUES (?, ?, ?, ?)",
            [team_id, canonical_name, country, ingestion_run_id],
        )
        return team_id

    def add_alias(
        self, raw: str, source: str, country: str, team_id: str,
        method: MatchMethod = MatchMethod.SEED, *, ingestion_run_id: str | None = None,
    ) -> None:
        """Approve a name for a team. Fuzzy can never reach this method."""
        if method is MatchMethod.FUZZY_PROPOSAL:
            raise ValueError(
                "a fuzzy proposal cannot become an alias directly; approve it first"
            )
        existing = self.con.execute(
            "SELECT team_id FROM team_aliases WHERE alias_raw = ? AND source = ? AND country = ?",
            [raw, source, country],
        ).fetchone()
        if existing:
            if existing[0] != team_id:
                raise ValueError(
                    f"alias collision: {raw!r} from {source}/{country} is already "
                    f"bound to {existing[0]}, refusing to rebind to {team_id}"
                )
            return
        self.invalidate()
        self.con.execute(
            """INSERT INTO team_aliases
               (alias_raw, source, country, alias_normalized, team_id,
                match_method, confidence, status, ingestion_run_id)
               VALUES (?, ?, ?, ?, ?, ?, 1.0, 'APPROVED', ?)""",
            [raw, source, country, normalize_team_name(raw), team_id,
             method.value, ingestion_run_id],
        )

    def approve_proposal(self, pid: str, decided_by: str, note: str = "") -> str:
        """Promote a quarantined proposal into an approved alias."""
        row = self.con.execute(
            """SELECT alias_raw, source, country, candidate_team_id, status
               FROM team_alias_proposals WHERE proposal_id = ?""", [pid]
        ).fetchone()
        if not row:
            raise KeyError(f"no such proposal: {pid}")
        raw, source, country, team_id, status = row
        if status != "PROPOSED":
            raise ValueError(f"proposal {pid} is already {status}")
        self.add_alias(raw, source, country, team_id, MatchMethod.OVERRIDE)
        self.invalidate()
        self.con.execute(
            """UPDATE team_alias_proposals
               SET status='APPROVED', decided_by=?, decided_at=now(), decision_note=?
               WHERE proposal_id = ?""", [decided_by, note, pid],
        )
        return team_id

    def reject_proposal(self, pid: str, decided_by: str, note: str = "") -> None:
        self.invalidate()
        self.con.execute(
            """UPDATE team_alias_proposals
               SET status='REJECTED', decided_by=?, decided_at=now(), decision_note=?
               WHERE proposal_id = ?""", [decided_by, note, pid],
        )
