# Validazione M5 — il modello contro la chiusura, su 10 campionati-stagione

```
python scripts/validate_models.py --json docs/validation/model-results.json
```

10 dataset · 311 fit walk-forward · **219.010 predizioni** · dati reali
Football-Data (nessun dato sintetico). Risultati grezzi in
[`model-results.json`](model-results.json).

---

## Il risultato

> **Il mercato batte il modello in 10 dataset su 10, su entrambe le metriche,
> senza una sola eccezione.**

| | Brier modello | Brier chiusura | Δ | LogLoss modello | LogLoss chiusura | Δ |
|---|---|---|---|---|---|---|
| ENG_PL 2017-18 | 0.19470 | 0.18491 | −0.00979 | 0.58172 | 0.54915 | −0.03258 |
| ENG_PL 2018-19 | 0.18480 | 0.17593 | −0.00887 | 0.54852 | 0.52845 | −0.02007 |
| ENG_PL 2019-20 | 0.19747 | 0.19010 | −0.00737 | 0.58403 | 0.56430 | −0.01973 |
| ENG_PL 2020-21 | 0.20612 | 0.19713 | −0.00899 | 0.60587 | 0.58179 | −0.02408 |
| ESP_LL 2019-20 | 0.19947 | 0.19219 | −0.00728 | 0.58899 | 0.56637 | −0.02262 |
| ITA_SA 2019-20 | 0.20020 | 0.18984 | −0.01036 | 0.58894 | 0.56377 | −0.02517 |
| DEU_BL1 2024-25 | 0.21728 | 0.20081 | −0.01646 | 0.63120 | 0.58556 | −0.04564 |
| FRA_L1 2024-25 | 0.19691 | 0.18767 | −0.00925 | 0.58543 | 0.55917 | −0.02626 |
| NLD_ED 2024-25 | 0.20346 | 0.18935 | −0.01411 | 0.59668 | 0.56055 | −0.03613 |
| PRT_L1 2024-25 | 0.19780 | 0.18913 | −0.00867 | 0.58380 | 0.55818 | −0.02562 |
| **media** | | | **−0.01012** | | | **−0.02779** |

Δ negativo = il modello è peggio. L'intervallo su Brier è
[−0.01646, −0.00728]: non c'è un campionato, un'epoca o una stagione in cui il
segno si inverta. Sei stagioni fino al 2020-21 e quattro 2024-25, sette paesi.

Un Dixon-Coles con decadimento a 180 giorni, fittato correttamente in
walk-forward su una stagione di storico, **non sa nulla che la chiusura Pinnacle
de-viggata non sappia già.** Questo era il risultato atteso. Averlo misurato
invece che assunto è ciò che permette di non costruirci sopra.

---

## Il modello continua a trovare «value» ovunque

| dataset | selezioni quotate | con edge > 5% | edge massimo |
|---|---|---|---|
| ENG_PL 2017-18 | 2 940 | 1 037 (35.3%) | +2.079 |
| ENG_PL 2018-19 | 2 868 | 941 (32.8%) | +2.677 |
| ENG_PL 2019-20 | 5 448 | 2 127 (39.0%) | +3.718 |
| ENG_PL 2020-21 | 4 752 | 1 671 (35.2%) | +5.211 |
| ESP_LL 2019-20 | 4 938 | 1 781 (36.1%) | +1.877 |
| ITA_SA 2019-20 | 5 292 | 1 842 (34.8%) | +3.615 |
| DEU_BL1 2024-25 | 4 656 | 1 652 (35.5%) | +2.918 |
| FRA_L1 2024-25 | 3 600 | 1 169 (32.5%) | +1.081 |
| NLD_ED 2024-25 | 3 720 | 1 033 (27.8%) | +1.999 |
| PRT_L1 2024-25 | 3 756 | 973 (25.9%) | +1.128 |

Un modello **peggiore del mercato in ogni singolo dataset** dichiara un vantaggio
superiore al 5% su circa **un terzo di tutte le selezioni**, e in un caso un
+521% di EV attesa.

Sono errori del modello, non edge. La distinzione non è filosofica: un sistema
che dimensiona con Kelly sulla confidenza del modello punterebbe **più forte
proprio dove sbaglia di più**. È l'esatta ragione per cui in questo sistema
decide il CLV e non il modello.

---

## Il CLV lo dice, lo yield no

Trenta combinazioni strategia × dataset per il modello, tre soglie:

| strategia | yield medio | yield > 0 in | CLV medio | CLV > 0 in | t medio |
|---|---|---|---|---|---|
| `model_edge` 5% | −0.0726 | **2/10** | −0.0439 | **0/10** | −13.8 |
| `model_edge` 15% | −0.0770 | **2/10** | −0.0470 | **0/10** | −10.9 |
| `model_edge` 30% | −0.1087 | **3/10** | −0.0474 | **0/10** | −8.1 |
| `take_home` (controllo) | −0.0090 | 5/10 | −0.0387 | 0/10 | — |

**Il CLV è negativo in 30 casi su 30.** Non una volta, su nessuna soglia, in
nessun paese, il modello ha comprato un prezzo che la chiusura poi ha
convalidato.

Lo yield invece è positivo 7 volte su 30, e non timidamente. Il caso peggiore:

> **ENG_PL 2019-20, `model_edge` 15%** — 968 scommesse, yield **+9.50%**,
> crescita **+159.89%**, drawdown 21.8%.
> CLV **−0.0414**, t = **−12.1**.

Una tearsheet con quello yield e quella curva verrebbe presentata come una
scoperta. Il t-stat del CLV a −12.1 su 968 scommesse dice che è rumore, con una
sicurezza che nessuna metrica di P&L su una stagione può avvicinare. È lo stesso
verdetto della validazione M4 — CLV corretto 30/30, yield corretto 23/30 —
ottenuto qui su una strategia che ha davvero un'opinione.

Nello stesso dataset `take_home` fa **+11.91% di yield e +287% di crescita**.
La stagione 2019-20 premia chiunque; questo è precisamente ciò contro cui il CLV
protegge.

### Il modello sceglie prezzi peggiori del caso

`model_edge` ha un CLV **peggiore** del controllo senza opinione in **7 dataset
su 10** (delta medio −0.0052, peggior caso NLD_ED −0.0310). Non è solo che il
modello non trova edge: la sua selezione è **attivamente anti-correlata** con il
prezzo giusto. Puntare dove il modello urla «value» è peggio che puntare in
casa a caso.

### Cosa NON regge

L'ipotesi che avevo formulato costruendo lo script — che uno yield decrescente
al crescere della soglia fosse la firma diagnostica della miscalibrazione — **non
è confermata**. Lo yield decresce monotonamente in 4 dataset su 10, e anche il
CLV in 4 su 10. Solo le medie aggregate sono monotone (CLV −0.0439 → −0.0470 →
−0.0474).

La lettura corretta è quella conservativa: su un singolo campionato-stagione lo
yield non distingue un edge vero da una miscalibrazione, nemmeno guardandone la
forma. Il confronto diretto con la chiusura sì, ed è unanime.

---

## Gli invarianti del motore

Su 219.010 predizioni e 311 fit: **zero violazioni**.

| invariante | violazioni |
|---|---|
| nessun fit addestrato oltre il kickoff che quota (R1) | **0** |
| nessuna predizione datata dopo il proprio kickoff | **0** |
| le cinque probabilità sommano a 1 | **0** |
| nessuna probabilità negativa | **0** |
| 1X2 somma a 1 su ogni fixture | **0** |
| OVER + UNDER = 1 su ogni linea a mezzo gol | **0** |
| ogni predizione ha un `model_run` con provenienza | **0** |

Il primo è quello che conta: è ciò che separa un walk-forward da un
look-ahead, e senza di esso ogni numero sopra sarebbe privo di significato. La
coerenza multi-mercato (righe 5 e 6) è vera per costruzione — un'unica griglia
per fixture — ma verificata comunque, perché la costruzione può rompersi.

---

## Il bug di penaltyblog, quantificato

**82 fallback** su 311 fit, distribuiti in modo molto irregolare:

| dataset | fallback |
|---|---|
| ENG_PL 2018-19 | **44** |
| DEU_BL1 2024-25 | 27 |
| ENG_PL 2019-20, ESP_LL 2019-20, NLD_ED 2024-25 | 3 ciascuno |
| ENG_PL 2017-18, ITA_SA 2019-20 | 1 ciascuno |
| ENG_PL 2020-21, FRA_L1 2024-25, PRT_L1 2024-25 | 0 |

`model.predict()` solleva «goal_matrix contains negative probabilities» quando
il `rho` stimato esce dai limiti imposti dalle lambda di quella specifica
fixture. Non è un caso limite raro: su ENG_PL 2018-19 accade **44 volte** nelle
33 finestre di fit — il contatore è per fixture quotata, non per finestra.

Senza l'adapter, il walk-forward si sarebbe interrotto sulla prima. Con
l'adapter, il fallback sui parametri grezzi e la saturazione del rho in
`score_grid` lo rendono un contatore in `model_runs.params`, non un incidente.
È l'argomento operativo — non ideologico — per tenere penaltyblog come
dipendenza e non come core.

---

## Limiti dichiarati

**Il prior di lega non è esercitato qui.** `priced from league prior: 0.0%` su
tutti e 10 i dataset: con `min_train = 60`, quando il primo fit avviene tutte le
squadre della lega hanno già giocato. Il percorso esiste, è coperto dai test
unitari (`TestUnseenTeams`), ma questa validazione **non lo mette alla prova**.
Diventerà rilevante quotando in cross-season, dove le neopromosse arrivano senza
storico.

**Un solo modello.** Tutti i numeri sono Dixon-Coles con emivita 180 giorni.
`MODELS` ne espone sei; gli altri cinque non sono stati validati. Non c'è ragione
di aspettarsi che uno di essi ribalti un risultato 10/10, ma non è stato
misurato.

**Un solo mercato nel confronto.** Calibrazione e backtest usano 1X2. Handicap
asiatici e totals sono quotati (55 selezioni per fixture) e verificati come
coerenti, ma non hanno una chiusura de-viggata di riferimento con cui misurarli
in questo dataset.

**Nessuna calibrazione applicata.** Le probabilità sono quelle grezze del fit.
Ricalibrarle out-of-fold e mescolarle con il mercato in logit space è M6, ed è
adesso una fase con un baseline numerico da battere invece che un'intenzione.

---

## Cosa cambia per M6

Il risultato non dice «il modello è inutile». Dice che il modello **da solo** non
batte la chiusura, che è la premessa da cui M6 parte: il blending con il mercato
non serve a nascondere un modello debole, serve perché la chiusura è
l'informazione migliore disponibile e il modello può al più aggiungerci qualcosa
ai margini.

Il criterio di successo di M6 è ora una soglia misurata, non un'aspirazione:

> Brier < 0.18491 su ENG_PL 2017-18 e sotto la chiusura in tutti e 10 i dataset,
> **con CLV medio positivo su almeno una strategia.**

La seconda condizione è quella vincolante. Su questi dati nessuna strategia,
a nessuna soglia, in nessun campionato, ha mai prodotto un CLV positivo.
