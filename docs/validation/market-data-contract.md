# Market Data Contract

Schema definitivo dei tre oggetti su cui poggia tutto il resto, con esempi
reali estratti da archivi Football-Data.

---

## Il vincolo che governa i tre schemi

> **Non inventare timestamp per osservazioni che non ne hanno.**

Imposto dallo schema, non dalla disciplina:

```sql
CHECK ((capture_precision = 'TIMESTAMPED') = (captured_at IS NOT NULL))
```

Verificato end-to-end: **0 righe con un orario** su 37.482 osservazioni reali.

---

## 1. `OddsObservation`

Un prezzo osservato. La tabella centrale: tutto il resto ne è derivato.

```sql
observation_id    VARCHAR PRIMARY KEY
match_id          VARCHAR NOT NULL   -> matches
bookmaker_id      VARCHAR NOT NULL   -> bookmakers
market_type       VARCHAR NOT NULL   -- ONE_X_TWO | ASIAN_HANDICAP | TOTALS | ...
line              DOUBLE  NOT NULL DEFAULT 0.0   -- R3/R4
selection         VARCHAR NOT NULL
price_decimal     DOUBLE  NOT NULL   -- CHECK > 1.0
capture_precision VARCHAR NOT NULL   -- TIMESTAMPED | OPENING | PREMATCH | CLOSING
captured_at       TIMESTAMPTZ        -- NULL salvo TIMESTAMPED
observed_before   TIMESTAMPTZ        -- il limite che SI conosce (il kickoff)
available_size    DECIMAL(18,2)      -- solo exchange
source            VARCHAR NOT NULL
ingestion_run_id  VARCHAR
```

### `capture_precision` — le quattro semantiche

| Valore | Significato | `captured_at` | Usabile per |
|---|---|---|---|
| `TIMESTAMPED` | istante reale (poller, API) | l'istante | **tutto**, incluso il point-in-time |
| `OPENING` | primo prezzo pubblicato | NULL | drift, non PIT |
| `PREMATCH` | raccolto a un momento non dichiarato | NULL | CLV, non PIT |
| `CLOSING` | ultimo prezzo prima del kickoff | NULL | CLV, riferimento |

**Conseguenza operativa:** la macro `odds_as_of()` espone **solo**
`TIMESTAMPED`. Un prezzo senza orologio non può rispondere a *«cosa era
disponibile al tempo T»*, e includerlo lascerebbe un backtest rivendicare un
prezzo che non può provare fosse offerto.

### Esempio reale

Arsenal – Leicester, 11/08/2017, Premier League. Sei righe da un file
Football-Data:

| bookmaker | selection | price | precision | captured_at |
|---|---|---:|---|---|
| pinnacle | HOME | 1.53 | PREMATCH | `NULL` |
| pinnacle | HOME | **1.49** | **CLOSING** | `NULL` |
| pinnacle | DRAW | 4.55 | PREMATCH | `NULL` |
| pinnacle | DRAW | **4.73** | **CLOSING** | `NULL` |
| pinnacle | AWAY | 6.85 | PREMATCH | `NULL` |
| pinnacle | AWAY | **7.25** | **CLOSING** | `NULL` |

### Normalizzazioni ereditate da M1

- **R2** — una sola forma: `(market_type, line, selection)`
- **R3** — linee asiatiche **sempre** in prospettiva casa: «Away +0.5» è
  `(ASIAN_HANDICAP, line = −0.5, selection = 'AWAY')`
- **R4** — `line NOT NULL`, 0.0 per i mercati senza linea
- **R5** — append-only: una correzione è una riga nuova

---

## 2. `ReferenceClose` — vista `reference_market`

La chiusura de-viggata del book di riferimento. **Il denominatore di ogni
numero di CLV.**

```sql
match_id, market_type, line, selection
closing_price       DOUBLE
closing_basis       VARCHAR   -- DECLARED | LATEST
seconds_to_kickoff  BIGINT    -- NULL quando la chiusura non ha orologio
is_trusted          BOOLEAN
closing_fair_prob   DOUBLE
closing_overround   DOUBLE
devig_method        VARCHAR
reference_bookmaker_id VARCHAR
```

### `closing_basis` — perché due valori

| Valore | Significato |
|---|---|
| `DECLARED` | la fonte etichetta la riga come chiusura (le colonne `C` di Football-Data) |
| `LATEST` | l'ultima osservazione timestampata che possediamo |

Una chiusura `LATEST` da un polling rado è un benchmark **più debole**, e M3
deve poterlo distinguere. Con Football-Data tutte le chiusure sono `DECLARED`.

### Esempio reale

Stesso match, dopo il de-vig Shin:

| selection | closing_price | closing_fair_prob | overround | method | basis |
|---|---:|---:|---:|---|---|
| HOME | 1.49 | 0.6626 | 0.0205 | SHIN | DECLARED |
| DRAW | 4.73 | 0.2052 | 0.0205 | SHIN | DECLARED |
| AWAY | 7.25 | 0.1321 | 0.0205 | SHIN | DECLARED |

Somma delle probabilità eque: **1.000000**.

---

## 3. `FairProbability`

Probabilità depurate dall'overround, calcolate **per mercato completo**.

```sql
PRIMARY KEY (match_id, bookmaker_id, market_type, line, selection,
             capture_precision, devig_method)
fair_prob         DOUBLE   -- CHECK > 0 AND < 1
raw_implied_prob  DOUBLE   -- 1 / price
overround         DOUBLE   -- sum(raw) - 1
n_selections      SMALLINT
```

Il **metodo è parte della chiave**: due de-vig coesistono sulla stessa
osservazione e si confrontano senza re-ingestione.

**Un mercato incompleto viene saltato e contato, mai normalizzato.** Un 1X2
senza il pareggio, normalizzato, produce un numero sicuro di sé che nulla a
valle potrebbe distinguere da uno vero.

---

## 4. Margini osservati, per book

Misurati su 10 campionati-stagione. Servono a sapere **contro cosa si compete**.

| Book | Margine di chiusura (mediana) | Nota |
|---|---:|---|
| `pinnacle` | **2.95%** [2.06%, 3.60%] | il riferimento |
| `bet365` | ~5.7% | soft |
| `market_avg` | ~5.4% | media di mercato |
| **`market_max`** | **0.59%** [0.26%, 1.19%] | **miglior prezzo disponibile** |

> Il margine effettivo contro cui si compete, facendo shopping del prezzo
> migliore, è **0.59%**, non il 2.95% di Pinnacle. È la differenza fra servire
> un edge del 3% e servirne uno dello 0.6%. Misurato, non assunto.

---

## 5. Limite dichiarato

Football-Data fornisce **due punti per mercato, non una curva**. Il movimento
di linea si misura fra apertura e chiusura, non lungo il percorso. Lo schema è
pronto a ricevere un poller (`TIMESTAMPED` esiste per quello), ma con le sole
fonti gratuite attuali il drift è un segmento, non una traiettoria.
