"""One match: market, model, and the decision — with the reasons."""

import sys
from datetime import timedelta
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.lib import build_warehouse  # noqa: E402
from fiorino.decision import classify  # noqa: E402
from fiorino.models.fitting import walk_forward  # noqa: E402

BADGE = {"NO_SIGNAL": "⚪", "WATCH": "🔵", "CANDIDATE": "🟡", "QUALIFIED": "🟢"}

st.title("Analisi")
label = st.session_state.get("dataset")
mid = st.session_state.get("match_id")
if not (label and mid):
    st.info("Scegli una partita dalla pagina Partite.")
    st.stop()

con = build_warehouse(label)

if not con.execute("SELECT count(*) FROM predictions").fetchone()[0]:
    st.warning("Il modello non è ancora stato addestrato su questo dataset.")
    if st.button("Esegui il walk-forward (~50 s)", type="primary"):
        comp, seas = con.execute(
            "SELECT competition_id, season_id FROM v_analytic_matches LIMIT 1"
        ).fetchone()
        with st.spinner("Fit settimanale, quotazione a otto giorni…"):
            walk_forward(con, competition_id=comp, season_id=seas,
                         step=timedelta(days=7))
        st.rerun()
    st.stop()

home, away, ko = con.execute("""
    SELECT th.canonical_name, ta.canonical_name, m.kickoff_utc
    FROM v_analytic_matches m
    JOIN teams th ON th.team_id = m.home_team_id
    JOIN teams ta ON ta.team_id = m.away_team_id
    WHERE m.match_id = ?""", [mid]).fetchone()
st.header(f"{home} – {away}")
st.caption(f"{ko:%d/%m/%Y %H:%M} UTC")

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
        st.markdown(f"### {BADGE[decision.level]} {decision.level}")
        for reason in decision.reasons:
            st.markdown(f"{'✅' if reason.supports else '⛔'} **{reason.code}** — {reason.detail}")

st.divider()
st.caption(
    "Il CLV storico usato qui è quello **misurato** per `model_edge` su questo "
    "campionato-stagione: −0.0336, t = −12.3 su 676 scommesse. È negativo, "
    "quindi ogni EV positivo del modello viene classificato NO_SIGNAL. Non è "
    "una scelta di interfaccia: è il risultato di M6."
)
