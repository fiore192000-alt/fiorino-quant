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

Nulla di tutto questo è raggiungibile dall'ambiente attuale: la policy di egress
blocca già `www.football-data.co.uk`, e un feed di quote timestampate o di
formazioni richiede fonti che non possiamo contattare da qui.

La fase successiva non inizia con una riga di codice. Inizia con la decisione su
**quale fonte** e **con quale accesso**.
