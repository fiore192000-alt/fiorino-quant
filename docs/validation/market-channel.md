# Quanto vale, al massimo, il canale dei movimenti di quota

```
python scripts/measure_market_channel.py --json docs/validation/market-channel.json
```

10 dataset · **3.502 partite** · bootstrap appaiato a 2.000 estrazioni.
Dati grezzi in [`market-channel.json`](market-channel.json).

---

## Perché questa misura

Di tutta la lista di «nuove informazioni» — formazioni, infortuni, xG, riposo,
congestione, meteo — **una sola voce è già nel magazzino**: il percorso del
prezzo. Football-Data dà una quota prematch e una di chiusura, quindi il
movimento fra le due è misurabile oggi.

E quel movimento mette un **tetto a un'intera classe di lavoro futuro**.

Qualunque segnale derivato dall'osservare i prezzi muoversi — *steam*, cali,
*reverse line movement*, rilevamento di denaro informato — è un segnale su dove
il prezzo **sta andando**. La sua versione perfetta, quella che nessun sistema
reale può battere, è il prezzo di chiusura stesso: il punto d'arrivo di ogni
percorso, noto solo a posteriori.

Quindi il divario di previsione fra prematch e chiusura è il limite superiore
dell'intero canale. Un sistema con feed timestampato perfetto, modello di
microstruttura perfetto e costi di esecuzione nulli cattura quello, e nient'altro.

Questo non misura la tradabilità e non pretende di farlo. **È un tetto.**

---

## Il risultato

> La linea **si muove molto** e **impara pochissimo**.

| dataset | n | Brier prematch → chiusura | guadagno LogLoss | mosse > 1 punto |
|---|---|---|---|---|
| ENG_PL 2017-18 | 380 | 0.18651 → 0.18568 | −0.00410 [−0.01017, +0.00244] | 75% |
| ENG_PL 2018-19 | 380 | 0.17371 → 0.17341 | −0.00168 [−0.00834, +0.00512] | 79% |
| ENG_PL 2019-20 | 380 | 0.19162 → 0.19154 | −0.00004 [−0.00717, +0.00730] | 85% |
| ENG_PL 2020-21 | 380 | 0.19938 → 0.19748 | **−0.00917 [−0.01881, −0.00035]** | 85% |
| ESP_LL 2019-20 | 378 | 0.19605 → 0.19539 | −0.00401 [−0.01223, +0.00470] | 86% |
| ITA_SA 2019-20 | 380 | 0.18956 → 0.18858 | −0.00423 [−0.01267, +0.00406] | 85% |
| DEU_BL1 2024-25 | 306 | 0.19727 → 0.19684 | −0.00190 [−0.01071, +0.00655] | 83% |
| FRA_L1 2024-25 | 306 | 0.18875 → 0.18798 | −0.00305 [−0.01284, +0.00688] | 86% |
| NLD_ED 2024-25 | 306 | 0.18773 → 0.18542 | −0.00950 [−0.01978, +0.00082] | 87% |
| PRT_L1 2024-25 | 306 | 0.18409 → 0.18240 | −0.00856 [−0.01784, +0.00071] | 83% |

**La linea si muove**: spostamento mediano di **2,29 punti di probabilità**,
oltre 1 punto nell'**83%** delle partite. Non è un mercato fermo.

**La linea impara**: guadagno medio **−0.00099 di Brier**, **−0.00462 di
LogLoss**.

### Direzione certa, magnitudine minuscola

Questa è la lettura corretta, e le due metà vanno tenute insieme:

* Il segno è **negativo in 10 dataset su 10** — la chiusura è sempre migliore
  della prematch. Dieci su dieci nella stessa direzione non è caso
  (un test dei segni dà p ≈ 0.001). **L'effetto è reale.**
* Ma è **statisticamente distinguibile dallo zero in 1 dataset su 10**
  (2/10 su RPS). Su una singola stagione il guadagno sparisce nel rumore.

Un effetto reale può essere trascurabile, e questo lo è. Confonderlo con
«nessun effetto» sarebbe sbagliato; trattarlo come sfruttabile lo sarebbe di
più.

---

## Il tetto, messo accanto agli altri numeri

```
  canale movimenti di quota, TUTTO INTERO        0.00099 Brier   ← tetto
  quanto il modello M5 è peggio della chiusura   0.00979 Brier
                                                 ──────────────
                       il canale intero vale 1/10 del divario del modello
```

Detto altrimenti: se un sistema catturasse **l'intero** contenuto informativo
dei movimenti di quota — cosa che richiederebbe un feed timestampato, un
modello di microstruttura e zero costi di esecuzione — recupererebbe **un
decimo** di quanto il modello Dixon-Coles è indietro rispetto alla chiusura.

E l'83% delle partite ha un movimento superiore a un punto di probabilità. La
maggior parte di quel movimento non è informazione: è liquidità, rumore,
riequilibrio del libro.

---

## Cosa significa per un feed timestampato

Il magazzino oggi non ha un solo prezzo `TIMESTAMPED`: Football-Data dà due
punti per partita, e M2 lo registra onestamente invece di inventare istanti.

La conseguenza pratica è stata finora accettata come limite. Questa misura la
qualifica:

**Un feed timestampato non è un prerequisito che sblocca un canale ricco. È un
investimento il cui rendimento massimo è 0.00099 di Brier.**

Il che non lo rende inutile — serve comunque per anticipare l'istante di
decisione, per misurare il CLV con più precisione, e per verificare che un
prezzo `PREMATCH` fosse davvero disponibile. Ma non è lì che si trova l'edge
mancante, e adesso c'è un numero invece di un'intuizione.

---

## Limiti dichiarati

**La finestra misurata non è opening → closing.** La colonna Pinnacle
`PSH/PSD/PSA` di Football-Data non è documentata come apertura: è una quota
prematch di istante ignoto. La finestra reale potrebbe essere più stretta
dell'intera vita del mercato, il che rende questo tetto **conservativo per
difetto** — il canale completo dall'apertura vera potrebbe valere di più.

**Un solo book.** Pinnacle, il libro di riferimento. La dispersione fra book —
un canale diverso, quello del *line shopping* — non è misurata qui, ed è stata
misurata in M6 dove si è rivelata in gran parte definizionale.

**Un solo mercato.** 1X2.

**Nessuna scomposizione del movimento.** Il movimento è trattato come una
quantità sola. Distinguere il movimento informato da quello di liquidità è
esattamente ciò che richiederebbe il feed timestampato, ed è ciò di cui questa
misura fissa il rendimento massimo.
