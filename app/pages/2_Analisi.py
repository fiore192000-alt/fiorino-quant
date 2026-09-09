"""One match: market, model, and the decision — with the reasons."""

import sys
from datetime import timedelta
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.lib import build_warehouse, evidence_card  # noqa: E402
from fiorino.decision import classify, score_signal  # noqa: E402

# NB: nessun import di fiorino.models qui, e nessun fit.
#
# L'app non addestra. E la separazione research/production del brief, e in
# questo repository e anche un requisito di deploy: la directory penaltyblog/
# del repo oscura il pacchetto installato da PyPI, e nel clone le estensioni
# Cython non sono compilate. Un `import penaltyblog` dentro l'app fallisce con
# "No module named 'penaltyblog.metrics.metrics'" — verificato in un venv
# pulito, non ipotizzato. Il walk-forward gira offline, negli script.

BADGE = {"NO_SIGNAL": "⚪", "WATCH": "🔵", "CANDIDATE": "🟡", "QUALIFIED": "🟢"}

st.title("Analisi")
label = st.session_state.get("dataset")
mid = st.session_state.get("match_id")
if not (label and mid):
    st.info("Scegli una partita dalla pagina Partite.")
    st.stop()

con = build_warehouse(label)

HAS_MODEL = bool(con.execute("SELECT count(*) FROM predictions").fetchone()[0])

home, away, ko = con.execute("""
    SELECT th.canonical_name, ta.canonical_name, m.kickoff_utc
    FROM v_analytic_matches m
    JOIN teams th ON th.team_id = m.home_team_id
    JOIN teams ta ON ta.team_id = m.away_team_id
    WHERE m.match_id = ?""", [mid]).fetchone()
st.header(f"{home} – {away}")
st.caption(f"{ko:%d/%m/%Y %H:%M} UTC")

if not HAS_MODEL:
    st.info(
        "**Nessuna previsione nel magazzino.** L'app non addestra modelli: il "
        "walk-forward gira offline (`scripts/validate_models.py`) e i suoi "
        "risultati vengono caricati. Qui sotto trovi il mercato, che è il "
        "benchmark contro cui tutto il resto va misurato."
    )
    market = con.execute("""
        SELECT selection, fair_prob, price_decimal FROM fair_probabilities f
        JOIN odds_observations o USING (match_id, market_type, line, selection,
                                        bookmaker_id, capture_precision)
        WHERE f.match_id = ? AND f.market_type = 'ONE_X_TWO'
          AND f.capture_precision = 'PREMATCH'
          AND f.bookmaker_id IN (SELECT bookmaker_id FROM bookmakers WHERE is_reference)
        ORDER BY selection""", [mid]).fetchall()
    for selection, prob, price in market:
        c1, c2 = st.columns(2)
        c1.metric(selection, f"{prob:.1%}", help="de-viggata, Shin")
        c2.metric("quota", f"{price:.2f}")
        decision = classify(edge=None, data_age=timedelta(minutes=1))
        st.markdown(f"{BADGE[decision.level]} **{decision.level}** — "
                    f"{decision.reasons[0].detail}")
    st.stop()

rows = con.execute("""
    WITH freshest AS (
        SELECT v.*, r.trained_through,
               row_number() OVER (PARTITION BY v.selection
                                  ORDER BY r.trained_through DESC) rn
        FROM v_model_vs_market v
        JOIN model_runs r ON r.model_run_id = v.model_run_id
        WHERE v.match_id = ? AND v.market_type='ONE_X_TWO'
          AND v.capture_precision='PREMATCH' AND r.model_name='dixon_coles'
    )
    SELECT selection, prob_win, offered_price, edge_ev, used_prior, bookmaker_id
    FROM freshest WHERE rn = 1 ORDER BY selection""", [mid]).fetchall()

if not rows:
    st.info("Nessuna previsione per questa partita: il fit più fresco non la copre.")
    st.stop()

st.subheader("Mercato contro modello")
for selection, prob, price, edge, prior, book in rows:
    implied = 1 / price
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        c1.metric(selection, f"{prob:.1%}", help="probabilità del modello")
        c2.metric("quota", f"{price:.2f}", help=f"{book}, prematch")
        c3.metric("EV", f"{edge:+.1%}", delta=f"{prob - implied:+.1%}")

        decision = classify(
            edge=edge,
            n_settled=676,                 # M6: model_edge, ENG_PL 2017-18
            historical_clv=-0.0336,        # misurato, non ipotizzato
            clv_t_stat=-12.3,
            used_prior=bool(prior),
            data_age=timedelta(minutes=1),
        )
        score = score_signal(
            edge=edge, historical_clv=-0.0336, n_settled=676,
            replications=0, adversarial_passed=0,
            data_age=timedelta(minutes=1),
        )
        evidence_card(
            f"{home} – {away} · {selection}", decision, score,
            facts={
                "Mercato": f"{implied:.1%} (quota {price:.2f}, {book})",
                "Fiorino": f"{prob:.1%}",
                "Edge": f"{prob - implied:+.1%} · EV {edge:+.1%}",
            },
        )

st.divider()
st.caption(
    "Il CLV storico usato qui è quello **misurato** per `model_edge` su questo "
    "campionato-stagione: −0.0336, t = −12.3 su 676 scommesse. È negativo, "
    "quindi ogni EV positivo del modello viene classificato NO_SIGNAL. Non è "
    "una scelta di interfaccia: è il risultato di M6."
)
