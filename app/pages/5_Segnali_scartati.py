"""
Why NOT bet.

The most valuable page in the terminal, and the one most systems do not have.
A dashboard that only shows opportunities cannot be audited: you never learn
what it silently discarded, or why, or whether the reason was good.

It also stops the same idea coming back in six months as if it were new.
"""

import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.lib import build_warehouse  # noqa: E402
from fiorino.decision import classify  # noqa: E402

st.title("Segnali scartati")
label = st.session_state.get("dataset")
if not label:
    st.info("Carica un campionato dalla pagina principale.")
    st.stop()

con = build_warehouse(label)
has_model = bool(con.execute("SELECT count(*) FROM predictions").fetchone()[0])

st.caption(
    "Ogni opportunità valutata e respinta, con il motivo. Una dashboard che "
    "mostra solo le occasioni non è verificabile: non si scopre mai cosa ha "
    "scartato in silenzio, né se il motivo era buono."
)

rows = con.execute("""
    SELECT f.match_id, f.selection, f.fair_prob, o.price_decimal
    FROM fair_probabilities f
    JOIN odds_observations o USING (match_id, market_type, line, selection,
                                    bookmaker_id, capture_precision)
    WHERE f.market_type = 'ONE_X_TWO' AND f.capture_precision = 'PREMATCH'
      AND f.bookmaker_id NOT IN (SELECT bookmaker_id FROM bookmakers WHERE is_reference)
""").fetchall()

# Il prezzo di un book soft contro la probabilità equa del book di riferimento:
# è il canale di line shopping, misurato in M6 e risultato definizionale.
reference = dict(con.execute("""
    SELECT match_id || '|' || selection, fair_prob FROM fair_probabilities
    WHERE market_type='ONE_X_TWO' AND capture_precision='PREMATCH'
      AND bookmaker_id IN (SELECT bookmaker_id FROM bookmakers WHERE is_reference)
""").fetchall())

counts = Counter()
examples: dict[str, tuple] = {}
for mid, selection, _fair, price in rows:
    ref = reference.get(f"{mid}|{selection}")
    if ref is None:
        continue
    edge = ref * price - 1.0
    decision = classify(
        edge=edge if edge > 0 else None,
        n_settled=676, historical_clv=-0.0336, clv_t_stat=-12.3,
        data_age=timedelta(minutes=1),
    )
    code = decision.blocking[0].code if decision.blocking else "NESSUNO"
    counts[code] += 1
    examples.setdefault(code, (mid, selection, edge, decision))

total = sum(counts.values())
st.metric("Opportunità valutate", f"{total:,}")
st.metric("Respinte", f"{total - counts.get('NESSUNO', 0):,}",
          delta=f"{(total - counts.get('NESSUNO', 0)) / max(total, 1):.1%}")

st.subheader("Per motivo")
for code, n in counts.most_common():
    st.markdown(f"**{n:,}** — `{code}`")
    mid, selection, edge, decision = examples[code]
    with st.expander(f"esempio: {selection}, EV {edge:+.2%}"):
        for r in decision.reasons:
            st.markdown(f"{'✅' if r.supports else '⛔'} {r.code} — {r.detail}")

st.divider()
st.info(
    "**NEGATIVE_CLV domina, ed è corretto.** In M6 `model_edge` ha prodotto CLV "
    "negativo in 30 casi su 30, e l'arm di puro line shopping ha prodotto un "
    "CLV positivo che, decomposto, era **definizionale**: su ENG_PL 2019-20 "
    "+0.0463 era vero per costruzione al momento della scommessa e la deriva "
    "reale valeva −0.0017."
)
if not has_model:
    st.caption("Il modello non è nel magazzino: qui è valutato il solo canale "
               "di line shopping. Vedi la pagina Sistema.")
