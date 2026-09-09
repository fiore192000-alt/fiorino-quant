"""
Fiorino Quant — V0.

Deployed on Streamlit Community Cloud, opened from a phone. What it shows is
the laboratory's actual state, which is: **no validated edge**. The dashboard
is built so that fact is impossible to miss rather than buried under a number.

WHY THE WAREHOUSE IS BUILT AT RUNTIME
-------------------------------------
The repository holds code, schema and config; the dataset lives under
$FIORINO_DATA_ROOT, outside the tree, and Community Cloud has no such
directory. So the app fetches a real Football-Data archive and builds an
in-memory DuckDB on first use, cached for the session. Nothing is faked: these
are the same matches, prices and identity rules the validation ran on.

It is a demonstration surface, not a live scanner. A live scanner needs
timestamped odds, which do not exist yet — see docs/architecture/data-acquisition.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

st.set_page_config(page_title="Fiorino Quant", page_icon="🦊",
                   layout="centered", initial_sidebar_state="collapsed")

from app.lib import DATASETS, build_warehouse, git_commit, system_status  # noqa: E402

st.title("🦊 Fiorino Quant")

status = system_status()

if not status["promoted_strategies"]:
    st.error(
        "**NESSUNA STRATEGIA VALIDATA.** Il laboratorio non ha mai prodotto un "
        "CLV positivo fuori campione che non fosse definizionale. Nessuna "
        "schermata di questa app può superare il livello **WATCH**, e non per "
        "prudenza: è un vincolo nel codice, con un test che fallisce se viene "
        "rimosso senza una promozione registrata."
    )

st.caption(
    f"commit `{status['commit']}` · {status['n_tables']} tabelle · "
    f"{status['n_views']} viste · {status['n_migrations']} migrazioni"
)

st.markdown(
    """
Un laboratorio quantitativo per il calcio europeo. Il suo scopo dichiarato è
**dimostrare o falsificare** un vantaggio, non produrne uno.

Finora ha falsificato:

| | |
|---|---|
| Il modello batte la chiusura? | **no**, 10 dataset su 10 |
| Il modello aggiunge informazione al mercato? | **no**, 20 CI su 20 contengono lo zero |
| Qualche situazione è mal prezzata? | **nessuna** delle 14 sopravvive alla correzione |
| Qualche strategia ha CLV positivo? | **mai**, in nessuna delle 30 combinazioni |
"""
)

st.divider()
dataset = st.selectbox("Campionato-stagione", [d[0] for d in DATASETS], index=0)
st.session_state["dataset"] = dataset

if st.button("Carica i dati", type="primary", use_container_width=True):
    with st.spinner("Scarico l'archivio, risolvo le identità, ricostruisco il mercato…"):
        build_warehouse(dataset)
    st.success("Magazzino costruito. Usa il menu in alto a sinistra per le pagine.")

st.divider()
st.caption(
    "Le pagine **Partite**, **Analisi**, **Ricerca** e **Sistema** sono nel menu "
    "laterale. Su iPhone: tocca la freccia in alto a sinistra."
)
