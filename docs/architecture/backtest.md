# Il backtest walk-forward (M4)

M4 costruisce il motore, non l'edge. Nessun modello: quello è M5.

---

## Il bias che questo motore elimina

Misurato sul motore precedente: tre partite alle 15:00, ciascuna al 50% del
bankroll «corrente», regolate in sequenza.

```
SBAGLIATO   bankroll 100  →  50 → 75 → 112.50
CORRETTO    ogni stake dimensionato su UN solo snapshot  →  50, 50, 50
                                                            poi vincolato
```

Non è un errore visibile nell'output: fa semplicemente sembrare migliore ogni
strategia. La coorte è quello snapshot reso esplicito.

**Verificato su dati veri.** Una coorte di 8 partite simultanee della Premier
League:

| | |
|---|---|
| `equity_open` | 930.30 |
| stake distinti | **[9.30]** — uno solo |
| coorti con stake diversi | **0** |

---

## Le tre grandezze da non confondere

```
settled_cash    denaro restituito da scommesse risolte
open_exposure   stake su scommesse non ancora risolte
equity          settled_cash + open_exposure   (stake a costo)
```

Kelly dimensiona sull'**equity**. Il vincolo è **available** = equity × cap −
esposizione già impegnata. Il capitale bloccato su un kickoff delle 12:30 non
è di nuovo disponibile alle 15:00, e una simulazione che se ne dimentica fa
girare una strategia che nessuno avrebbe potuto finanziare.

---

## Perché l'istante di decisione è il kickoff

Con una fonte senza timestamp, l'unica cosa nota di un prezzo `PREMATCH` è che
era disponibile **a un certo punto prima** del kickoff. Il kickoff è quindi
l'ultimo istante in cui quel prezzo è certamente ancora reale, e usarlo fa
l'affermazione più debole che i dati sostengano.

Un feed timestampato permetterebbe di anticipare la decisione e renderla
precisa. Anticiparla adesso sarebbe un'ipotesi travestita da calendario.

---

## Risultati

> Questi numeri sono di **una sola stagione**. La validazione completa su 10
> campionati-stagione è in `docs/validation/backtest-validation.md`, e mostra
> che lo yield di una singola stagione dà il verdetto sbagliato 7 volte su 30
> mentre il CLV non sbaglia mai. Non usare i numeri qui sotto come benchmark.

Premier League 2017-18, 306 partite, prezzi Pinnacle reali, stake piatto 1%,
esposizione max 25%.

| Strategia | Bet | Yield su giocato | Crescita | Max DD | CLV_ev | t | Verdetto |
|---|---:|---:|---:|---:|---:|---:|---|
| `take_home` | 306 | −1.72% | −4.88% | 22.3% | −0.026 | −6.45 | no edge |
| `take_favourite` | 306 | −4.59% | −13.32% | 19.0% | −0.016 | −5.15 | no edge |
| `oracle_beats_close` | 108 | **+40.0%** | **+54.2%** | 12.0% | **+0.104** | **+19.2** | edge |

Le naive **devono** perdere: se una strategia indiscriminata profittasse, il
motore sarebbe rotto.

`oracle_beats_close` è **deliberatamente chiaroveggente** — legge la chiusura,
che non è conoscibile quando la scommessa viene piazzata. Non è una strategia:
è la prova che il motore converte edge reale in denaro reale. Se fallisse, un
edge vero trovato più avanti sarebbe invisibile.

---

## Il risultato che giustifica la priorità del CLV

*(Confermato fuori campione: vedi il report di validazione. Su 30 run, «punta
sempre la casa» ha prodotto +287% di crescita in una stagione con un CLV di
−0.027 e t = −11.5.)*

Per l'oracolo, con 108 scommesse:

```
CLV t-stat        +19.23        inequivocabile
yield 95% CI      [−2.7%, +95.9%]   comprende ancora lo zero
```

Una strategia il cui CLV è schiacciante ha un intervallo di confidenza sullo
yield che **straddle lo zero**. È la dimostrazione numerica del motivo per cui
il CLV viene prima: dice «c'è edge» molto prima che il P&L possa.

Il bootstrap è percentile su rendimenti per-scommessa, senza assunzioni
distributive: i rendimenti del betting sono per lo più −1 con occasionali +4, e
un intervallo normale sottostimerebbe l'incertezza.

---

## Attriti, di prima classe

| Attrito | Cosa impedisce |
|---|---|
| Commissione su vincite nette | un edge sottile che l'exchange si mangia |
| Arrotondamento verso il basso | inventare capitale |
| Stake minimo | scommesse che nessun book accetta |
| Stake massimo | un edge che esiste solo a size irreali |
| Slippage sul prezzo | il prezzo visto non è quello ottenuto |

Un backtest senza attriti riporta una strategia che non esiste.

---

## Cinque stati, non due

Un handicap asiatico è impossibile da regolare con un booleano. `settle_bet()`
è la gemella deterministica di `asian_handicap_outcomes()`: **stessa algebra**,
applicata a un risultato invece che a una griglia. Scritta come riuso e non
come seconda implementazione, perché due copie della logica di settlement
divergono, e un backtest che regola diversamente da come ha prezzato non vale
nulla.

---

## Cosa manca

Lo staking è **piatto**: Kelly frazionario, shrinkage per errore di stima e
allocazione di portafoglio con correlazione intra-partita sono M7. La
dimensione piatta rende leggibile il comportamento del motore, e non pretende
di essere ottimale.
