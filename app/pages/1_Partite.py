"""Fixtures with the market's own view. No model, no opinion — the baseline."""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.lib import build_warehouse  # noqa: E402

st.title("Partite")
label = st.session_state.get("dataset")
if not label:
    st.info("Torna alla pagina principale e carica un campionato.")
    st.stop()

con = build_warehouse(label)
rows = con.execute("""
    SELECT m.match_id, m.kickoff_utc, th.canonical_name, ta.canonical_name,
           max(f.fair_prob) FILTER (WHERE f.selection='HOME'),
           max(f.fair_prob) FILTER (WHERE f.selection='DRAW'),
           max(f.fair_prob) FILTER (WHERE f.selection='AWAY'),
           any_value(r.goals_home), any_value(r.goals_away)
    FROM v_analytic_matches m
    JOIN teams th ON th.team_id = m.home_team_id
    JOIN teams ta ON ta.team_id = m.away_team_id
    LEFT JOIN match_results r ON r.match_id = m.match_id
    LEFT JOIN fair_probabilities f
      ON f.match_id = m.match_id AND f.market_type='ONE_X_TWO'
     AND f.capture_precision='PREMATCH'
     AND f.bookmaker_id IN (SELECT bookmaker_id FROM bookmakers WHERE is_reference)
    GROUP BY m.match_id, m.kickoff_utc, th.canonical_name, ta.canonical_name
    ORDER BY m.kickoff_utc
""").fetchall()

st.caption(f"{len(rows)} partite nel dataset analitico — le identità non "
           f"giudicate ne restano fuori per costruzione.")

query = st.text_input("Filtra per squadra", "")
shown = 0
for mid, ko, home, away, ph, pd_, pa, gh, ga in rows:
    if query and query.lower() not in f"{home} {away}".lower():
        continue
    shown += 1
    if shown > 60:
        break
    score = f"{gh}–{ga}" if gh is not None else "—"
    with st.container(border=True):
        st.markdown(f"**{home} – {away}**  ·  {ko:%d/%m/%Y %H:%M} UTC  ·  {score}")
        if ph is None:
            st.caption("nessuna quota di riferimento")
            continue
        c1, c2, c3 = st.columns(3)
        c1.metric("1", f"{ph:.1%}")
        c2.metric("X", f"{pd_:.1%}")
        c3.metric("2", f"{pa:.1%}")
        if st.button("Analizza", key=mid, use_container_width=True):
            st.session_state["match_id"] = mid
            st.switch_page("pages/2_Analisi.py")
