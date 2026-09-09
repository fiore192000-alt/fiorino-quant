# Fiorino Quant — Findings & Research Closure

**Stato:** ricerca ex-post CHIUSA · fase point-in-time APERTA
**Data:** 2026-09-09 · **Promozioni:** `PROMOTED = 0`

Questo documento è un registro scientifico, non un consuntivo. Dice cosa è
stato testato, cosa è stato falsificato, cosa resta non misurato, e quali
condizioni devono verificarsi prima che il sistema possa produrre un
`PROMOTED`.

---

## Conclusione esecutiva

La ricerca ex-post non ha identificato alcun edge sfruttabile e statisticamente
credibile contro il mercato.

Da non leggere come:

> «Non abbiamo ancora trovato il segnale.»

La lettura corretta è:

> Le famiglie di segnali finora testate non hanno prodotto evidenza sufficiente
> di **informazione incrementale** rispetto al prezzo di mercato.

La fase di ricerca storica è quindi **chiusa, non sospesa**. L'unica direzione
non falsificata è la raccolta point-in-time di informazione che il mercato non
aveva ancora incorporato nel prezzo al momento in cui il prezzo si è formato.

---

## 1. L'evidenza contro un edge ex-post

| test | scala | esito |
|---|---|---|
| CLV su prezzi prematch | 369.662 oss., 4 stagioni, 21 divisioni | nessuna cella positiva sopravvive a Benjamini-Hochberg |
| movimento delle quote | 125.594 oss., 5 stagioni | gradiente monotono, ogni direzione negativa |
| partite in arrivo | 90 righe | 0 sopra la banda nulla |
| ipotesi situazionali | 14 ipotesi | 0 sopravvivono alla correzione |
| modello contro mercato | 10 dataset | il mercato vince 10 su 10 |

**CLV medio su tutto: −0.0527.** È il margine, ed è il pavimento contro cui
ogni regola sbatte. Il risultato è coerente con un prezzo di apertura che
incorpora già l'informazione, poi ulteriormente raffinata fino alla chiusura.
Nessuna sottopopolazione stabile trasforma quella dinamica in profitto.

### L'unica cella positiva, e perché non conta

`BETFAIR_EX` quotato più lungo del consenso degli altri book:
**+0.0075 di CLV, t=+5.69**, sopravvive a BH su 7.414 osservazioni.

Muore sulla commissione. Il prezzo dell'exchange è al lordo:

| quota | commissione 2% | commissione 5% |
|---:|---:|---:|
| 2.00 | −0.0026 | −0.0177 |
| 5.00 | −0.0086 | −0.0328 |

Il 2% è la commissione **minima** esistente. Non è un edge: è l'exchange che
è il prezzo più affilato del mercato, e la sua commissione se lo riprende.
Questa singola riga è la giustificazione empirica del Gate 5.

---

## 2. Artefatto: la maledizione del vincitore

Il motore aveva classificato **5 partite su 18 in classe A**, edge fino a
**+5.74%**.

Controllo costruito: tutti i bookmaker stimano la stessa probabilità, nessuna
inefficienza reale, l'unica differenza è la dispersione dei prezzi. Calibrato
sulla dispersione realmente osservata (0.024 punti di probabilità su 7 book):

```
edge mediano del massimo di sette prezzi   +4.0%
casi sopra il +4%                          50%
```

**Il segnale apparente è generabile dalla sola selezione del prezzo estremo.**
Un edge calcolato come *massimo prezzo osservato meno probabilità stimata* non
dimostra alcuna inefficienza.

Rimedio permanente: l'edge si valuta su un **book nominato** contro il consenso
degli **altri** (`edge_leave_one_out`), e la soglia è la banda nulla calcolata
sulla dispersione di quella singola partita (`null_edge`), non una costante.

---

## 3. Artefatto: il look-ahead

Risultato apparente, il più convincente mai prodotto dal progetto:

```
CLV      +0.0440
t        +45.8
dose-risposta monotona sull'ampiezza del movimento
controllo negativo che si comporta correttamente
replica su due stagioni
9 celle oltre Benjamini-Hochberg
```

Controllo negativo su mercato simulato **senza alcun segnale**: stessa
selezione, **CLV +0.0702**. L'artefatto è più grande dell'effetto.

La differenza era temporale:

```
cella circolare (usa la chiusura per selezionare)   +0.0440
cella point-in-time onesta (solo l'apertura)        −0.0442
```

Il criterio selezionava le righe dove `movement = close_fair − consensus_open`
era positivo e poi le segnava con `clv = close_fair × prezzo − 1`: la stessa
chiusura da entrambe le parti. Al momento della scommessa quel movimento non è
nemmeno conoscibile.

**Principio architetturale che ne discende:** nessuna informazione successiva
al timestamp decisionale può entrare nel dataset di previsione.

Fissato da `test/fiorino/test_no_lookahead.py`, che fallisce se la simulazione
smette di riprodurre l'artefatto. È la seconda volta che il progetto ci cade —
in M6 il braccio MARKET mostrava +0.0234 per pura definizione.

---

## 4. Cosa è stato imparato davvero

### 4.1 Mercati minori

Misurato due volte, per strade indipendenti:

```
skill contro la climatologia   prime −  inferiori = −0.0451   6 paesi su 6
CLV                            TOP −0.0449   LOWER −0.0594
margine                        più alto nelle inferiori, 6 paesi su 6
scarto di calibrazione         NON distinguibile (p = 0.31)
```

Meno affilato **non** significa più sbagliato. Il book fa pagare la propria
ignoranza: il margine sale dove lo skill scende, con correlazione −0.83 sui sei
paesi appaiati. *Mercato meno efficiente ≠ edge gratuito.*

### 4.2 Dispersione dei prezzi ed execution

```
MARKET_MAX   −0.0176        ← miglior prezzo disponibile
BETFAIR_EX   −0.0238
BET365       −0.0630
SKYBET       −0.0970        ← peggiore
```

**Otto punti percentuali** fra il miglior prezzo e il peggiore: più grande
dell'effetto attribuibile a quasi tutte le caratteristiche analizzate. La
catena che conta è `segnale → probabilità equa → prezzo ottenibile →
commissioni → EV netto`, e i primi due anelli non bastano.

### 4.3 Il mercato è il benchmark

La baseline corretta è `MODELLO vs MERCATO`, mai `MODELLO vs random`. Un
modello che batte il caso ma perde contro il prezzo non ha dimostrato niente di
commerciabile — ed è esattamente il caso di questo.

---

## 5. Cosa resta non misurato

L'unica famiglia non testata soddisfa una condizione diversa: **informazione
disponibile al sistema prima che venga incorporata nel prezzo.**

```
formazione ufficiale
      ↓  timestamp reale di pubblicazione
quote immediatamente precedenti
      ↓
quote immediatamente successive
      ↓
movimento del mercato
```

Il problema non è la disponibilità della formazione: è il **timestamp**. Un
archivio che contiene `lineup = X` non dice *quando il mercato poteva
conoscere X*, e senza quello il rischio di look-ahead resta — come il §3
dimostra costare 8,8 punti percentuali di illusione.

Nessuna fonte pubblica, gratuita o a pagamento, porta quell'istante. È stato
cercato: non esiste. Esiste solo se qualcuno lo registra mentre accade.

---

## 6. Raccolta point-in-time

Il collector delle quote è **operativo** dal 2026-09-09 e ha prodotto il primo
dato point-in-time del progetto. Quello delle formazioni è il prossimo
componente necessario.

L'obiettivo iniziale **non** è trovare un edge. È costruire un dataset in cui
ogni osservazione permetta di ricostruire *cosa sapevamo esattamente in
quell'istante e quale prezzo era disponibile*.

`known_at` significa sempre e solo l'istante in cui **il nostro** poll ha visto
il fatto: è un limite superiore, ed è sicuro solo se la sua **larghezza**
viaggia con lui (`known_at_uncertainty_seconds`, calcolata dallo scarto reale
fra poll avvenuti).

---

## 7. No-peeking policy

Per i prossimi **sei mesi**: nessuna ottimizzazione basata sui risultati
intermedi del collector. Niente modifiche a feature, soglie, finestre, target,
modelli o criteri di selezione mentre il dataset si accumula.

```
COLLECT → FREEZE → ANALYZE
```

non

```
COLLECT → LOOK → MODIFY → LOOK AGAIN → MODIFY AGAIN
```

Lo scopo è impedire che il dataset venga trasformato progressivamente in
risposta alla propria stessa evidenza. C'è anche una ragione di potenza: con
l'orizzonte attuale ogni analisi avrebbe un effetto minimo rilevabile più
grande di ciò che cerca — è già successo, con MDE 0.1068 su un effetto di 0.04.

---

## 8. Cancelli di promozione

`PROMOTED = 0` finché tutti e sei non sono superati.

| # | cancello | cosa richiede |
|---|---|---|
| 1 | integrità point-in-time | nessun look-ahead |
| 2 | significatività | sopravvive alla correzione per confronti multipli |
| 3 | replica out-of-sample | su dati non usati per la scoperta |
| 4 | confronto col mercato | aggiunge informazione rispetto al benchmark |
| 5 | economia netta | sopravvive a commissioni, spread, limiti, slippage, disponibilità del prezzo |
| 6 | stabilità | non dipende da una stagione, una lega, pochi eventi, una soglia, un book |

Il Gate 5 non è teorico: ha già ucciso l'unica cella positiva della ricerca
(§1). Il Gate 1 ha già ucciso il risultato più convincente (§3). Il Gate 2 ha
già ucciso 14 ipotesi su 14.

---

## 9. Posizione scientifica al 2026-09-09

```
ricerca ex-post storica
        ↓
     CHIUSA
        ↓
nessun edge robusto identificato
        ↓
raccolta point-in-time
        ↓
   NON ANCORA ANALIZZATA
        ↓
   PROMOTED = 0
```

Metodologicamente è una conclusione **positiva**. Il sistema non ha trovato ciò
che voleva trovare, ma ha dimostrato di saper riconoscere e rifiutare:
dispersione scambiata per edge, look-ahead, selezione post-hoc, risultati che
evaporano dopo la correzione, e vantaggi troppo piccoli per coprire i costi.

Lo stato macchina-leggibile di ogni affermazione è in
[`CLAIMS.json`](research/CLAIMS.json); le fonti in
[`SOURCES.json`](research/SOURCES.json).

---

## 10. Principio finale

Il progetto non va costruito per trovare scommesse. Va costruito per
**determinare se esiste evidenza sufficiente ad autorizzarne una**.

```
nessuna evidenza → NO BET
```

e non

```
nessuna evidenza → troviamo comunque qualcosa → BET
```

Non è una strategia che ha fallito. È un sistema di ricerca che ha eliminato
diverse strategie false **prima** che diventassero decisioni finanziarie.

La prossima domanda non è «quale altra feature aggiungiamo». È:

> Possiamo dimostrare che un'informazione point-in-time, non ancora
> incorporata nel prezzo, produce un vantaggio replicabile?

Finché non è dimostrato empiricamente, la risposta operativa resta **NO BET**.

---

---

# Registro della fase precedente — laboratorio v1.0

Quanto segue è il verbale della fase M1–M6, conservato integralmente: è
l'evidenza su cui poggia la chiusura dichiarata sopra.

## Il risultato, in tre righe

```
M5   MODELLO            <   MERCATO           in 10 dataset su 10
M6   MERCATO + MODELLO  ≈   MERCATO           in 10 dataset su 10
                        <   in 9 su 10, tutti i CI contengono lo zero
```

Non è «il modello non funziona». È l'affermazione più forte:

> **Il modello non contiene informazione incrementale misurabile rispetto al
> mercato.**

E in metà dei campionati è peggio di neutro: il peso ottimale **non vincolato**
è negativo in 5 dataset su 10, fino a **−0.51**. Dove è negativo, il miglior
uso del modello sarebbe stato `mercato − α · modello` — cioè trattarne
l'opinione come un indicatore di errore.

---

## Cosa è stato costruito

| fase | cosa | verificato da |
|---|---|---|
| **M1** | data layer, identità squadra, point-in-time | 10 stagioni × 8 leghe; il fuzzy propone di fondere **Manchester United e City a 0.926** — regola 9 confermata sul campo |
| **M2** | ricostruzione del mercato, chiusura de-viggata | `captured_at` nullable per progetto: nessun timestamp inventato |
| **M3** | CLV contro la chiusura reale | identità di calibrazione riprodotta a **6.2e−06** |
| **M4** | backtest walk-forward a coorti | tre partite simultanee → stake `[50, 50, 50]`, mai `[50, 75, 112.50]` |
| **M5** | adapter modelli, pricing multi-mercato | 219.010 predizioni, **0 violazioni PIT** |
| **M6** | informazione incrementale | 20 CI, **20 contengono lo zero** |

453 test. Il CI ricostruisce l'intero schema da un clone pulito a ogni PR.

---

## I cinque numeri che contano

### 1. Lo yield mente, il CLV no

Validazione M4 su 30 combinazioni strategia × dataset:

```
  CLV corretto    30/30
  yield corretto  23/30
```

Il falso positivo peggiore, `take_home` su ENG_PL 2019-20:

> **+11.91% di yield, +287.1% di crescita** — con CLV −0.0272 e t = −11.5.

E il falso negativo simmetrico, l'oracolo chiaroveggente su DEU_BL1 2024-25:
−1.33% di yield con CLV +0.1010 e t = +32.7. Una strategia che vede il futuro
sembrava in perdita.

### 2. Un modello peggiore del mercato trova «value» ovunque

Un terzo di tutte le selezioni con edge dichiarato sopra il 5%, con punte a
**+521% di EV attesa** — da un modello che perde contro la chiusura in ogni
singolo dataset. Il CLV di quelle scommesse è negativo **30 volte su 30**, ed è
peggiore del controllo senza opinione in 7 dataset su 10.

Kelly su quella confidenza punterebbe più forte proprio dove il modello sbaglia
di più.

### 3. Un solo parametro basta a produrre overfitting misurabile

In tre dataset l'ottimizzatore M6 trova sul training un peso del **17–21%** per
il modello. Fuori campione quel peso non produce alcun guadagno, e in due casi
su tre peggiora le cose.

Un numero. Vincolato a `[0, 1]`. Stimato su duecento partite. Il guadagno
in-sample era **garantito non negativo** (`w = 0` è sempre ammissibile), ed è
evaporato.

Questo è il risultato che rende difficile auto-convincersi che
`CatBoost + LightGBM + 40 feature + stacking` risolverebbe il problema.
Migliorerebbero il training. Non c'è alcuna evidenza che migliorino il deploy —
e c'è una misura diretta che dice il contrario.

### 4. Il divario è grande rispetto a ciò che il mercato stesso impara

Entrambi i numeri sono medie sugli **stessi 10 dataset**:

```
  informazione che il mercato acquisisce fra prematch e chiusura   0.00099 Brier
  quanto il modello è peggio della chiusura                        0.01012 Brier
                                                                   ────────────
                                                                         10.2x
```

Il modello dovrebbe recuperare **dieci volte** l'intera finestra in cui il
mercato stesso impara qualcosa, solo per arrivare alla pari.

Questo dice quanto è **grande** il divario. Non dice di che cosa sia fatto —
vedi la sezione seguente.

### 5. Il mercato è meno affilato nelle serie inferiori, e costa di più

Il primo risultato del progetto in cui due gruppi di mercati si distinguono
davvero, replicato paese per paese. 235.806 partite, 38 divisioni, quota
prematch bet365.

```
  skill del mercato contro la climatologia della divisione
    prime divisioni        +0.0879
    divisioni inferiori    +0.0428      permutazione p = 0.0001

  appaiato dentro il paese, 6 paesi con entrambe le serie
    skill più basso nella serie inferiore     6/6      test dei segni p = 0.031
    margine più alto nella serie inferiore    6/6      media +0.0127
    scarto di calibrazione più alto           2/6      nessuna direzione
```

Il Brier grezzo delle serie inferiori è più alto, ma il Brier grezzo non misura
l'efficienza: misura anche quanto è incerto il campionato. Lo skill contro la
climatologia toglie quell'entropia, ed è su quello che il risultato regge.

**E resta un risultato che non autorizza a scommettere.** Meno affilato non è
scalibrato: la calibrazione, che sarebbe la firma del prezzo sbagliato, non si
muove. Uno skill più basso è ugualmente compatibile con serie inferiori
semplicemente meno prevedibili — un previsore perfetto avrebbe anche lì uno
skill più basso. E il margine è più alto proprio dove lo skill è più basso
(correlazione −0.83 sui sei paesi): **il book fa pagare la propria ignoranza**,
e si pagano 1.27 punti percentuali in più esattamente dove si spererebbe di
trovare il vantaggio.

Dettagli in [efficienza fra divisioni](validation/division-efficiency.md).

---

## Cosa questi risultati NON dimostrano

Questa sezione esiste perché la tentazione opposta è forte quanto quella di
sopravvalutare un edge: usare un risultato negativo per chiudere più domande di
quante ne abbia effettivamente chiuse.

Quello che è dimostrato:

> Il modello **attuale** non estrae informazione incrementale da **ciò che
> usa** — gol segnati e subiti, con decadimento temporale — su questi 10
> campionati-stagione.

Quello che **non** è dimostrato, e che sarebbe un'estrapolazione:

* **Che una feature non testata sia esaurita dal mercato.** `MODELLO A + xG →
  nessun valore` non implica `qualunque uso di xG → nessun valore`. Non abbiamo
  mai testato xG. La rappresentazione, la granularità e il momento in cui una
  feature entra nel modello cambiano il risultato, e nessuna delle tre è stata
  variata.
* **Che il mercato sia efficiente.** È stato misurato che **questo** modello non
  lo batte, e che la chiusura è migliore della prematch di una quantità
  minuscola. Nessuna delle due cose è un'affermazione sull'efficienza.
* **Che i movimenti di quota siano inutili.** Il tetto misurato dice che sono
  **piccoli**, non che siano zero — il segno è consistente in 10 dataset su 10.
  Dice che è improbabile che bastino da soli come prima scommessa di ricerca.
* **Che una classe di informazione manchi.** Il divario è dieci volte la
  finestra prematch→chiusura. Questo ne misura la taglia, non la composizione:
  potrebbe essere informazione assente, o la stessa informazione rappresentata
  peggio.

La differenza pratica: il peso dell'evidenza oggi sta dalla parte del mercato, e
questo è sufficiente per **ordinare** le priorità di ricerca. Non è sufficiente
per **eliminare** una direzione senza averla misurata.

---

## Le due trappole evitate, e come

Entrambe producono un risultato che **sembra** una scoperta.

### La tautologia del CLV

Il CLV si misura contro la chiusura. Quindi una previsione costruita **sulla**
chiusura mostra CLV positivo per costruzione: scommette solo prezzi migliori
della chiusura, perché quella è la definizione di entrambe le cose.

Questa strategia esiste già nel repository come **controllo positivo
chiaroveggente** (`TakeValueVsClose`, etichettata `oracle_beats_close`). Senza
la separazione, sarebbe rientrata dalla finestra travestita da risultato di M6.

La disciplina che lo impedisce:

```
  PREMATCH  →  decide e scommette
  CLOSING   →  valuta, e nient'altro
```

Nel percorso deployable nessun componente legge un prezzo di chiusura.

**La trappola si è comunque ripresentata**, attenuata, nel controllo. L'arm
`MARKET` — line shopping puro, nessun modello — mostrava CLV **+0.0234**,
positivo in 7 dataset su 8. Decomposto:

| | edge alla scommessa (per costruzione) | CLV misurato | deriva reale |
|---|---|---|---|
| ENG_PL 2019-20 | **+0.0463** | +0.0445 | **−0.0017** |
| PRT_L1 2024-25 | **+0.0586** | −0.0198 | **−0.0783** |

Il CLV era la condizione d'ingresso riscritta. L'unica parte reale è negativa in
entrambi.

### Il leakage del peso

`w` è l'unico parametro di tutto M6 stimato dagli esiti — quindi l'unica nuova
via per cui il futuro può raggiungere il passato, e arriva da una porta che
nessuno stava guardando: la disciplina PIT sorveglia le *previsioni*, non i
*pesi*.

Tre difese, ridondanti di proposito: il filtro sta dentro `fit_weight` e non nel
chiamante; il fitter registra il massimo `settled_at` che ha **davvero**
consumato, così `v_weight_leakage` può fallire invece di rileggere il confine
dichiarato; e un test costruisce il caso in cui un fitter che sbircia
risponderebbe `w > 0.9` invece di `w ≈ 0` — con il controllo che dimostra che
quel test *può* fallire.

Un audit che non può fallire non è un audit. La prima versione che avevo
scritto era un `WHERE FALSE`.

---

## Cosa è stato ritirato

Il laboratorio ha smentito anche le proprie affermazioni precedenti, e le
smentite sono parte del verbale:

* **L'asimmetria HOME/AWAY nel drift** (HOME −0.0043 / AWAY +0.0045), su una
  stagione, sembrava un risultato solido. Su 10 dataset **non replica**: AWAY è
  positivo in 4–5 su 10 e le medie sono quasi identiche. Ritirata.
* **La «firma della miscalibrazione»** — l'ipotesi che lo yield decrescesse al
  crescere della soglia — decresce in 4 dataset su 10. Solo le medie aggregate
  sono monotone. Ritirata.
* **Il baseline «−0.028, t −10.66»** non è una costante globale: varia da
  −0.029 a −0.065 per dataset.

---

## Un bug che vale quanto un risultato

Il `.gitignore` ereditato da penaltyblog conteneva `data/` non ancorata, che in
questo albero corrisponde anche a `fiorino/data/`. **Sette migrazioni, il ledger
di identità, il manifest del lake e entrambi gli script di validazione erano
scritti, testati e mai committati.**

I commit di M2, M3 e M4 sono arrivati nel repository senza lo schema su cui il
loro stesso codice si appoggia. `git add -A` non ha segnalato nulla — saltare un
file ignorato è il suo comportamento corretto. La suite non poteva accorgersene:
legge l'albero di lavoro, e l'albero era completo.

> Codice presente nell'albero di lavoro ≠ codice presente nel repository.

È esattamente il tipo di problema che rende una ricerca quantitativa non
riproducibile senza che nessuno se ne accorga. Da qui `test_repo_hygiene.py` e
il CI clean-clone: ogni PR deve poter partire da zero.

---

## Limiti dichiarati

* **Un solo modello.** Dixon-Coles, emivita 180 giorni. Gli altri cinque di
  `MODELS` non sono validati.
* **Un solo mercato nel confronto.** 1X2. Handicap asiatici e totals sono
  quotati e verificati coerenti, ma senza una chiusura di riferimento con cui
  misurarli.
* **Nessun dato timestampato.** Football-Data dà due punti per partita. Ogni
  segnale di microstruttura è quindi non verificabile per tradabilità, non solo
  non implementato. Vedi [`market-channel`](validation/market-channel.md).
* **Il prior di lega non è esercitato** dalla validazione: con `min_train = 60`,
  al primo fit tutte le squadre hanno già giocato.
* **Il fetch della stagione in corso non è mai stato eseguito.**
  `www.football-data.co.uk` è fuori dall'allowlist di egress dell'ambiente. La
  catena M2→M6 è validata su archivi Football-Data reali mirrorati altrove.

---

## Perché questo è il punto di partenza giusto

Un repository che mostra ROI positivi su backtest è comune e quasi sempre
sbagliato: leakage, overfitting, o fortuna su una stagione — e le tre cose sono
indistinguibili senza CLV.

Qui c'è il contrario: un'infrastruttura che ha misurato **+11.91% di yield e
+287% di crescita** e ha detto, con t = −11.5, che era rumore.

La domanda successiva non è «come aumentiamo il rendimento». È:

> **quale nuova informazione arriva abbastanza tardi, abbastanza concentrata e
> abbastanza lentamente da non essere già riflessa nel prezzo?**

Le formazioni confermate sono una delle poche candidate che soddisfano tutte e
tre le condizioni. Il disegno dell'esperimento, i criteri di arresto registrati
in anticipo e il contratto dati minimo sono in
[`architecture/next-experiment.md`](architecture/next-experiment.md).

La conclusione scomoda di quel documento: il lavoro mancante è **acquisizione
dati e ingestione**, non modellazione. Lo schema per le quote timestampate e il
suo lettore point-in-time sono già scritti e non sono mai stati esercitati —
non esiste una riga `TIMESTAMPED` in nessuno dei 10 dataset.

**La scansione di ipotesi** ha poi cercato ciò che i dati esistenti possono
esprimere — riposo, congestione, motivazione, calendario, banda di prezzo — con
la correzione per test multipli che quella procedura richiede: 14 situazioni ×
3 selezioni su 3.502 partite, **zero sopravvissute**. Con il limite che
qualifica il risultato: la scansione può escludere bias più grandi di ~4–7
punti di probabilità, non bias di 2–3 punti, che sarebbero comunque molto
profittevoli. Vedi
[`validation/hypothesis-scan.md`](validation/hypothesis-scan.md).

Il sottoprodotto più utile è una tabella di calibrazione: **il prezzo Pinnacle
de-viggato segue la frequenza realizzata in ogni banda**, dal 3% all'85%,
scostamento massimo |z| = 1.38. E il bias favorito-longshot, il mispricing più
documentato in letteratura, **non è presente in questo mercato** — il margine
non cresce verso i longshot, cresce verso i favoriti.

M6.5 ha confermato il vincolo con delle prove invece che con un'assunzione:
otto sonde di rete, un solo host raggiungibile, e nessuna fonte pubblica di
quote timestampate sul calcio. Vedi
[`architecture/data-acquisition.md`](architecture/data-acquisition.md). L'audit
della catena point-in-time end-to-end è costruito e testato; le due fonti no,
e non sono state simulate su fixture per farle sembrare tali.

---

## L'app

[`architecture/webapp.md`](architecture/webapp.md) — dashboard Streamlit
apribile da telefono. Mostra lo stato reale del laboratorio: **nessun edge
validato**, e il vincolo è nel codice (`PROMOTED = {}`) con un test che
fallisce se viene alzato senza una promozione registrata. Non esiste un livello
`BET`.

---

## Protocollo di ricerca

Il laboratorio ha ora regole scritte, non solo consuetudini:

* [**Protocollo di ricerca**](research/RESEARCH_PROTOCOL.md) — dieci regole, e
  il vocabolario obbligatorio degli esiti. «Promettente» non è un esito.
* [**Gate di promozione**](research/PROMOTION_GATES.md) — sei cancelli, il P&L
  è l'ultimo.
* [**Registro delle ipotesi**](research/HYPOTHESIS_REGISTRY.md) — tutto ciò che
  è stato testato, incluse le affermazioni che il laboratorio ha ritirato.
* [**Layer temporale del mercato**](architecture/market-path.md) — PR #3:
  adapter e viste del percorso del prezzo, costruiti prima dei loro dati.
  «Perché il mercato si è mosso del 9%» è la domanda; oggi manca il percorso.
* [**Efficienza per campionato**](validation/league-efficiency.md) — le
  prime divisioni sono indistinguibili fra loro: la dispersione fra campionati
  è più piccola dell'incertezza dentro un campionato.
* [**Piano di acquisizione dati**](research/DATA_ACQUISITION_MASTER_PLAN.md) —
  il codice è congelato, il dato no. Le tre azioni fuori da questo ambiente.
* [**Audit delle fonti**](research/FREE_SOURCES_AUDIT.md) e
  [`SOURCES.json`](research/SOURCES.json) — otto fonti verificate campo per
  campo. Una sola è PIT-usabile, e non è raggiungibile da qui.
* [**Catalogo dei dati**](research/DATA_CATALOG.md) — cosa c'è, cosa manca,
  cosa è raggiungibile.
* [**Modulo dell'esperimento**](research/EXPERIMENT_TEMPLATE.md) — si compila
  prima di guardare i dati.
* [**Stato dei claim**](research/CLAIMS.json) — machine-readable: ogni
  affermazione con PROVEN / TESTED_BUT_LIMITED / UNTESTED / DATA_GAP /
  NOT_DEMONSTRATED, e il test che la verifica. Validato dalla suite: un claim
  marcato PROVEN che nomina un test inesistente fa fallire il build.
* [**Gate Audit finale**](research/GATE_AUDIT.md) — clone pulito, mappa
  claim→test, e i quattro difetti che solo un ambiente vuoto poteva rivelare.
* [**Audit del PR #1**](research/PR1_AUDIT.md) — 4 MUST FIX, nessuno di natura
  statistica.

---

## Indice

**Architettura**
[panoramica](architecture/fiorino-quant.md) ·
[modello dati quote](architecture/odds-model.md) ·
[CLV](architecture/clv.md) ·
[backtest](architecture/backtest.md) ·
[modelli e pricing](architecture/models.md) ·
[ensemble](architecture/ensemble.md) ·
[storage e versioning](architecture/storage-and-versioning.md)

**Validazione**
[metodologia CLV](validation/clv-methodology.md) ·
[contratto dati di mercato](validation/market-data-contract.md) ·
[review M1–M3](validation/validation-report.md) ·
[motore M4](validation/backtest-validation.md) ·
[modelli M5](validation/model-validation.md) ·
[informazione incrementale M6](validation/incremental-information.md) ·
[canale di mercato](validation/market-channel.md) ·
[efficienza fra divisioni](validation/division-efficiency.md)

**Prossimo passo**
[esperimento formazioni: disegno e contratto dati](architecture/next-experiment.md)
