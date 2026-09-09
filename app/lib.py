"""Shared plumbing for the dashboard. No decision logic lives here."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import streamlit as st

from fiorino.data.db.connection import connect
from fiorino.data.db.migrate import migrate
from fiorino.data.identity.resolver import IdentityResolver
from fiorino.data.ingest.sources.footballdata import FootballData
from fiorino.data.lake import bronze_path, write_bronze
from fiorino.data.pipeline import bootstrap_reference, ingest_bronze
from fiorino.decision.signal import PROMOTED
from scripts.validate_clv import DATASETS, fetch

__all__ = ["DATASETS", "build_warehouse", "git_commit", "system_status"]


def git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "sconosciuto"
    except Exception:
        return "sconosciuto"


@st.cache_resource(show_spinner=False)
def build_warehouse(label: str):
    """Fetch one real league-season and build the warehouse in memory.

    Cached per label: the walk is deterministic, so rebuilding on every rerun
    would only cost time. Identity proposals are rejected rather than approved,
    which is the conservative choice — an unadjudicated club stays out of the
    analytic dataset instead of being merged on a similarity score.
    """
    entry = next(d for d in DATASETS if d[0] == label)
    _, competition_id, season_id, url = entry

    con = connect()
    migrate(con)
    bootstrap_reference(con)
    # Una directory nuova a ogni costruzione. Il bronze e immutabile per
    # progetto — riscrivere lo stesso run id solleva FileExistsError — e un
    # percorso fisso faceva schiantare l'app al secondo caricamento. La cache
    # rende questo raro, ma "raro" non e "mai": un riavvio del container basta.
    root = Path(tempfile.mkdtemp(prefix="fiorino-app-"))
    rows = FootballData().parse(fetch(url), competition_id, season_id)
    write_bronze(con, [r.as_row() for r in rows],
                 bronze_path(root, "footballdata", competition_id, season_id, "app"))
    ingest_bronze(con, root, auto_register_unknown=True)
    for _ in range(6):
        open_props = con.execute(
            "SELECT proposal_id FROM team_alias_proposals WHERE status='PROPOSED'"
        ).fetchall()
        if not open_props:
            break
        resolver = IdentityResolver(con)
        for (pid,) in open_props:
            resolver.reject_proposal(pid, "app", "club distinto")
        con.execute("DELETE FROM match_quarantine")
        ingest_bronze(con, root, auto_register_unknown=True)
    return con


@st.cache_data(show_spinner=False)
def system_status() -> dict:
    con = connect()
    migrate(con)
    migrations = Path(__file__).resolve().parent.parent / "fiorino/data/db/migrations"
    status = {
        "commit": git_commit(),
        "n_tables": con.execute("SELECT count(*) FROM duckdb_tables()").fetchone()[0],
        "n_views": con.execute(
            "SELECT count(*) FROM duckdb_views() WHERE NOT internal").fetchone()[0],
        "n_migrations": len(list(migrations.glob("*.sql"))),
        "promoted_strategies": dict(PROMOTED),
    }
    con.close()
    return status


BADGE = {"DATA_GAP": "⬛", "NO_SIGNAL": "⚪", "WATCH": "🔵",
         "CANDIDATE": "🟡", "QUALIFIED": "🟢"}


def evidence_card(title: str, decision, score=None, *, facts=None):
    """The card a person reads before deciding not to act.

    Two halves, and the second is the one that matters: WHY NOT. A card that
    only lists supporting evidence is an advertisement.
    """
    with st.container(border=True):
        st.markdown(f"### {BADGE[decision.level]} {decision.level}")
        st.caption(title)

        for key, value in (facts or {}).items():
            st.markdown(f"**{key}** {value}")

        if score is not None and score.scorable:
            st.progress(min(max(score.value, 0.0), 1.0),
                        text=f"qualita del segnale {score.value:.2f}")
        elif score is not None:
            # Deliberately not a zero bar. An empty bar would read as
            # "assessed, found worthless", which is the falsification this
            # whole distinction exists to prevent.
            st.info(f"**non valutabile** — {score.data_gap}. Non è un "
                    f"punteggio di zero: è l'assenza di ciò che serve per "
                    f"calcolarne uno.")
            if score.failed_gate:
                st.error(f"gate **{score.failed_gate}** fallito: il punteggio è "
                         f"zero indipendentemente dal resto")
            elif score.weakest:
                st.caption(f"componente più debole: **{score.weakest}** "
                           f"({score.graded.get(score.weakest, 0):.2f})")

        supporting = [r for r in decision.reasons if r.supports]
        blocking = decision.blocking

        if supporting:
            st.markdown("**A favore**")
            for r in supporting:
                st.markdown(f"✅ {r.code} — {r.detail}")

        st.markdown("**Perché NON scommettere**")
        if blocking:
            for r in blocking:
                st.markdown(f"⛔ {r.code} — {r.detail}")
        else:
            st.markdown("⛔ nessun motivo registrato — il che, con zero "
                        "strategie promosse, non dovrebbe accadere")
