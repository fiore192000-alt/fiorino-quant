# M6 — informazione incrementale

M5 ha stabilito che la chiusura Pinnacle de-viggata batte il modello in 10
dataset su 10. M6 non chiede «troviamo un modello migliore»: chiede una cosa
diversa e più precisa.

> **Il modello contiene informazione che il mercato non ha?**

Sono domande davvero distinte. Un modello che perde nettamente contro il mercato
può comunque *migliorarlo*, se sbaglia in modo indipendente. E un modello che non
lo migliora di nulla è un modello per cui smettere di pagare, per quanto
sofisticato lo si renda.

---

## La trappola che decide tutto il disegno

Questa è la parte da leggere anche saltando il resto.

Il CLV si misura **contro la linea di chiusura**. Quindi una previsione che *è*
la linea di chiusura mostra CLV positivo **per costruzione**: scommette solo
prezzi migliori della chiusura, perché quella è la definizione di entrambe le
cose.

```
  MERCATO = chiusura de-viggata
        ↓  scommetti quando offerto > chiusura
        ↓
  CLV positivo garantito       ← NON è un edge. È una tautologia.
```

Questa strategia esiste già nel repository: si chiama `TakeValueVsClose`, ed è
etichettata `oracle_beats_close` nella validazione M4 — un **controllo positivo
chiaroveggente**, che vede il futuro apposta. Costruire l'ensemble sulla
chiusura la farebbe rientrare dalla finestra travestita da scoperta di M6.

La soluzione è separare due esperimenti che rispondono a due domande diverse:

| | mercato usato | conoscibile al momento della decisione? | scommesso? | risponde a |
|---|---|---|---|---|
| **INFORMATION** | chiusura | **no** | **mai** | il modello sa qualcosa che la chiusura non sa? |
| **DEPLOYABLE** | prematch | sì | sì | quel qualcosa si può giocare? |

Nel percorso deployable **nessun componente legge un prezzo di chiusura**. La
chiusura compare solo dopo, come metro del CLV — che è esattamente il suo ruolo
legittimo.

### Perché il prematch è un sostituto onesto

Non è una rinuncia grande quanto sembra. Su ENG_PL 2017-18:

| | Brier | LogLoss (per selezione) |
|---|---|---|
| Pinnacle PREMATCH | 0.18651 | 0.55397 |
| Pinnacle CLOSING | 0.18568 | 0.55150 |
| **spazio fra le due** | **0.00083** | 0.00246 |

Tutta l'informazione che il mercato acquisisce fra il prematch e la chiusura
vale 0.00083 di Brier. Il modello di M5 è 0.00979 **peggio** della chiusura:
un divario **dodici volte più grande** dell'intera finestra in cui il mercato
stesso impara qualcosa.

---

## Il pool è logaritmico

```
  p_k  ∝  p_modello_k ** w  ·  p_mercato_k ** (1 − w)
```

Per due esiti è esattamente la miscelazione in spazio logit; per tre è la sua
generalizzazione naturale. È la forma giusta perché combinare **quote** è
un'operazione moltiplicativa: un pool lineare di due previsioni sicure e
discordi produce una media bimodale in cui non crede nessuna delle due fonti,
il pool logaritmico produce qualcosa in mezzo.

**Un solo parametro, di proposito.** La domanda non è «quanto possiamo spremere
da queste due previsioni» ma «il modello contiene informazione». Un parametro la
risponde con quasi nessuna capacità di overfitting, e `w = 0` è un «no»
leggibile senza interpretazione.

### Il vincolo, e cosa nasconde

`w` è vincolato a `[0, 1]`: fuori non è una miscela, è estrapolazione, e nessuno
la giocherebbe. Ma il vincolo collassa due casi diversi nello stesso numero —
«il modello non aggiunge niente» e «il modello è attivamente fuorviante»
diventano entrambi `w* = 0`.

Per questo viene stimato e registrato anche l'ottimo **non vincolato** su
`[−1, 2]`. Non viene mai applicato: serve solo a distinguere i due casi.

---

## Il punto in cui M6 poteva introdurre una fuga

`w` è l'**unico parametro di tutto M6 stimato dagli esiti**. È quindi l'unica
nuova via per cui il futuro può raggiungere il passato, e arriva da una porta
che nessuno stava guardando: tutta la disciplina point-in-time del sistema
sorveglia le *previsioni*, non i *pesi*.

Tre difese, ridondanti di proposito:

1. **Il filtro sta dentro `fit_weight`, non nel chiamante.** La funzione prende
   un confine esplicito e scarta le righe dalla parte sbagliata. Un chiamante
   che passa una finestra larga e lascia tagliare al confine è l'uso previsto,
   non un errore.

2. **Il fitter registra il massimo `settled_at` che ha davvero consumato.**
   `v_weight_leakage` confronta quel valore con il confine dichiarato. Un audit
   che si limitasse a rileggere il confine non potrebbe fallire, e un audit che
   non può fallire non è un audit.

3. **Un test costruito per fallire se la difesa cede.** Periodo di training in
   cui il modello punta con sicurezza sull'esito *sbagliato*, periodo di test in
   cui punta su quello *giusto*. Gli ottimi dei due periodi stanno agli estremi
   opposti dell'intervallo: un fitter corretto risponde `w ≈ 0`, uno che sbircia
   risponde `w > 0.9`. Non serve niente di sottile per rilevare la fuga.

Il test di controllo che dimostra che il primo test *può* fallire è parte del
requisito: un test verde su una difesa che non è mai messa alla prova non
dimostra nulla.

---

## Gli arm passano dal motore esistente

Gli arm `MARKET` ed `ENSEMBLE` vengono scritti in `model_runs`/`predictions`
come qualunque altra previsione. Così l'ablation si gioca con **un solo motore**
di backtest e una sola implementazione di CLV, invece che con tre percorsi
paralleli che possono divergere.

Ha richiesto una modifica: `ModelEdge` ora filtra per `model_name`. Senza,
la finestra «fit più fresco» — corretta con un solo modello — sceglierebbe
l'arm scritto più di recente, confrontando silenziosamente gli arm fra loro
invece di scommetterne uno.

---

## Cosa M6 NON fa

Fuori scope per costruzione, non per mancanza di tempo:

* **Nessuna feature nuova.** Niente xG, formazioni, infortuni, riposo, viaggi,
  congestione, portieri, mismatch tattici. Prima si stabilisce se il modello che
  c'è aggiunge qualcosa; la caccia alle feature ha senso solo dopo.
* **Nessun modello nuovo.** Gli altri cinque di `MODELS` restano non validati.
* **Niente staking, Kelly o portfolio.** È M7.
* **Nessuna calibrazione applicata** oltre al peso del pool.

---

## Risultati

Vedi
[`../validation/incremental-information.md`](../validation/incremental-information.md).
