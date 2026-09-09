# Fiorino Quant — laboratorio v1.0

**Stato: nessun edge trovato. Nessun edge nascosto.**

Sei fasi, 10 campionati-stagione reali, 7 paesi, due epoche. Il laboratorio è
completo e la risposta che produce, su questi dati, è negativa. Questo documento
è il verbale.

Chi arriva qui cercando una strategia profittevole non la troverà. Chi arriva
cercando un'infrastruttura capace di **dire di no**, quella c'è, ed è
l'unica cosa che il progetto rivendica.

---

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

## I quattro numeri che contano

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
[canale di mercato](validation/market-channel.md)

**Prossimo passo**
[esperimento formazioni: disegno e contratto dati](architecture/next-experiment.md)
