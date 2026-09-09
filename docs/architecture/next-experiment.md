# Il prossimo esperimento: impatto delle formazioni

**Stato: specificato, non implementato. Bloccato sull'acquisizione dati.**

Segue la disciplina che il progetto usa da M1: prima il disegno e i criteri di
accettazione, poi il codice. Con una differenza — questa volta il blocco non è
una decisione da prendere, è un dato che non esiste ancora.

---

## Perché le formazioni, e non le altre voci della lista

Le formazioni confermate hanno tre proprietà **contemporaneamente**, e sono
poche le variabili che le hanno tutte e tre:

| | proprietà | perché conta |
|---|---|---|
| 1 | **arrivano a un istante preciso** — tipicamente 60–75 minuti dal calcio d'inizio | c'è un prima e un dopo misurabili, non una feature che sfuma nel tempo |
| 2 | **possono cambiare bruscamente la probabilità** — portiere sostituito, centravanti indisponibile, turnover inatteso | l'effetto, se c'è, è grande rispetto al rumore |
| 3 | **la velocità di incorporazione è lenta rispetto alla finestra** | il mercato non le conosce giorni prima |

xG, riposo, congestione e meteo sono disponibili con giorni di anticipo. Questo
non dimostra che siano esaurite dal prezzo — non sono mai state testate, e la
[sezione «cosa non è dimostrato»](../FINDINGS.md) del verbale lo dice
esplicitamente — ma li rende candidati **peggiori come prima scommessa**, perché
mancano della proprietà 3 e quindi della finestra in cui un sistema potrebbe
arrivare prima del mercato.

---

## Fase 1 — misura descrittiva, prima di qualunque modello

**Domanda:** il mercato si muove, in modo consistente, dopo la pubblicazione
delle formazioni?

Non «riusciamo a prevedere il risultato». Se non esiste nemmeno un effetto di
mercato osservabile, non c'è niente da estrarre e la fase 2 non deve iniziare.

```
   T-120min      T-60min      T-30min       close
      │             │            │            │
      └──── formazioni pubblicate ────┘
              (istante noto)

   misura:  |Δ log-odds|  in ciascuna finestra
```

Condizionato a:

* titolari confermati come attesi (controllo: nessuna sorpresa)
* assenza inattesa di un titolare
* sostituzione del portiere
* turnover marcato rispetto all'undici modale recente

Il **log-odds** e non la probabilità, perché il movimento è moltiplicativo: uno
spostamento da 0.10 a 0.12 e uno da 0.50 a 0.52 non sono lo stesso evento, e la
differenza di probabilità li confonde.

Il gruppo di controllo è la parte che rende la misura interpretabile. Il mercato
si muove **comunque**: già misurato, mediana 2,29 punti di probabilità fra
prematch e chiusura, oltre 1 punto nell'83% delle partite (vedi
[`market-channel`](../validation/market-channel.md)). La domanda non è se si
muove nella finestra delle formazioni, ma se si muove **di più** che in una
finestra di controllo di pari durata senza evento.

### Criterio di arresto, registrato in anticipo

Perché registrarlo prima è l'unica differenza fra un criterio e una
razionalizzazione:

> **Si procede alla fase 2 solo se** il movimento medio nella finestra
> post-formazioni, sulle partite con un'assenza inattesa di un titolare, supera
> quello della finestra di controllo con un intervallo di confidenza bootstrap
> appaiato che **esclude lo zero**, su almeno **due campionati indipendenti**.
>
> **Non** si procede se l'intervallo contiene lo zero, per quanto favorevole sia
> la stima puntuale. È la stessa regola che ha chiuso M6, e vale anche quando il
> risultato piace.

---

## Quanto deve essere grande il pilot

La domanda va risposta **prima** di raccogliere, non dopo. La dispersione dei
movimenti di prezzo è misurabile oggi sui dati che ci sono: su 10.506 selezioni,
il movimento prematch→chiusura in log-odds ha **deviazione standard 0.1414**.

È un limite superiore per la finestra dell'event study, che è un
sotto-intervallo di quella: la stima che segue è quindi **conservativa**.

Dimensione richiesta per gruppo (evento contro controllo, test a due code,
α = 0.05, potenza 0.80):

| effetto (log-odds) | in probabilità a p = 0.30 | n per gruppo |
|---|---|---|
| 0.02 | +0.42 punti | **784** |
| 0.05 | +1.06 punti | **125** |
| 0.10 | **+2.14 punti** | **31** |
| 0.15 | +3.24 punti | 14 |
| 0.20 | +4.36 punti | 8 |
| 0.30 | +6.65 punti | 3 |

### Il pilot da 100–200 partite è dimensionato per una domanda sola

Questo cambia il disegno, ed è la ragione per cui vale la pena fare il conto
prima:

* **Domanda aggregata** — «il mercato si muove di più dopo le formazioni che in
  una finestra di controllo?» Ogni partita ha una formazione, quindi 200
  partite danno 200 eventi: sufficienti per rilevare **~1 punto di
  probabilità**. Il pilot è dimensionato correttamente per questo.

* **Ripartizione per categoria** — «portiere fuori», «attaccante fuori»,
  «3+ assenze». Qui il pilot è **troppo piccolo di un ordine di grandezza**. Un
  portiere titolare fuori a sorpresa capita nel 3–5% delle partite: i 31 eventi
  necessari per un effetto di 2 punti richiedono **600–1.000 partite**, non 200.

Il pilot resta la cosa giusta da fare per prima — se l'effetto aggregato non
c'è, non c'è nulla da ripartire e si sono risparmiati mesi. Ma va presentato per
quello che può decidere, e la ripartizione A–E è una fase successiva con un
requisito di raccolta molto diverso.

---

## Il disegno della misura: doppia differenza

Due elementi rendono inutile un semplice «quanto si è mosso il prezzo dopo le
formazioni»: i prezzi si muovono comunque, e si muovono **più in fretta**
avvicinandosi al kickoff — quindi qualunque finestra più vicina all'inizio mostra
più movimento, qualunque cosa vi accada dentro.

```
  ┌──────────── pre ────────────┬──────────── post ────────────┐
  │                             │                              │
T_pub − w                    T_pub                        T_pub + w
                                ▲
                        formazione pubblicata

  dentro la partita   post − pre        elimina la volatilità della partita
  fra le partite      trattate − controllo   elimina l'accelerazione verso
                                              il kickoff, perché entrambi i
                                              gruppi sono misurati nella
                                              stessa finestra RELATIVA alla
                                              pubblicazione
```

Il controllo è una partita la cui formazione è uscita come prevista: ha anch'essa
un istante di pubblicazione, quindi ha entrambe le finestre — semplicemente non
ha shock.

I prezzi sono convertiti in log-odds prima di differenziare: un movimento da
1.10 a 1.12 e uno da 5.00 a 5.10 non sono lo stesso evento su scala di
probabilità, e mediarli lì lascerebbe dominare le quote lunghe per aritmetica
invece che per informazione.

## Il punteggio di shock, prima di qualunque modello

```
  shock = Σ  peso_posizione × max(quota_di_titolarità − quota_del_sostituto, 0)
```

Un righello, non un modello. Tre proprietà deliberate:

* **Uno scambio alla pari non è uno shock.** Un sostituto che gioca quasi
  sempre non è una notizia.
* **Un upgrade non conta negativo.** Un sostituto migliore è un evento diverso;
  lasciarlo andare sotto zero annullerebbe segnale vero nella media.
* **I pesi sono grossolani apposta.** Un portiere pesa più di un centrocampista;
  fingere di conoscere il rapporto a due decimali sarebbe un modello travestito
  da costante.

Costruire CatBoost prima di sapere se questa versione elementare si muove
insieme al mercato nasconderebbe la risposta invece di trovarla: se il segnale
non esiste in una forma così semplice, un modello complesso impara soprattutto
a fittare rumore.

---

## Fase 2 — solo se la fase 1 passa

Ablation identica a M6, perché il metro deve restare lo stesso:

```
   MARKET                       (prezzo pre-formazioni, de-viggato)
   MARKET + LINEUP              (peso stimato solo sul training)
```

Con gli stessi sei gate, nello stesso ordine, e il P&L per ultimo.

Nota sulla tradabilità, che qui è più stretta che in M6: il segnale è utile solo
se si può agire **fra** la pubblicazione delle formazioni e il momento in cui il
mercato le ha assorbite. Un backtest che decide al calcio d'inizio — la
convenzione di M4, corretta per dati non timestampati — misurerebbe qualcosa di
già incorporato. La fase 2 richiede quindi un istante di decisione reale, non
una convenzione.

---

## Il contratto dati minimo

Questa è la parte bloccante, ed è il vero contenuto di questo documento.

### Quote

| requisito | valore |
|---|---|
| `capture_precision` | `TIMESTAMPED` — con `captured_at` reale, non dedotto |
| cadenza | almeno T−180, T−120, T−90, T−60, T−45, T−30, T−15 minuti |
| book | il libro di riferimento (sharp) più almeno un book soft |
| mercato | 1X2 come minimo; handicap e totals se disponibili |
| copertura | l'intera stagione, non le sole partite con eventi |

L'ultima riga non è un dettaglio: raccogliere solo le partite con un'assenza
inattesa produce un campione selezionato sull'evento e rende il gruppo di
controllo inesistente.

### Formazioni

| requisito | valore |
|---|---|
| istante di pubblicazione | **timestamp reale della pubblicazione**, non l'ora del calcio d'inizio meno un'ora |
| contenuto | undici titolari, per identificatore di giocatore stabile |
| storico | l'undici delle partite precedenti, per definire «inatteso» |
| identità giocatore | risolta come le squadre in M1 — **nessun fuzzy matching nel dataset analitico** |

L'ultima riga è la regola 9 applicata a una nuova entità. Un giocatore mal
identificato produce un'assenza inattesa fantasma, che è esattamente il tipo di
errore che si presenterebbe come segnale.

### Quanto storico serve

Con una cadenza di raccolta in avanti, il dato non esiste retroattivamente:
va accumulato. Una stagione di un campionato maggiore dà ~380 partite, di cui
una frazione con un'assenza inattesa di un titolare. Il criterio di arresto
chiede **due campionati indipendenti**, quindi l'ordine di grandezza è
**una stagione su due campionati raccolti in parallelo**, non un backfill.

Questo è il costo reale dell'esperimento, ed è tempo, non calcolo.

---

## Cosa c'è già, e cosa manca

Il lato che di solito costa di più è già costruito e **non è mai stato
esercitato**:

```sql
-- 0006_odds.sql — il vincolo che rende impossibile inventare un istante
CHECK ((capture_precision = 'TIMESTAMPED') = (captured_at IS NOT NULL))

-- 0007_odds_views.sql — il lettore point-in-time, che legge SOLO timestamped
CREATE OR REPLACE MACRO odds_as_of(at_ts) AS TABLE
...
WHERE capture_precision = 'TIMESTAMPED' AND captured_at <= at_ts
```

Non esiste una sola riga `TIMESTAMPED` in nessuno dei 10 dataset: Football-Data
dà due punti per partita, e M2 lo registra onestamente invece di fabbricare
istanti. `odds_as_of()` è quindi scritto, testato e inutilizzato — aspetta un
feed.

| componente | stato |
|---|---|
| schema quote timestampate | **c'è**, mai usato |
| lettore point-in-time timestampato | **c'è**, mai usato |
| ablation, bootstrap appaiato, gate | **c'è** (M6), riutilizzabile così com'è |
| CLV, backtest a coorti, settlement | **c'è** (M3, M4) |
| identità giocatore | **manca** — nuova entità, stessa disciplina delle squadre |
| ingestione quote timestampate | **manca** — è un poller, non un modello |
| fonte formazioni con timestamp | **manca** — ed è il vero blocco |

Il lavoro mancante è **acquisizione dati e ingestione**, non modellazione. È una
conclusione scomoda perché è la parte meno interessante, ed è per questo che
vale la pena averla scritta prima di iniziare.

---

## Il blocco operativo

Nulla di tutto questo è raggiungibile dall'ambiente attuale. La ricerca delle
fonti è documentata in [`data-acquisition.md`](data-acquisition.md), con un
risultato che vale la pena isolare:

> Il dataset di **BeatTheBookie** (Kaunitz et al., 2017) contiene serie continue
> di quote per ~113.860 partite. È ospitato su Dropbox e Google Drive, **entrambi
> bloccati**. Una regola di allowlist separa questo esperimento dai suoi dati.

Per le formazioni non esiste invece **nessuna** fonte pubblica con istante di
pubblicazione: quel fatto va raccolto in avanti, e resta il vero collo di
bottiglia.

La fase successiva non inizia con una riga di codice. Inizia con la decisione su
**quale fonte** e **con quale accesso**.
