"""Data status, coverage, versions. The page that says when not to trust the rest."""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.lib import build_warehouse, system_status  # noqa: E402
from fiorino.data.quality.pit_chain import run_pit_chain_audit  # noqa: E402

st.title("Sistema")
status = system_status()

c1, c2, c3 = st.columns(3)
c1.metric("Tabelle", status["n_tables"])
c2.metric("Viste", status["n_views"])
c3.metric("Migrazioni", status["n_migrations"])
st.caption(f"commit `{status['commit']}`")

st.subheader("Freschezza dei dati")
st.error(
    "🔴 **NESSUN DATO TIMESTAMPATO.** Non esiste una riga `TIMESTAMPED` in "
    "nessun dataset: Football-Data fornisce due punti per partita. `odds_as_of()` "
    "e il vincolo sui timestamp sono scritti, testati e **mai esercitati**.\n\n"
    "Questa app non è un live scanner e non può diventarlo finché non arriva "
    "una fonte timestampata."
)

label = st.session_state.get("dataset")
if label:
    con = build_warehouse(label)
    st.subheader("Audit point-in-time")
    findings = run_pit_chain_audit(con)
    blocking = [f for f in findings if f.severity == "BLOCKING"]
    if blocking:
        for f in blocking:
            st.error(f"**{f.check_name}** — {f.detail}")
    else:
        st.success("Nessuna violazione bloccante nella catena point-in-time.")
    for f in findings:
        if f.severity != "BLOCKING":
            st.warning(f"**{f.check_name}** — {f.detail}")

    st.subheader("Metodo di de-vig effettivamente usato")
    methods = [r[0] for r in con.execute(
        "SELECT DISTINCT devig_method FROM fair_probabilities").fetchall()]
    if methods == ["SHIN"]:
        st.success("SHIN — il metodo previsto.")
    else:
        st.warning(
            f"**{', '.join(methods)}** invece di SHIN. penaltyblog non e "
            "importabile in questo ambiente (la directory del repository "
            "oscura il pacchetto installato e le estensioni Cython non sono "
            "compilate), quindi il de-vig ricade sul moltiplicativo.\n\n"
            "Non e un dettaglio: le probabilita eque differiscono, e in M3 e "
            "stato stabilito che l'identita di calibrazione del CLV regge "
            "sotto moltiplicativo e **non** sotto Shin. Il dato registra il "
            "metodo applicato, non quello richiesto."
        )

    st.subheader("Copertura del mercato")
    cov = con.execute("""
        SELECT capture_precision, bookmaker_id, count(*)
        FROM odds_observations WHERE market_type='ONE_X_TWO'
        GROUP BY 1, 2 ORDER BY 3 DESC""").fetchall()
    st.table({"precisione": [r[0] for r in cov],
              "book": [r[1] for r in cov],
              "osservazioni": [r[2] for r in cov]})

st.subheader("Strategie promosse")
if status["promoted_strategies"]:
    st.json(status["promoted_strategies"])
else:
    st.info(
        "**Nessuna.** Il registro delle promozioni è vuoto, quindi il "
        "classificatore non può superare WATCH. Vedi `PROMOTION_GATES.md`."
    )
