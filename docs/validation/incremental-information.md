# M6 — il modello aggiunge informazione al mercato?

```
python scripts/validate_m6.py --json docs/validation/m6-results.json
```

10 dataset · ablation `MARKET` / `MODEL` / `MARKET+MODEL` · due esperimenti
(chiusura e prematch) · **2.396 partite valutate su 2.875** · bootstrap appaiato a 1.500
estrazioni. Risultati grezzi in [`m6-results.json`](m6-results.json).

---

## La risposta

> ## NO.
>
> `MARKET+MODEL` non batte `MARKET` in **nessuno** dei 10 dataset, in nessuno
> dei due esperimenti, su nessuna delle tre regole di scoring. **Tutti e 20 gli
> intervalli di confidenza contengono lo zero**, e 9 stime puntuali su 10 sono
> dalla parte sbagliata.

| dataset | w medio | w max | w non vincolato | `MARKET+MODEL` − `MARKET`, LogLoss | verdetto |
|---|---|---|---|---|---|
| ENG_PL 2017-18 | 0.0016 | 0.0197 | −0.0402 | +0.00017 [−0.00005, +0.00041] | 0 nel CI |
| ENG_PL 2018-19 | 0.0345 | 0.1576 | +0.0339 | +0.00084 [−0.00052, +0.00224] | 0 nel CI |
| ENG_PL 2019-20 | 0.2071 | 0.3814 | +0.2071 | −0.00007 [−0.00888, +0.00908] | 0 nel CI |
| ENG_PL 2020-21 | 0.0558 | 0.2524 | +0.0514 | +0.00162 [−0.00159, +0.00477] | 0 nel CI |
| ESP_LL 2019-20 | 0.1671 | 0.2827 | +0.1671 | +0.00227 [−0.00423, +0.00899] | 0 nel CI |
| ITA_SA 2019-20 | 0.1720 | 0.3368 | +0.1720 | +0.00166 [−0.00537, +0.00893] | 0 nel CI |
| DEU_BL1 2024-25 | **4.8e−06** | 4.8e−06 | **−0.5087** | +1.5e−07 [≈0] | il peso è a zero |
| FRA_L1 2024-25 | 0.0187 | 0.1100 | −0.0478 | +0.00090 [−0.00026, +0.00216] | 0 nel CI |
| NLD_ED 2024-25 | **4.8e−06** | 4.8e−06 | **−0.3004** | +5.1e−08 [≈0] | il peso è a zero |
| PRT_L1 2024-25 | 0.0012 | 0.0279 | −0.3617 | +0.00018 [−0.00014, +0.00056] | 0 nel CI |

`4.8e−06` è il fondo della ricerca a sezione aurea con tolleranza `1e-5`, non
uno zero esatto: in quei due dataset il peso ottimale è a zero e il pool
coincide con il mercato a meno di `1e-7`.

Il quadro è lo stesso sull'esperimento *information* (mercato = chiusura):
differenza media +0.00073, `MARKET+MODEL` batte `MARKET` in **0/10**. Sulle 20
stime puntuali dei due esperimenti, **18 sono peggiori del mercato e 2 migliori**
— e le due migliori sono dentro il rumore (−0.00007 e −0.00040, con CI larghi
cento volte tanto).

Su Brier `MARKET+MODEL` è peggiore in **10 dataset su 10**, anche se in due di
essi per meno di `1e-7`. **Mai migliore.** Su RPS, idem.

---

## Il pezzo più istruttivo: un peso non nullo che non serve a niente

In tre dataset il peso stimato **non** è vicino a zero:

| | w medio | w max | guadagno out-of-sample |
|---|---|---|---|
| ENG_PL 2019-20 | 0.2071 | 0.3814 | −0.00007, CI [−0.00888, +0.00908] — CI 130 volte la stima |
| ITA_SA 2019-20 | 0.1720 | 0.3368 | **+0.00166** (peggio) |
| ESP_LL 2019-20 | 0.1671 | 0.2827 | **+0.00227** (peggio) |

L'ottimizzatore ha trovato, sul periodo di training, che pesare il modello al
17–21% riduceva la log-loss. Fuori campione quel peso **non ha prodotto alcun
miglioramento**, e in due casi su tre ha peggiorato le cose.

Questo è overfitting di **un solo parametro**, misurato. Non un ensemble con
duecento feature: un numero, vincolato a `[0, 1]`, stimato su duecento partite.
Se un parametro basta a produrre un guadagno in-sample che evapora fuori
campione, non c'è ragione di credere che aggiungere feature avrebbe prodotto
qualcosa di diverso — avrebbe prodotto lo stesso, meno visibile.

Il guadagno in-sample era **garantito non negativo**: `w = 0` è sempre
ammissibile, quindi il pool non può perdere sul training. È esattamente per
questo che un miglioramento in-sample non dimostra nulla, ed è per questo che
`ensemble_weights` registra `market_logloss` accanto a `train_logloss`: per
rendere illeggibile l'errore di scambiarli.

---

## Il modello è anti-informativo in metà dei dataset

Il peso vincolato a `[0, 1]` collassa «non aggiunge niente» e «è attivamente
fuorviante» sullo stesso `0`. L'ottimo **non vincolato** li distingue, ed è
**negativo in 5 dataset su 10**:

```
  DEU_BL1 2024-25   -0.5087
  PRT_L1  2024-25   -0.3617
  NLD_ED  2024-25   -0.3004
  FRA_L1  2024-25   -0.0478
  ENG_PL  2017-18   -0.0402
```

Media su 10 dataset: **−0.0627**. Nei quattro campionati 2024-25 il valore
ottimale sarebbe stato *sottrarre* il modello dal mercato. Un modello con peso
ottimale negativo non è neutro: la sua opinione, invertita, sarebbe stata
informativa — cioè le sue deviazioni dal mercato puntano sistematicamente nella
direzione sbagliata.

---

## Il controllo che sembrava aver trovato qualcosa

L'arm `MARKET` non contiene alcun modello: prende la quota de-viggata prematch
di Pinnacle e scommette un prezzo di un altro book quando lo supera del 2%. È
puro *line shopping*. E all'inizio sembra il primo arm del progetto con CLV
positivo:

```
  MARKET @2%     CLV medio +0.0234   positivo in 7/8 dataset
```

**È una tautologia, e va detto invece che festeggiato.** Il CLV è
`p_chiusura × prezzo − 1`; l'arm scommette quando `p_prematch × prezzo − 1 >
0.02`. Poiché la prematch di Pinnacle e la sua chiusura sono quasi la stessa
previsione, il CLV positivo è **la condizione d'ingresso riscritta**.

Decomposto esattamente su due dataset:

| | edge alla scommessa (per costruzione) | CLV misurato | deriva reale prematch→chiusura |
|---|---|---|---|
| ENG_PL 2019-20 | **+0.0463** | +0.0445 | **−0.0017** |
| PRT_L1 2024-25 | **+0.0586** | −0.0198 | **−0.0783** |

L'unica componente non definizionale è la deriva, ed è **negativa in entrambi**.
L'arm `MARKET` non ha edge: ha una condizione d'ingresso che si auto-certifica.

Questo è lo stesso errore contro cui M6 è stato progettato — un arm costruito
sulla chiusura mostra CLV positivo per costruzione — che si ripresenta in forma
attenuata perché la prematch di Pinnacle *quasi* è la sua chiusura. Il disegno
a due esperimenti lo ha reso visibile invece di lasciarlo passare per una
scoperta.

---

## Scommesse: l'ablation completa

| arm | soglia | CLV medio | CLV > 0 | yield medio | yield > 0 |
|---|---|---|---|---|---|
| `MARKET` | 2% | +0.0234 † | 7/8 | −0.0320 | 4/8 |
| `MODEL` | 2% | −0.0425 | **0/10** | −0.0675 | 2/10 |
| `MARKET+MODEL` | 2% | −0.0022 | 4/8 | −0.1060 | 2/8 |
| `MARKET` | 5% | — campione sotto le 30 scommesse in ogni dataset — |
| `MODEL` | 5% | −0.0439 | **0/10** | −0.0726 | 2/10 |
| `MARKET+MODEL` | 5% | −0.0142 | 1/4 | −0.0620 | 2/4 |

† definizionale, vedi sopra.

Il fatto che l'arm `MARKET` piazzi **7–25 scommesse a stagione** alla soglia del
5%, contro le 676–1.465 del modello, non è un dettaglio tecnico: è la stessa
misura vista da un'altra angolazione. Una previsione calibrata quasi non trova
mai «value». Una previsione miscalibrata ne trova ovunque.

---

## I gate

| | gate | esito |
|---|---|---|
| 1 | point-in-time, peso incluso | **0 violazioni** su 10 dataset |
| 2 | calibrazione (Brier, LogLoss, RPS) | `MODEL` perde 10/10 su tutte e tre |
| 3 | informazione incrementale | **fallito: 0/10, tutti i CI contengono 0** |
| 4 | CLV > 0 out-of-sample | non raggiunto (l'unico positivo è definizionale) |
| 5 | robustezza | 7 paesi, 2 epoche, bootstrap appaiato |
| 6 | yield / drawdown / staking | non valutato: il gate 3 non è passato |

Nessun parametro è stato stimato sul periodo di test. `v_weight_leakage` è
vuota su tutti e 10 i dataset, e l'audit può fallire: il fitter registra il
massimo `settled_at` che ha davvero consumato, e i test unitari costruiscono il
caso in cui un fitter che sbircia risponderebbe `w > 0.9` invece di `w ≈ 0`.

---

## Limiti dichiarati

**Copertura del campione.** Vengono valutate 2.396 partite su 2.875 regolate
(83%): le prime settimane di ogni stagione non hanno ancora un peso stimato.
Non è una selezione sugli esiti — è un prefisso temporale, uguale per tutti e
tre gli arm, e gli arm sono verificati come valutati sullo stesso campione (è un
gate).

**Un solo modello, un solo mercato.** Dixon-Coles con emivita 180 giorni,
mercato 1X2, book di riferimento Pinnacle. Gli altri cinque modelli di `MODELS`
restano non validati.

**Il peso è uno solo, e globale.** Non varia per lega, per periodo della
stagione, né per quota. Un peso condizionale potrebbe trovare qualcosa dove
quello globale non trova niente — ma sarebbe più parametri sugli stessi dati,
e questo esperimento mostra che già uno solo non regge fuori campione.

**Il campione dell'arm `MARKET` è sottile** alla soglia del 5%: 7–25 scommesse
per stagione. La riga a 2% esiste proprio per quello, e resta comunque troppo
sottile per un t-stat interpretabile.

---

## Cosa cambia adesso

L'ordine che questo risultato suggerisce non è «più modelli», ed è quello che
l'esperimento è stato costruito per poter dire:

1. **PenaltyBlog non va buttato**, ma non va nemmeno tenuto come sorgente di
   previsione. Non aggiunge informazione al mercato, e in metà dei campionati
   ne toglie. Il suo valore residuo è come *generatore di feature* — le lambda,
   le forze di attacco e difesa — dentro un modello che parta dal mercato,
   non accanto ad esso.

2. **La baseline è il mercato**, non un modello. Qualunque cosa venga costruita
   dopo va valutata come `market + X` contro `market`, con il CI, con la stessa
   ablation e con lo stesso gate: un CI che contiene lo zero non è evidenza.

3. **Il metro esiste adesso.** `MARKET` alla soglia del 2% definisce il numero
   da battere, e la decomposizione del suo CLV definisce come non farsi ingannare
   dal proprio criterio d'ingresso.

4. La caccia alle feature — xG, formazioni, infortuni, riposo, congestione —
   è la fase successiva, e ha senso ora che c'è un modo di dire *no*.

Il risultato scientifico, in una riga: **su questi dati, un modello Dixon-Coles
correttamente addestrato non contiene informazione che il mercato non abbia
già.** Non è nascosto dietro complessità aggiuntiva, ed è riproducibile.
