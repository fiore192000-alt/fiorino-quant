"""The research state. Negative results are the content, not a footnote."""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
DOCS = Path(__file__).resolve().parents[2] / "docs"

st.title("Ricerca")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Ipotesi chiuse", 11)
c2.metric("Positive", 0)
c3.metric("Replicate", 0)
c4.metric("Bloccate da dati", 3)

st.error(
    "**0 ipotesi positive su 11 chiuse.** Nessuna strategia ha mai prodotto un "
    "CLV positivo fuori campione che non fosse definizionale."
)

st.subheader("I quattro risultati")
st.markdown("""
| esperimento | esito | evidenza |
|---|---|---|
| Il modello batte la chiusura | **NO INCREMENTAL EDGE** | mercato migliore in 10/10, Brier −0.01012 |
| `MARKET + MODEL` batte `MARKET` | **NO INCREMENTAL EDGE** | 0/10, tutti e 20 i CI contengono lo zero |
| Il modello trova value sfruttabile | **NO EVIDENCE** | CLV negativo 30 volte su 30 |
| Qualche situazione è mal prezzata | **NO EVIDENCE** | 0/14 sopravvive a Benjamini-Hochberg |
""")

st.subheader("Il limite del risultato negativo")
st.info(
    "La scansione rileva effetti sopra **0.039–0.072 punti di probabilità**. "
    "«Nessun bias trovato» significa quindi «nessun bias più grande di ~4–7 "
    "punti», non «nessun bias». Un bias di 2–3 punti sarebbe molto "
    "profittevole e resta sotto la soglia."
)

st.subheader("Affermazioni ritirate dal laboratorio")
st.markdown("""
Sembravano solide su un campione e non hanno replicato. Restano a registro
perché sono la prova che il metodo funziona.

- Asimmetria HOME/AWAY nel drift
- «Firma della miscalibrazione»: lo yield decresce con la soglia
- Il baseline CLV −0.028 come costante globale
- «Non manca una feature, manca una classe di informazione»
- Il rapporto divario/canale 12× (sugli stessi dataset è 10,2×)
""")

with st.expander("Documenti completi"):
    for name in ("research/HYPOTHESIS_REGISTRY.md", "research/PROMOTION_GATES.md",
                 "research/RESEARCH_PROTOCOL.md", "research/DATA_CATALOG.md",
                 "FINDINGS.md"):
        path = DOCS / name
        if path.exists():
            st.markdown(f"**{name}** — {len(path.read_text().splitlines())} righe")
