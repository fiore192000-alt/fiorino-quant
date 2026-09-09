"""
The efficiency map.

Not "is this market inefficient" — that question has no answer — but "where has
this laboratory looked, what did it find, and how hard did it look". Every row
is a measurement already in the repository, with the power that qualifies it.
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

st.title("Mappa dell'efficienza")
st.caption(
    "Dove il laboratorio ha guardato, cosa ha trovato, e con quanta potenza. "
    "Una casella vuota non è un'assenza di inefficienza: è un'assenza di misura."
)

st.subheader("Misurato")
st.markdown("""
| mercato | universo | finestra | CLV | replica | stato |
|---|---|---|---|---|---|
| 1X2 | 10 camp.-stagione | prematch | **−0.0439** | 10/10 negativo | ⚪ NO_SIGNAL |
| 1X2 | 10 camp.-stagione | prematch, soglia 15% | **−0.0470** | 10/10 negativo | ⚪ NO_SIGNAL |
| 1X2 | 10 camp.-stagione | prematch, soglia 30% | **−0.0474** | 10/10 negativo | ⚪ NO_SIGNAL |
| 1X2 | 10 camp.-stagione | line shopping | +0.0234 † | 7/8 positivo | ⚪ NO_SIGNAL |
| 1X2 | 10 camp.-stagione | prematch → chiusura | n/d | segno 10/10 | ⚪ trascurabile |

† **definizionale.** Decomposto su ENG_PL 2019-20: +0.0463 era vero per
costruzione al momento della scommessa, la deriva reale vale −0.0017. Su
PRT_L1, −0.0783.
""")

st.subheader("Cercato e non trovato")
st.markdown("""
Quattordici situazioni × tre selezioni su 3.502 partite, con correzione per
test multipli. **Nessuna sopravvive.**

| famiglia | situazioni | esito |
|---|---|---|
| riposo | breve, vantaggio relativo, casa e trasferta | ⚪ nessuna |
| congestione | terza partita in 8 giorni | ⚪ nessuna |
| motivazione | fine stagione, divario in classifica | ⚪ nessuna |
| calendario | infrasettimanale, festivo, apertura | ⚪ nessuna |
| banda di prezzo | longshot, favoriti, grezzo e de-viggato | ⚪ nessuna |
""")

st.warning(
    "**Potenza:** effetto minimo rilevabile **0.039–0.072** punti di "
    "probabilità. «Nessun bias trovato» significa «nessun bias più grande di "
    "~4–7 punti», non «nessun bias». Un bias di 2–3 punti sarebbe molto "
    "profittevole e resta interamente sotto la soglia."
)

st.subheader("Non misurato — le caselle vuote")
st.markdown("""
| mercato / finestra | perché non c'è |
|---|---|
| Handicap asiatici, Over/Under | quotati e coerenti, ma senza chiusura di riferimento con cui misurarli |
| Post-formazioni | **nessuna fonte con istante di pubblicazione** |
| Post-infortunio | idem |
| Mercato tardivo, bassa liquidità | **nessuna quota timestampata** |
| Reversal, price discovery, breadth | idem: servono più book con istanti |
| Campionati minori, mercati femminili | nessuna fonte gratuita raggiungibile |
| xG | mai testato. Nessun risultato del progetto ne stabilisce l'inutilità |
""")

st.info(
    "Le righe vuote sono la parte utile di questa mappa. Dicono dove **non** "
    "abbiamo guardato, il che è diverso da dove abbiamo guardato senza trovare."
)
