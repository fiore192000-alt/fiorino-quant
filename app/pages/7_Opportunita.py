"""
The research opportunity list.

Not opportunities to bet — opportunities to research. Each row says what is
missing, and a missing price is shown as a gap rather than as a verdict.
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.lib import build_warehouse  # noqa: E402

MARK = {"AVAILABLE": "🟢", "RUN": "🟢", "EVALUABLE": "🟢", "TIMESTAMPED": "🟢",
        "PUBLISHED_AT_KNOWN": "🟢", "NOT_YET_AVAILABLE": "🟡",
        "UNKNOWN_INSTANT": "🟡", "NOT_RUN": "🟡",
        "DATA_GAP": "⬛", "NONE": "⬛"}

st.title("Opportunità di ricerca")
label = st.session_state.get("dataset")
if not label:
    st.info("Carica un campionato dalla pagina principale.")
    st.stop()

con = build_warehouse(label)

st.caption(
    "Non opportunità di scommessa: opportunità di **ricerca**. Ogni riga dice "
    "cosa manca. Un prezzo assente è ⬛ DATA_GAP, mai «nessun vantaggio» — "
    "sono affermazioni statisticamente diverse."
)

ready = con.execute("SELECT * FROM v_data_readiness ORDER BY fixture_status").df()
if len(ready):
    st.subheader("Prontezza del dato")
    st.dataframe(ready, use_container_width=True, hide_index=True)

rows = con.execute("""
    SELECT home_team, away_team, kickoff_utc, fixture_status, odds_status,
           odds_timestamp_quality, lineup_status, model_status, decision_status
    FROM v_research_opportunities ORDER BY kickoff_utc DESC LIMIT 40
""").fetchall()

st.subheader("Per partita")
for home, away, ko, fx, odds, oq, lineup, model, decision in rows:
    with st.container(border=True):
        st.markdown(f"**{home} – {away}** · {ko:%d/%m/%Y %H:%M} · `{fx}`")
        st.markdown(
            f"{MARK.get(odds,'⬛')} quote `{odds}` · "
            f"{MARK.get(oq,'⬛')} istante `{oq}` · "
            f"{MARK.get(lineup,'⬛')} formazioni `{lineup}` · "
            f"{MARK.get(model,'⬛')} modello `{model}` · "
            f"{MARK.get(decision,'⬛')} decisione `{decision}`"
        )

st.divider()
st.warning(
    "**`decision_status` è `DATA_GAP` ovunque manchi una quota o un modello.** "
    "Non significa che non ci sia vantaggio: significa che non è stato "
    "possibile cercarlo. Il collo di bottiglia è il **tempo** — quote con un "
    "istante — non il modello."
)
