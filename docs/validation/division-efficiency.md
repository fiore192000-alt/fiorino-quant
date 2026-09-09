# C-106 — le divisioni inferiori sono prezzate peggio?

**Data**: 2026-09-09 · **Script**: `scripts/scan_division_efficiency.py` ·
**Dati**: `docs/validation/division-efficiency.json` ·
**Fonte**: `xgabora/Club-Football-Match-Data-2000-2025` (bet365 prematch, nessun timestamp)

C-106 e rimasta UNTESTED per quattro milestone per una ragione sola: i dieci
dataset del progetto sono tutti PRIME divisioni, e i mercati di cui parla
l'ipotesi — seconde, terze, quarte serie — non erano nel campione. Non era
un'ipotesi difficile: era un'ipotesi senza dati.

Ora ci sono. 235.806 partite con quota 1X2 completa, 38 divisioni, fra cui
l'Inghilterra fino alla quinta serie e la Scozia fino alla quarta.

## Cosa e stato misurato, e cosa NO

Il benchmark e la quota **prematch di bet365**, non la chiusura Pinnacle
de-viggata su cui girano M5 e M6. I numeri assoluti **non sono confrontabili**
con quelli delle altre milestone: il prematch di un book soft porta un margine
piu largo ed e per costruzione una previsione peggiore.

Il confronto **fra divisioni** invece regge, ed e la domanda: stesso book,
stessa convenzione di raccolta, 38 mercati.

Nessun timestamp. Questo lavoro non dice **nulla** sulla microstruttura, sul
percorso del prezzo o su quando l'informazione entra nella quota.

## Il Brier grezzo non e una misura di efficienza

E la trappola centrale di questo test, ed e il motivo per cui la prima
versione dello script andava rifatta.

Le divisioni inferiori hanno un Brier piu alto (0.20713 contro 0.19604,
p=0.0001). Letto cosi sembra la conferma di C-106. Non lo e: il Brier misura
anche **quanto e incerto il campionato**, non solo quanto e buono il prezzo.
Un campionato piu vicino al lancio di moneta prende un Brier peggiore anche se
prezzato alla perfezione.

La correzione e lo **skill contro la climatologia**: `1 - Brier/Brier_clim`,
dove la previsione climatologica e la frequenza storica H/D/A **di quella
divisione**. Porta esattamente quell'entropia e nient'altro, quindi il
rapporto e cio che il mercato aggiunge **sopra** il sapere in che campionato
si e.

## Risultato

| gruppo | mercati | partite | skill | scarto calibrazione | margine |
|---|---:|---:|---:|---:|---:|
| prime divisioni | 27 | 137.940 | +0.0879 | 0.0064 | 0.0715 |
| divisioni inferiori | 11 | 97.863 | +0.0428 | 0.0052 | 0.0787 |

Differenza (inferiori − prime), test di permutazione sull'etichetta di serie:

| statistica | delta | p | |
|---|---:|---:|---|
| skill vs climatologia | −0.0451 | 0.0001 | distinguibile |
| scarto di calibrazione | −0.0013 | 0.3080 | **NON** distinguibile |
| margine | +0.0072 | 0.0113 | distinguibile |

### Il confronto appaiato, che e quello che conta

Il confronto sopra e in parte un confronto fra **paesi**, non fra serie: ogni
divisione inferiore del campione e europea, mentre fra le prime ci sono
Argentina, Cina, Giappone, Messico e Stati Uniti. Sei paesi pubblicano qui sia
la prima sia una serie inferiore, e li il paese si annulla:

| paese | skill 1a | skill inf. | delta skill | scarto 1a | scarto inf. | delta margine |
|---|---:|---:|---:|---:|---:|---:|
| Inghilterra | +0.1083 | +0.0408 | −0.0675 | 0.0035 | 0.0041 | +0.0132 |
| Francia | +0.0696 | +0.0337 | −0.0360 | 0.0055 | 0.0037 | +0.0118 |
| Germania | +0.0799 | +0.0349 | −0.0450 | 0.0038 | 0.0012 | +0.0095 |
| Italia | +0.1181 | +0.0408 | −0.0773 | 0.0105 | 0.0076 | +0.0151 |
| Scozia | +0.1263 | +0.0565 | −0.0698 | 0.0077 | 0.0085 | +0.0132 |
| Spagna | +0.0968 | +0.0285 | −0.0684 | 0.0068 | 0.0028 | +0.0135 |

- skill piu basso nella serie inferiore: **6/6 paesi** (test dei segni p=0.031)
- scarto di calibrazione piu alto nella serie inferiore: **2/6 paesi**
- margine piu alto nella serie inferiore: **6/6 paesi**, media +0.0127

## Lettura

**1. Il mercato e misurabilmente meno affilato nelle serie inferiori.** In sei
paesi su sei, con lo stesso book e lo stesso anno. E la prima volta in tutto il
progetto che due gruppi di mercati si distinguono in modo replicato. Il
risultato e reale.

**2. Non e una prova di prezzo sbagliato, ed e la distinzione che decide
tutto.** Meno affilato non vuol dire scalibrato. Lo scarto di calibrazione non
distingue i due gruppi (p=0.31) e nell'appaiato va nella direzione "sbagliata"
in 4 paesi su 6. Uno skill piu basso e ugualmente compatibile con l'ipotesi che
la quarta serie inglese sia **intrinsecamente meno prevedibile**, non prezzata
peggio: un previsore perfetto avrebbe anche lui uno skill piu basso li. Questa
misura **non puo separare** "mercato meno informato" da "partita meno
prevedibile". Serve un modello che batta il mercato in una serie inferiore, ed
e un test diverso.

**3. Il book fa pagare la propria ignoranza.** Il margine e piu alto dove lo
skill e piu basso, in 6 paesi su 6, e fra i sei la correlazione delle due
differenze e −0.83 (n=6: un'indicazione, non una stima). E il comportamento
di un market maker razionale sotto incertezza, e ha una conseguenza pratica
diretta: **"andare dove il mercato e piu stupido" e in parte autolesionista**,
perche il pedaggio sale insieme all'ignoranza. In media si paga 1.27 punti
percentuali in piu proprio dove si spererebbe di trovare il vantaggio.

## Qualita del dato

3 righe su 235.806 rifiutate dal de-vig: somma implicita sotto 1, cioe
arbitraggio o riga corrotta. Peggior mercato FIN, 0.04%. Contate e riportate
per divisione nel JSON, non nascoste.

## Cosa NON e stato dimostrato

- che esista un vantaggio economico nelle serie inferiori — non e stato cercato
- che il mercato sia scalibrato li — misurato, e non si distingue
- qualunque cosa sulla microstruttura — la fonte non ha timestamp
- qualunque confronto con i numeri M5/M6 — benchmark diverso
