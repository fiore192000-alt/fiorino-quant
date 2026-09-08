# Validation Report — motore M4

Verifica del motore di backtest sui 10 campionati-stagione della validazione
M1–M3. **30 run** (3 strategie × 10 dataset).

**Riproducibile:** `python scripts/validate_backtest.py --json out.json`

---

## Parte 1 — Invarianti strutturali

Proprietà che devono valere su **ogni** run, indipendentemente da come è andata
la strategia. Una sola violazione è un bug, non sfortuna.

| # | Invariante | Esito |
|---|---|---|
| 1 | ogni scommessa di una coorte dimensionata sullo stesso snapshot di equity | ✅ |
| 2 | nessuna coorte ha puntato più del disponibile | ✅ |
| 3 | l'equity non è mai andata negativa | ✅ |
| 4 | ogni scommessa piazzata è stata regolata | ✅ |
| 5 | i conti tornano: equity finale = iniziale + Σ pnl | ✅ |
| 6 | nessuna scommessa porta un timestamp inventato | ✅ |

**0 violazioni su 30 run.** Coorte più grande osservata: **40 scommesse
simultanee** (Premier League, giornata di chiusura).

---

## Parte 2 — Comportamento, e il risultato che conta

Tre strategie, di cui due che **devono** perdere e una **deliberatamente
chiaroveggente** che legge la chiusura e quindi ha edge per costruzione.

### Il verdetto: CLV 30/30, yield 23/30

| Metrica | Verdetti corretti |
|---|---|
| **CLV_ev** | **30 / 30** |
| yield sul giocato | 23 / 30 |

Sette volte su trenta lo yield di una stagione ha dato la risposta sbagliata.
Il CLV non ha mai sbagliato.

### I falsi positivi: sei strategie senza edge che hanno guadagnato

| Dataset | Strategia | Yield | Crescita | CLV_ev | t |
|---|---|---:|---:|---:|---:|
| **ENG_PL 2019-20** | take_home | **+11.91%** | **+287.1%** | −0.0272 | −11.5 |
| ESP_LL 2019-20 | take_home | +1.41% | +41.9% | −0.0262 | −11.2 |
| ENG_PL 2018-19 | take_home | +2.79% | +20.8% | −0.0406 | −14.5 |
| ITA_SA 2019-20 | take_favourite | +1.34% | +5.3% | −0.0394 | −10.2 |
| ENG_PL 2017-18 | take_home | +0.70% | +4.9% | −0.0299 | −13.5 |
| PRT_L1 2024-25 | take_home | +0.22% | +2.5% | −0.0722 | −21.9 |

> **«Punta sempre la squadra di casa» ha prodotto +287% di crescita e +11.91%
> di yield in una stagione di Premier League** — con un CLV di −0.0272 e un
> t-stat di −11.5. Non ha edge. Non può averne. Ha semplicemente avuto una
> stagione fortunata.

Questo è il numero da tenere in mente ogni volta che un progetto di betting
esibisce un rendimento stagionale come prova di edge. Un rendimento di quella
grandezza è pienamente ottenibile da una strategia che **sappiamo** essere in
perdita attesa. Lo yield di una stagione non distingue l'edge dalla fortuna;
il CLV sì, e lo fa nello stesso campione.

### Il falso negativo: edge reale, stagione in perdita

| Dataset | Strategia | Yield | CLV_ev | t |
|---|---|---:|---:|---:|
| DEU_BL1 2024-25 | oracle_beats_close | **−1.33%** | **+0.1010** | **+32.7** |

L'oracolo conosce la chiusura: il suo edge è massiccio e certo. In Bundesliga
2024-25 ha comunque **perso denaro**. Con t = +32.7 sul CLV, l'edge era
inequivocabile e il P&L lo ha smentito.

Chi avesse giudicato quella strategia dal solo rendimento l'avrebbe scartata.

---

## Sintesi per strategia

| Strategia | Yield medio | Positivo in | CLV medio | Positivo in |
|---|---:|---:|---:|---:|
| `take_home` | −0.0090 | **5/10** | −0.0387 | 0/10 |
| `take_favourite` | −0.0195 | 1/10 | −0.0418 | 0/10 |
| `oracle_beats_close` | +0.0991 | 9/10 | **+0.1107** | **10/10** |

L'intervallo del CLV dell'oracolo è strettissimo — [+0.0967, +0.1203] su dieci
campionati diversi — mentre il suo yield spazia da −1.3% a +31.2%. La stessa
quantità di edge, misurata due volte: una misura è stabile, l'altra no.

---

## Che cosa questo dice del progetto

1. **Il motore è corretto.** 30 run, 6 invarianti, zero violazioni.
2. **Il motore riconosce l'edge quando c'è:** CLV positivo 10/10 sull'oracolo.
3. **Il motore non inventa edge dove non c'è:** CLV negativo 10/10 su entrambe
   le strategie naive, nonostante 6 di quelle run siano state in profitto.
4. **La priorità data al CLV è ora un fatto misurato**, non una preferenza
   metodologica.

---

## Limiti dichiarati

- Lo staking è **piatto** all'1% dell'equity. Kelly frazionario, shrinkage e
  portafoglio sono M7. Con Kelly, la varianza del rendimento — e quindi il
  numero di falsi positivi — sarebbe **maggiore**, non minore.
- L'oracolo non è una strategia: legge la chiusura, che al momento della
  puntata non è conoscibile. Serve solo a provare che il motore converte edge
  reale in denaro reale.
- Una sola stagione per lega in 6 casi su 10. I falsi positivi sono contati su
  30 run, non su 30 anni.
