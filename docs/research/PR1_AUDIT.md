# Audit del PR #1

**Oggetto:** [`fiore192000-alt/fiorino-quant#1`](https://github.com/fiore192000-alt/fiorino-quant/pull/1)
`claude/european-football-value-bet-ddqnq6` → `master`, testa `c791b17`.
**Ampiezza reale:** 19 commit, 156 file, +26.679 / −1.
**Metodo:** ogni riga sotto è verificata con un comando, non asserita. Dove ho
solo un'inferenza, lo dico.

---

## Verdetto

> **NON PASSA.** Quattro MUST FIX, di cui due rendono il sistema **non
> installabile** e due indeboliscono guardie di sicurezza che sembrano attive e
> non lo sono.
>
> Nessuno riguarda la correttezza statistica: il nucleo point-in-time, la regola
> 9 e la disciplina CLV reggono. I difetti sono di **confezionamento e di
> perimetro delle guardie** — cioè esattamente la categoria che una suite verde
> non vede, perché la suite gira dall'albero di lavoro.

È la stessa classe dell'incidente `.gitignore`: il codice funziona **qui** e non
funziona **altrove**, e nulla lo segnala.

---

## MUST FIX

### M1. `fiorino` non è un pacchetto installabile

```python
# setup.py
packages=find_packages(include=["penaltyblog", "penaltyblog.*"])
```

`pip install .` installa **19 pacchetti penaltyblog e zero pacchetti fiorino**.
Ventisette pacchetti esistono nell'albero e nessuno è dichiarato:

```
fiorino, fiorino.backtest, fiorino.clv, fiorino.core, fiorino.data,
fiorino.data.access, fiorino.data.db, fiorino.data.identity, ...
fiorino.models, fiorino.research, fiorino.pricing, fiorino.odds, ...
```

**Perché non se n'è accorto nessuno:** i test girano dalla radice del
repository, dove `import fiorino` risolve dalla directory corrente. Anche il job
`clean-clone` che ho scritto io passa **per la ragione sbagliata** — installa
il pacchetto, poi importa dal `cwd`.

**Impatto:** il gate di riproducibilità non è soddisfatto. Un ambiente pulito
non può importare il sistema.

### M2. `duckdb` e `hypothesis` non sono dipendenze dichiarate

Zero occorrenze in `pyproject.toml`. DuckDB è il motore dell'intero magazzino;
Hypothesis regge i test di proprietà che hanno trovato i bug di normalizzazione
in M1.

**Impatto:** un'installazione pulita non può eseguire nulla. Insieme a M1, il
sistema è oggi riproducibile solo dentro questo albero di lavoro.

### M3. La guardia PIT nomina una tabella che non esiste

```python
RAW_TABLES = ("matches", "match_results", "odds_snapshots", "team_aliases")
```

`odds_snapshots` **non compare in nessuna migrazione**. La tabella si chiama
`odds_observations`. Quella voce non guarda niente e non può fallire.

Mancano inoltre dall'elenco: `odds_observations`, `fair_probabilities`,
`predictions`, `bets`, `equity_curve`.

**È la stessa classe di difetto** della vista `v_analytic_lineups` trovata in
M6.5 — una guardia irraggiungibile dà la stessa rassicurazione senza la
protezione. Lì l'ho corretta; qui era già presente e non l'avevo vista.

### M4. La guardia PIT non copre `fiorino/models`

```python
GUARDED = ("strategy", "backtest", "portfolio", "staking", "pricing")
```

`fiorino/models` contiene `fitting.py`, cioè **il codice che decide su cosa un
modello può addestrarsi**. Oggi passa correttamente da `PointInTimeView`, ma
per convenzione: nulla impedisce a una modifica futura di leggere direttamente,
e la guardia tacerebbe.

`fiorino/models/incremental.py` legge già `FROM predictions` direttamente.

---

## SHOULD FIX

### S1. Non esiste una tassonomia dichiarata produttori / consumatori

Questi pacchetti leggono tabelle grezze e **hanno ragione di farlo**:

| pacchetto | cosa fa | legittimo? |
|---|---|---|
| `fiorino/odds` | ingestione e de-vig | sì, è un produttore |
| `fiorino/clv` | misura a posteriori | sì, misura il passato |
| `fiorino/research` | analisi retrospettiva | sì, non decide nulla |
| `fiorino/data/*` | costruisce il magazzino | sì |

Ma la distinzione fra «decide» e «misura» è **convenzione, non dichiarazione**.
Un pacchetto nuovo eredita il silenzio, non la regola. Serve una lista esplicita
con la motivazione, e la guardia deve leggere quella.

### S2. Le quote di chiusura sono raggiungibili da qualunque strategia

`fiorino/backtest/strategy.py:131` fa `JOIN reference_market` — è
`TakeValueVsClose`, l'oracolo chiaroveggente, ed è **deliberato**. Ma nulla lo
marca come unico lettore autorizzato: una strategia nuova può fare lo stesso
join e nessun test la ferma.

Il gate che avete elencato («closing odds non possono entrare nella decisione»)
è oggi soddisfatto per disciplina, non per costruzione.

### S3. `odds_as_of()` è aggirato, oggi correttamente

Le strategie leggono `odds_observations` filtrando `capture_precision`, non
attraverso `odds_as_of()`. È **corretto adesso**, perché `odds_as_of()` legge
solo `TIMESTAMPED` e non esiste una riga TIMESTAMPED — usarlo restituirebbe
sempre vuoto.

Ma diventa una via di leakage attiva **nel momento esatto** in cui arrivano i
dati timestampati, cioè il primo obiettivo di M6.5. Va chiuso prima, non dopo.

### S4. `test.yml` fallirebbe se lanciato

Esegue `pytest -v test`, che ora include `test/fiorino`, dopo aver installato
solo `.[cloud]` e `pytest` — senza duckdb né hypothesis.

Non è rosso adesso: i trigger sono `workflow_dispatch` soltanto (`push` è
commentato nel repository originale). È un difetto **latente** che ho introdotto
mettendo i test sotto `test/`, e che si manifesta al primo dispatch manuale.

### S5. Il titolo e la descrizione del PR non corrispondono più al contenuto

Titolo: *«architettura del sistema quantitativo, schema DuckDB e roadmap»* —
descrive M1. Il PR contiene M1–M6.5, lo scanner di ipotesi e l'event study.

Un revisore legge una descrizione che non corrisponde al diff. Con 156 file è
un problema pratico, non formale.

### S6. `coverage.yml` copre solo penaltyblog

`--cov=penaltyblog`. La copertura di `fiorino` non è mai misurata.

---

## NICE TO HAVE

* **N1.** I seed sono fissati per modulo (`20260908`, `20260909`) invece che in
  un punto solo. Riproducibile, ma la provenienza è sparsa.
* **N2.** I JSON degli esperimenti non registrano il commit che li ha prodotti.
  La riproducibilità dipende dal ricordarsi quale versione girava.
* **N3.** `fiorino/strategy`, `fiorino/portfolio`, `fiorino/staking`,
  `fiorino/reporting`, `fiorino/data/ingest/features` sono pacchetti vuoti o
  quasi. Guardati dalla guardia PIT, il che è corretto in anticipo, ma un
  lettore non distingue «vuoto perché è M7» da «vuoto perché dimenticato».

---

## ACCEPT

Verificato, funzionante, da non toccare:

| | verifica |
|---|---|
| **Timestamp inventati impossibili** | `CHECK ((capture_precision = 'TIMESTAMPED') = (captured_at IS NOT NULL))` — testato in questo audit: un PREMATCH con `captured_at` **viene rifiutato dal database** |
| **Regola 9 su tre livelli** | guard Python, `CHECK (match_method <> 'FUZZY')` su squadre *e* giocatori, `v_analytic_*` |
| **Identità non giudicata esclusa** | `v_analytic_matches` e `v_analytic_lineups` escludono alias non `APPROVED` |
| **`published_at` non fabbricabile** | `NOT NULL`, nessun `DEFAULT` — testato |
| **Event study rifiuta dati non timestampati** | `require_timestamped()` **solleva**, non avvisa |
| **Correzione per test multipli** | Benjamini-Hochberg sull'intera famiglia, controlli inclusi nel denominatore |
| **penaltyblog non toccato** | `git diff origin/master...HEAD -- penaltyblog/` è **vuoto** |
| **Suite** | 502 test verdi |
| **Clean clone** | il job asserisce il numero di relazioni, non solo che le migrazioni girino |
| **Igiene del repository** | `test_repo_hygiene.py` impedisce il ripetersi dell'incidente `.gitignore` |

---

## Cosa NON è stato auditato

* **Il contenuto statistico dei risultati.** Questo audit riguarda l'ingegneria.
  I risultati M5/M6 e la scansione hanno i loro documenti.
* **La correttezza del de-vig di Shin** oltre l'identità di calibrazione già
  verificata in M3 (6.2e−06).
* **La performance.** La suite impiega 14 minuti; non ho profilato.
* **La sicurezza delle dipendenze.** Nessuna scansione delle vulnerabilità.

---

## Ordine di intervento proposto

M1 e M2 insieme, in un PR minimo che tocca solo `setup.py` e `pyproject.toml`:
senza quelli il sistema non esiste fuori da questo albero, e ogni altra
correzione è costruita su una base che non si installa.

Poi M3 e M4, che sono una modifica sola: la guardia PIT va riscritta attorno a
una **tassonomia dichiarata** (S1), il che chiude anche S2 nello stesso punto.

S3 va chiuso **prima** che arrivino i dati timestampati, non dopo.

S4, S5, S6 e i NICE TO HAVE non bloccano.
