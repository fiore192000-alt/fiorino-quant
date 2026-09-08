# Fiorino Quant — Architettura

Sistema quantitativo per l'individuazione di value bet nel calcio europeo.

**penaltyblog è una dipendenza, non il core.** Viene raggiunto esclusivamente
attraverso `fiorino.models.adapters` e `fiorino.pricing`. Il motore statistico
può essere sostituito senza toccare ingestione, CLV, backtest o staking.

---

## 1. Principio guida

Il sistema è costruito attorno a una sola invariante, da cui dipende tutto il
resto:

> **R1 — Point-in-time.** Ogni fatto che il sistema può *apprendere nel tempo*
> porta con sé l'istante in cui è diventato conoscibile. Nessuna query eseguita
> durante un backtest può leggere una riga il cui istante di conoscibilità è
> successivo all'orologio della simulazione.

| Fatto | Colonna |
|---|---|
| Quote | `captured_at` |
| Risultati | `settled_at` |
| Feature | `as_of` |
| Modelli | `trained_through` (meno `embargo_seconds`) |

L'enforcement non è per convenzione ma per costruzione: `fiorino.data.access.PointInTimeView`
è l'unico lettore autorizzato per il codice di strategia e backtest, e ogni suo
metodo è limitato da `as_of`. Un test asserisce che nessun modulo sotto
`fiorino/strategy` o `fiorino/backtest` importi i repository grezzi.

Le altre quattro regole dello schema (R2 forma unica delle quote, R3 linee in
prospettiva casa, R4 line non nullable, R5 ledger append-only) sono documentate
in testa a `fiorino/data/db/schema.sql`.

---

## 2. Struttura delle cartelle

```
fiorino/
├── config/            settings tipizzati, registry di leghe/book/mercati
├── core/              types, ids deterministici, money in Decimal, vocabolario mercati
├── data/
│   ├── db/            schema.sql · views.sql · connection · migrations
│   ├── identity/      risoluzione identità squadra (alias → team_id stabile)
│   ├── ingest/
│   │   ├── odds/      feed quote → odds_snapshots
│   │   ├── fixtures/  calendari e risultati → fixtures, results
│   │   └── features/  feature point-in-time → feature_values
│   └── access/        PointInTimeView (R1) · repositories (solo ingest/report)
├── odds/              devig · closing (materializzazione) · best_price
├── clv/               compute · report            ← segnale primario
├── models/
│   ├── adapters/      penaltyblog dietro il protocollo GoalModel
│   └── blend/         market blending · calibrazione
├── pricing/           grid → righe (market_type, line, selection) con push
├── strategy/          generazione candidati (NON dimensiona le puntate)
├── staking/           kelly (con push) · shrinkage per errore di stima
├── portfolio/         allocator di coorte · correlazione intra-fixture
├── backtest/          engine · clock · ledger · settlement · frictions · metrics
├── reporting/         tearsheet · dashboard CLV
└── cli/               bootstrap · ingest · devig · fit · price · backtest · clv
```

**Direzione delle dipendenze:** `core ← data ← {odds, models, pricing} ← {strategy,
staking, portfolio} ← backtest ← reporting`. Nessun ciclo. `core` non importa nulla
di `fiorino`.

---

## 3. I sette sottosistemi

### 3.1 Odds ingestion

Una sola forma per ogni mercato di ogni book: `(market_type, line, selection)`.
Niente tabelle per-mercato, niente colonne larghe. È questo che rende banali il
best-price cross-book e i join per il CLV.

Due normalizzazioni non negoziabili:

- **R3 — linee in prospettiva casa.** «Away +0.5» si memorizza come
  `(ASIAN_HANDICAP, line = -0.5, selection = 'AWAY')`. Senza questa regola lo
  stesso prezzo compare sotto due chiavi e il confronto best-price si rompe.
- **R4 — `line NOT NULL`,** 0.0 per i mercati senza linea. I NULL contano come
  distinti nei vincoli UNIQUE e permetterebbero snapshot 1X2 duplicati.

Il polling è più fitto vicino al calcio d'inizio: l'ultima ora contiene la
maggior parte dell'informazione. Ogni adapter è idempotente e la copertura è
verificata da `v_data_coverage` prima di fidarsi di qualunque backtest — un
periodo con snapshot radi produce un backtest che ha visto solo le partite facili.

### 3.2 Closing line database

`odds_closing` è materializzata da `odds_snapshots`: l'ultimo snapshot
strettamente precedente il kickoff per ogni chiave. Porta un gate di qualità,
`is_trusted`: un prezzo «di chiusura» catturato sei ore prima non è una chiusura,
e il modulo CLV rifiuta di assegnare un punteggio quando la soglia di obsolescenza
è superata.

`fair_probabilities` conserva le probabilità depurate dall'overround, calcolate
**per mercato completo** e mai per singola selezione. Il metodo (Shin di default)
è memorizzato per riga, così de-vig alternativi possono coesistere e essere
confrontati senza re-ingestione.

### 3.3 CLV tracking — priorità assoluta

Misurato contro la chiusura **del book di riferimento** (sharp), de-vigata, per
la selezione identica — mai contro il book con cui si è scommesso.

```
clv_price = price_taken / closing_price - 1
clv_ev    = closing_fair_prob * price_taken - 1      ← numero di riferimento
clv_log   = ln(closing_fair_prob * price_taken)      ← additivo tra scommesse
```

`clv_ev` è il ROI atteso se la probabilità equa di chiusura è la verità.
`v_clv_summary` espone anche il **t-stat del CLV** contro zero: con qualche
centinaio di scommesse un |t| > 2 è segnale reale, mentre lo yield ne richiede
migliaia per dire altrettanto.

> Perché è la priorità: il CLV converge sulla verità in centinaia di scommesse,
> il P&L in migliaia. Una strategia con CLV negativo e P&L positivo è fortunata,
> e saperlo in anticipo vale più del P&L stesso.

Complessità nota: se il book di riferimento non ha mai offerto quella linea
esatta, il confronto va interpolato. La v1 richiede corrispondenza esatta e
marca `line_matched = FALSE` altrove — quelle scommesse sono escluse dalle
statistiche invece di essere confrontate contro una linea diversa.

### 3.4 Walk-forward backtest

Il bias da eliminare, misurato sul motore attuale di penaltyblog: tre partite
delle 15:00, puntando il 50% del bankroll su ciascuna, producono stake
`[50.0, 75.0, 112.5]` perché ognuna si regola prima che la successiva sia
dimensionata. Nella realtà iniziano tutte insieme con un bankroll di 100.

**La coorte** è la correzione. Una coorte è l'insieme delle scommesse
dimensionate contro un unico snapshot di equity. Il motore mantiene:

```
equity     = cassa liquidata + stake aperti a costo
esposizione_aperta = stake non ancora risolti
disponibile = equity * max_exposure_frac - esposizione_aperta
```

Kelly dimensiona come frazione di `equity`; `disponibile` è il vincolo effettivo.
Le partite con orari diversi nello stesso giorno formano coorti diverse, ma il
capitale impegnato alle 12:30 resta bloccato quando si dimensiona la coorte
delle 15:00 — che è il comportamento corretto.

Il ciclo:

```
per ogni istante di decisione (clock):
    equity, esposizione ← ledger.stato(as_of)
    candidati ← strategy.generate(PointInTimeView(as_of))
    stake     ← allocator.allocate(candidati, equity, disponibile, vincoli)
    ledger.place(stake)
    settle(tutto ciò il cui settlement_utc ≤ prossimo istante di decisione)
```

Il refit dei modelli rispetta `trained_through - embargo_seconds`: nessuna riga
di training può avere `settled_at` oltre quel confine. L'embargo serve quando le
feature sono rolling e sconfinerebbero oltre il taglio.

Le frizioni sono di prima classe: commissioni, stake minimo/massimo,
arrotondamento, slippage. Le metriche sono yield **sul giocato** (non sul
bankroll iniziale), drawdown massimo, Sharpe, CI bootstrap — e il CLV in testa.

### 3.5 Portfolio management

Le scommesse sulla **stessa partita non sono indipendenti**: sono funzioni dello
stesso risultato. Over 2.5 e BTTS Sì sulla stessa partita sono fortemente
correlate; `multiple_kelly_criterion` di penaltyblog le tratterebbe come
mutuamente esclusive, che è sbagliato in direzione pericolosa.

`portfolio/correlation.py` valuta la crescita congiunta **esattamente** sulla
griglia dei punteggi: per un vettore di stake `f` sulle scommesse di una partita,
il moltiplicatore di ricchezza nello scenario (h, a) è

```
W(h,a) = 1 - Σf_i + Σ f_i · payoff_i(h,a)
E[log W] = Σ_{h,a} p(h,a) · log W(h,a)
```

concavo in `f`, quindi risolvibile con SLSQP. Tra partite diverse l'indipendenza
è un'assunzione ragionevole e la crescita attesa è additiva, così l'allocator
risolve l'intera coorte congiuntamente sotto un vincolo globale di esposizione.

### 3.6 Kelly frazionario

Per un mercato win/push/lose (handicap asiatici e totali su linea intera) la
frazione ottimale ha forma chiusa:

```
f* = (p_win · b - p_lose) / (b · (p_win + p_lose))          b = price - 1
```

che si riduce al Kelly standard quando `p_push = 0`. *(Verificata numericamente
contro l'ottimizzazione diretta di E[log W].)* Coincide inoltre con il Kelly
binario applicato alla probabilità condizionata al no-push — quindi lo **stake**
resta corretto anche rinormalizzando.

**La trappola non è lo stake, è l'EV.** Con push:

```
EV = p_win · b - p_lose            (corretto: il push restituisce la puntata)
EV = p_win · b - (1 - p_win)       (formula binaria: sottostima di esattamente p_push)
```

Esempio reale: `p_win = 0.42, p_push = 0.08, p_lose = 0.50`, quota 2.60.
L'EV corretto è **+17.2%**; la formula binaria dà +9.2%. Con una soglia di edge
al 10% la scommessa viene **rifiutata**. Ecco perché `predictions` porta
`prob_win`/`prob_push`/`prob_lose` e non una probabilità sola.

Le linee a quarto (half-win / half-lose, cinque esiti) non hanno forma chiusa e
richiedono la soluzione numerica: nell'esempio testato, `f* = 0.0906` contro
`0.0714` della formula a tre esiti.

Prima di applicare qualsiasi frazione, `staking/shrinkage.py` penalizza l'edge
con il proprio errore di stima: `edge_used = max(0, edge - k · σ_edge)`, con
`σ_edge` da posterior bayesiano o bootstrap. Kelly su un edge sovrastimato è il
modo in cui i bankroll muoiono.

### 3.7 Multi-market pricing

Una `FootballProbabilityGrid` per partita, proiettata su tutti i mercati. Poiché
tutti i prezzi discendono dalla stessa griglia, sono coerenti per costruzione:
non è possibile che il modello prezzi 1X2 e Over/Under in modo mutuamente
contraddittorio.

`pricing/markets.py` emette righe che si uniscono direttamente a
`odds_snapshots` su `(market_type, line, selection)`, senza livello di
traduzione. Le colonne sono `prob_win`, `prob_push`, `prob_lose`.

Attenzione a una incoerenza ereditata da penaltyblog: `model.predict(max_goals=15)`
restituisce una griglia 15×15 (gol 0–14), mentre `create_dixon_coles_grid(max_goals=15)`
ne restituisce una 16×16 (gol 0–15). `pricing/grid.py` normalizza la convenzione
in un punto solo.

---

## 4. Schema DuckDB

DDL completo in `fiorino/data/db/schema.sql`; viste e macro point-in-time in
`fiorino/data/db/views.sql`. Entrambi verificati con esecuzione su DuckDB 1.5.

### Tabelle

| Gruppo | Tabelle |
|---|---|
| Riferimento | `competitions`, `teams`, `team_aliases`, `bookmakers`, `market_selections` |
| Partite | `fixtures`, `results` |
| **Quote** | `odds_snapshots`, `odds_closing`, `fair_probabilities` |
| Feature | `feature_values` |
| Modelli | `model_runs`, `predictions` |
| Esecuzione | `strategies`, `runs`, `cohorts` |
| **Ledger** | `bets`, `bet_settlements`, `clv`, `equity_curve` |

### Viste e macro

| Nome | Ruolo |
|---|---|
| `v_reference_closing` | chiusura del book sharp, de-vigata — base di ogni CLV |
| `v_bet_performance` | una riga per scommessa: contesto decisionale + settlement + CLV |
| `v_clv_summary` | rollup CLV con t-stat e beat-close rate |
| `v_line_history` | apertura, chiusura, drift, numero di snapshot per mercato |
| `v_data_coverage` | salute dell'ingestione — da leggere prima di ogni backtest |
| `odds_as_of(at_ts)` | **macro PIT** — prezzo più recente conoscibile |
| `best_price_as_of(at_ts)` | **macro PIT** — miglior prezzo e book che lo offre |
| `bettable_fixtures_as_of(at_ts)` | **macro PIT** — partite legittimamente giocabili |
| `results_as_of(at_ts)` | **macro PIT** — le sole righe su cui un modello può allenarsi |
| `features_as_of(at_ts)` | **macro PIT** — ultimo valore feature conoscibile |

Le macro sono l'unico modo sancito per leggere le quote in un backtest. Una query
che tocca `odds_snapshots` direttamente dentro il codice di strategia è un bug:
vede il futuro.

### Note di design

- **ID deterministici.** `fixture_id` è un hash di
  `(competition_id, season, utc_date, home_team_id, away_team_id)`: re-ingerire
  la stessa partita da qualunque fonte è idempotente.
- **`market_key`** è una colonna generata che raggruppa le selezioni di un
  mercato completo — l'unità su cui si rimuove l'overround.
- **`settle_t` ha cinque stati** (`WIN`, `HALF_WIN`, `PUSH`, `HALF_LOSE`, `LOSE`),
  non due. Gli handicap asiatici sono impossibili da regolare correttamente con
  un booleano.
- **Denaro in `DECIMAL(18,6)`**, quote e probabilità in `DOUBLE`. I float non
  toccano mai uno stake o un P&L.
- **`bookmakers.is_reference`** definisce il benchmark del CLV. Cambiarlo
  invalida ogni numero storico di CLV: va trattato come una costante.

---

## 5. Roadmap implementativa

La catena di dipendenze è vincolante: il CLV è la priorità numero uno ma non può
esistere prima delle quote, che non possono esistere prima dell'identità squadra.
Le fasi M1→M4 vanno quindi in ordine.

### M1 — Data layer *(priorità)*
Bootstrap DuckDB dallo schema, `core/` (ids, money, vocabolario mercati),
risolutore di identità squadra, ingestione fixture e risultati, backfill
storico. `PointInTimeView` con il test che vieta l'accesso grezzo.

**Fatto quando:** 10 stagioni × 8 leghe caricate, zero squadre non risolte tra
le fonti, `v_data_coverage` verde.

### M2 — Odds ingestion e closing line *(priorità)*
Adapter per il book di riferimento sharp più almeno un book soft. Poller con
cadenza crescente verso il kickoff. Materializzazione di `odds_closing` con gate
di obsolescenza. De-vig Shin su mercato completo → `fair_probabilities`.

**Fatto quando:** per ogni partita storica esiste una chiusura di riferimento
de-vigata; `v_line_history` mostra una storia reale, non due punti.

### M3 — CLV tracking *(priorità massima)*
`clv/compute.py`, `clv/report.py`, dashboard. Gestione di `line_matched`.

**Fatto quando:** si può calcolare il CLV di qualunque scommessa storica e il
t-stat aggregato per strategia. Validabile **prima di avere un modello**,
replaying scommesse sintetiche a prezzi noti.

### M4 — Backtest walk-forward *(priorità)*
`clock`, `ledger`, `cohorts`, `settlement` a cinque stati, `frictions`,
`metrics`. Nessuna strategia reale ancora: si valida su partite sintetiche a
risposta nota.

**Fatto quando:** il caso delle tre partite simultanee produce stake
`[50, 50, 50]` da un bankroll di 100, non `[50, 75, 112.5]`; e un test dimostra
che una strategia che legge il futuro viene bloccata dal PIT.

### M5 — Adapter modelli e pricing multi-mercato
`models/adapters/penaltyblog.py` con prior di lega per le neopromosse;
`pricing/grid.py` e `pricing/markets.py` con `prob_push`.

**Fatto quando:** data una partita, si produce un listino completo che si unisce
alle quote senza traduzione.

### M6 — Calibrazione e market blending
Calibrazione out-of-fold, blending in logit space con `w` stimato, valutazione
RPS/Brier **contro la closing line** come baseline.

**Fatto quando:** esiste una tabella modello × lega di RPS calibrato contro la
chiusura. Se non si batte la chiusura, non c'è edge — e va saputo qui, non dopo.

### M7 — Staking e portfolio
Kelly con push (forma chiusa a tre esiti, numerico a cinque), shrinkage per
errore di stima, allocator di coorte con correlazione intra-fixture.

**Fatto quando:** Monte Carlo a 10.000 percorsi con probabilità di rovina sotto
la soglia configurata.

### M8 — Strategie e reporting
Prima strategia reale end-to-end, tearsheet, confronto tra run.

### M9 — Paper trading
Stesso codice del backtest in modalità `PAPER`: quote live, scommesse registrate,
nessun denaro. È l'unico test onesto della latenza e della disponibilità dei prezzi.

### M10 — Produzione
Scheduler, alerting, monitoraggio del drift di CLV, versionamento modelli.

---

## 6. Cosa questa architettura non risolve

Onestà preventiva, perché ognuno di questi punti costa mesi se scoperto tardi:

- **Nessun modello di soli gol batte la chiusura di un book sharp.** L'edge
  realistico sta nei mercati meno efficienti e nella velocità, non nella
  raffinatezza statistica sull'1X2 di Premier League. Il blending di M6 esiste
  per ammetterlo, non per aggirarlo.
- **La limitazione degli account è un rischio operativo, non statistico.** Un
  book soft chiude i conti vincenti. Nessuna architettura lo previene.
- **CLV positivo non è profitto** se il prezzo non è disponibile alla dimensione
  che serve. `available_size` è in schema proprio per questo, ma solo il paper
  trading (M9) dice la verità.
- **Il backtest resta ottimista** anche corretto: assume di ottenere il prezzo
  visto nello snapshot. `frictions.py` modella lo slippage, ma è una stima.
