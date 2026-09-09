# PR #3 — il layer temporale del mercato

> La domanda non è «chi vincerà Milan-Roma».
> È **«perché il mercato ha spostato Milan-Roma del 9% nelle ultime tre ore»**.

Oggi il progetto non sa rispondere, e non per mancanza di modelli: non ha il
percorso del prezzo, solo due punti agli estremi.

---

## Costruito prima dei suoi dati, di proposito

Il dump di BeatTheBookie è dietro Dropbox e Google Drive, entrambi bloccati
dalla policy di egress. È un **environment access limitation**, non una fonte
mancante: lo schema è documentato, verificato e non cambierà.

Quindi adapter, viste e guardie esistono adesso, e l'ingestione diventerà un
comando invece che un progetto.

**Nessun dato è stato ingerito, e un test lo asserisce.**

## Il dump, non l'export

La stessa fonte produce due artefatti e solo uno è utilizzabile:

| | istante | bookmaker |
|---|---|---|
| **dump SQL** | `ohs.odds_datetime` **per osservazione** | `oh.bookmaker`, 32 nomi reali |
| export `.txt` | 72 punti **orari**, relativi al kickoff | indice di riga, anonimo |

L'export è quello che il paper usa e che si trova per primo. Ricampiona
l'istante su una griglia oraria e butta l'originale — il che lo rende inutile
per la domanda che serve: **una formazione pubblicata a 60–75 minuti dal
kickoff cade dentro una sola cella oraria**, insieme alla finestra di controllo
con cui andrebbe confrontata.

Verificato in `src/generate_odds_series_csv.php` del repository originale:

```php
$time_window_hours = 72;
$interval_mins     = 60;
```

## L'adapter rifiuta di inventare un istante

```python
class MissingInstant(ValueError):
    """A price row with no odds_datetime. Refused rather than defaulted."""
```

Non ha altre modalità: emette solo `TIMESTAMPED`. Una fonte senza istanti non
ha ragione di passare da qui, e accettare una riga senza `odds_datetime`
reintrodurrebbe esattamente ciò che scegliere il dump invece dell'export
serviva a evitare.

Un istante naive viene letto come UTC perché lo script di export fissa
`date_default_timezone_set('UTC')` — detto qui invece che assunto in silenzio,
perché **attaccare il fuso sbagliato a un istante vero è peggio che non averne
uno: sembra corretto.**

---

## Le cinque viste

Tutte filtrano `capture_precision = 'TIMESTAMPED'`. Il filtro **è** il punto:
un prezzo `PREMATCH` e uno `CLOSING` sono due osservazioni di istanti ignoti, e
differenziarli dà una deriva totale senza dire **quando** è avvenuta.
Ammetterli produrrebbe una tabella che sembra una serie temporale e non lo è.

| vista | risponde a |
|---|---|
| `v_market_path` | passo per passo: prezzo, precedente, delta implicito, secondi trascorsi, minuti al kickoff |
| `v_market_moves` | i passi sopra un punto di probabilità — soglia dichiarata prima, non scelta dopo |
| `v_market_summary` | deriva netta **e** distanza percorsa |
| `v_market_breadth` | quanti book si muovono nello stesso minuto |
| `v_path_coverage` | quanto del mercato è osservato — da leggere prima di ogni numero |

### Deriva netta e distanza percorsa non sono la stessa cosa

```
  2.40  →  2.10  →  2.40
  deriva netta      0
  distanza percorsa 0.12
```

Un prezzo che esce e torna ha deriva zero. Mediare solo la deriva farebbe
sparire overreaction e correzione — che sono precisamente i fenomeni
interessanti.

### Un book non è il mercato

Un solo book che si muove può essere un prezzo stantio corretto. Tutti i book
che si muovono insieme è il mercato che cambia idea, e **solo il secondo è
informazione sulla partita**. `v_market_breadth` li separa per minuto.

---

## Le viste sono vuote, ed è corretto

Non esiste una riga `TIMESTAMPED` in nessun dataset. `v_path_coverage`
riporta `n_with_path = 0` e `n_untimestamped_rows` alto.

**Vuoto significa «nessun dato», mai «nessun movimento»** — la stessa
distinzione che PR #2 ha tracciato fra `DATA_GAP` e `NO_SIGNAL`, applicata al
tempo invece che al prezzo.

---

## Due affermazioni della roadmap che restano non dimostrate

Registrate come tali invece di essere adottate:

**«Nei campionati minori nascono gli edge»** — `C-106`, `UNTESTED`. È
largamente creduto e qui non è mai stato misurato: la scansione ha coperto sette
prime divisioni, con una soglia di rilevabilità di 4–7 punti di probabilità.
Niente in questo progetto riguarda Serie C, settore giovanile, calcio femminile
o Scandinavia. Va misurato, non assunto — che è la stessa disciplina applicata
al bias favorito-longshot, che si è rivelato **assente** dove la letteratura lo
dava per presente.

**«Dopo un anno puoi stimare il valore di ogni assenza»** — `C-107`,
`NOT_DEMONSTRATED`. Il calcolo di potenza dice altro: un portiere fuori a
sorpresa capita nel 3–5% delle partite, quindi i 31 eventi necessari per un
effetto di 2 punti richiedono **600–1.000 partite**. Una stagione di un
campionato ne dà ~380, con ~15 eventi portiere. Per la domanda **aggregata**
una stagione basta e avanza; per la **ripartizione per categoria** servono due
campionati raccolti in parallelo.

Meglio saperlo prima di iniziare a raccogliere.
