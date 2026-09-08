# Modello dati delle quote (M2) — progettato prima del codice

Da qui in poi non stiamo costruendo un pronostico: stiamo **ricostruendo il
mercato contro cui misurarlo**. Il modello dati viene quindi fissato prima
dell'implementazione.

---

## Il vincolo che governa tutto

> **Non inventare timestamp per osservazioni che non ne hanno.**

Football-Data pubblica, per ogni mercato, al massimo **due** osservazioni: un
prezzo pre-match e un prezzo di chiusura. La colonna pre-match **non ha un
orario di raccolta**. Attribuirgliene uno preciso metterebbe una falsità dentro
R1, la regola su cui poggia l'intero sistema.

Ogni osservazione porta quindi una `capture_precision` esplicita:

| Valore | Significato | `captured_at` |
|---|---|---|
| `TIMESTAMPED` | la fonte fornisce un istante reale (poller, API) | l'istante osservato |
| `CLOSING` | ultimo prezzo prima del kickoff; semantica definita, orario no | NULL, con `observed_before` = kickoff |
| `PREMATCH` | raccolto a un momento non dichiarato prima del kickoff | NULL |
| `OPENING` | primo prezzo pubblicato del mercato | NULL se la fonte non lo data |

`captured_at` è **nullable per progetto**. Una query point-in-time può usare
solo righe `TIMESTAMPED`; le altre sono utilizzabili per il CLV — che confronta
contro la *chiusura*, non contro un istante — ma non per dire «abbiamo
scommesso tre ore prima».

---

## La catena

```
match → bookmaker → market → selection → odds → precision → source
```

### Tabelle

| Tabella | Ruolo |
|---|---|
| `bookmakers` | anagrafica: `kind` (SHARP/SOFT/EXCHANGE/AGGREGATOR), `is_reference`, commissione |
| `markets` | vocabolario `(market_type, line, selection)`, già definito in M1 |
| `odds_observations` | **la tabella centrale**: una riga per prezzo osservato |
| `odds_closing` | materializzata: la chiusura per chiave, con gate di obsolescenza |
| `fair_probabilities` | probabilità de-viggate per mercato completo, con metodo |
| `reference_market` | la vista che M3 userà come denominatore del CLV |

### `odds_observations`

```sql
match_id, bookmaker_id, market_type, line, selection,
price_decimal,
capture_precision,        -- TIMESTAMPED | OPENING | PREMATCH | CLOSING
captured_at,              -- NULL quando la fonte non lo fornisce
observed_before,          -- limite superiore noto (di norma il kickoff)
available_size,           -- profondità, solo exchange
source, ingestion_run_id, ingested_at
```

Chiave: `(match_id, bookmaker_id, market_type, line, selection, capture_precision, coalesce(captured_at, 'epoch'))`.
Include `capture_precision` perché lo stesso book pubblica legittimamente sia un
pre-match sia una chiusura per la stessa selezione.

### Le cinque distinzioni richieste

| Distinzione | Come è rappresentata |
|---|---|
| **opening** | `capture_precision = 'OPENING'` |
| **prematch snapshot** | `'PREMATCH'` (senza orario) o `'TIMESTAMPED'` (poller) |
| **closing** | `'CLOSING'`, materializzato in `odds_closing` con `is_trusted` |
| **exchange** | `bookmakers.kind = 'EXCHANGE'`, con `commission_rate` e `available_size` |
| **de-vigged reference** | `fair_probabilities` sul book `is_reference`, esposto da `reference_market` |

---

## Regole di normalizzazione, ereditate da M1

- **R2** — una sola forma: `(market_type, line, selection)`. Niente tabelle
  per-mercato.
- **R3** — le linee asiatiche sempre in prospettiva casa. «Away +0.5» è
  `(ASIAN_HANDICAP, line = -0.5, selection = 'AWAY')`.
- **R4** — `line NOT NULL`, 0.0 per i mercati senza linea.
- **R5** — append-only. Una correzione è una riga nuova.

---

## Il de-vig

Rimozione dell'overround **per mercato completo**, mai per singola selezione.
Metodo di default **Shin** (superiore al moltiplicativo sui favoriti), con il
metodo memorizzato per riga così da poterne confrontare altri senza
re-ingestione.

Il **book di riferimento** è Pinnacle: `PSCH/PSCD/PSCA` in Football-Data sono
la sua chiusura 1X2. De-viggata, è il denominatore di ogni numero di CLV che
M3 calcolerà. `bookmakers.is_reference` va trattato come una costante:
cambiarlo invalida ogni CLV storico.

---

## Cosa M2 produce, e cosa non fa

**Produce**: osservazioni di mercato affidabili, chiusure identificate,
probabilità eque, e una vista `reference_market` su cui M3 possa lavorare.

**Non fa**: nessun CLV, nessun edge, nessuno staking, nessuna strategia. M2
costruisce il metro; M3 misura.

---

## Limite dichiarato

Football-Data dà **due punti, non una storia di linea**. Il movimento delle
quote — l'idea più interessante presa da OddsIntel — richiede un poller su una
fonte con timestamp reali. Lo schema è pronto a riceverlo (`TIMESTAMPED` esiste
proprio per quello), ma con le sole fonti gratuite attuali il drift si misura
fra apertura e chiusura, non lungo la curva.
