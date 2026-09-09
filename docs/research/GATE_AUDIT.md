# Gate Audit finale — PR #1

Tre obiettivi, nessuno dichiarato senza averlo eseguito.

---

## 1. Un clone pulito ricostruisce tutto

Clone del branch in una directory vuota, virtualenv nuovo, install dal solo
`requirements.txt`:

```
14 migrazioni su disco, 14 applicate, 39 tabelle, 15 viste     PASS
Streamlit headless, sei pagine                                 HTTP 200
costruzione del magazzino a runtime, tre volte identica        19 s, 575 MB
suite completa nel clone                                       PASS, ma vedi sotto
```

### Due contratti diversi, e vanno detti separati

Eseguendo il gate è emerso che `requirements.txt` **non basta per la suite**:
i test M5 importano penaltyblog per il fit, e penaltyblog vuole `tqdm` e il
resto delle sue dipendenze. Con il solo `requirements.txt` la suite muore su
`ModuleNotFoundError: No module named 'tqdm'`.

Non è un difetto: sono due contratti distinti, e confonderli sarebbe stato il
difetto.

| contratto | installa | serve a |
|---|---|---|
| `requirements.txt` | streamlit, duckdb, pytz, pandas… | **l'app**, su Streamlit Cloud |
| `pip install -e .` | penaltyblog + fiorino + tutte le dipendenze | **la ricerca e i test** |

L'app è deliberatamente più leggera: non addestra modelli, quindi non ha
bisogno di penaltyblog né delle sue estensioni Cython, che su Community Cloud
allungherebbero il build senza servire a nulla di ciò che la dashboard mostra.

Il workflow `clean-clone.yml` usa il secondo contratto, che è quello giusto per
un CI di test. Verificato: `pip install -e .` in un venv vuoto compila le
estensioni e la suite gira.

Il gate ha **fallito quattro volte** prima di passare, e ogni fallimento era
invisibile dall'albero di sviluppo perché la suite gira dalla radice, dove gli
import risolvono dal `cwd` e ogni dipendenza è già presente:

| # | difetto | perché non si vedeva |
|---|---|---|
| 1 | `import penaltyblog` fallisce: la directory del repo oscura il pacchetto installato e nel clone i `.so` non ci sono | in sviluppo i `.so` sono compilati |
| 2 | `pytz` mancante — DuckDB lo richiede, pandas 3.0 l'ha rimosso dalle transitive | in sviluppo era già installato |
| 3 | il bronze è immutabile e l'app scriveva su percorso fisso | serviva un secondo caricamento |
| 4 | il de-vig collideva sulla chiave primaria in fallback, e prima ancora era **non deterministico** | serviva un ambiente senza penaltyblog |

Il quarto è il più grave e non riguarda il deploy: sondare penaltyblog a ogni
chiamata è non deterministico, perché un import fallito lascia i sottomoduli
riusciti in `sys.modules` e il secondo tentativo riesce. Una ricostruzione
produceva righe `SHIN` e `MULTIPLICATIVE`, la successiva solo `SHIN`, **da input
identico** — cioè una violazione silenziosa della regola A di M1.

## 2. Ogni claim ha un test riproducibile

Non tutti ce l'hanno, ed è la parte utile della risposta.

`docs/research/CLAIMS.json` classifica **29 affermazioni**:

```
PROVEN               15    un test deterministico le verifica, e può fallire
TESTED_BUT_LIMITED    7    misurate su dati reali, con il limite dichiarato
UNTESTED              3    il percorso esiste, nessun test lo esercita
DATA_GAP              2    non testabili: il dato non esiste qui
NOT_DEMONSTRATED      2    non affermate. Elencate perché nessuno le deduca
```

Il registro è **validato dalla suite**: `test_claims_registry.py` raccoglie i
test reali con pytest e fallisce se un claim marcato `PROVEN` ne nomina uno che
non esiste. Un registro che nessuno verifica diventa un documento di marketing
entro una release — gli stati restano mentre i test dietro vengono rinominati o
cancellati, e nessuno se ne accorge perché un JSON non può fallire.

Scrivendolo, il test ha trovato due pigrizie nel registro stesso: un claim che
non era una frase, e due `limits` che dicevano «come sopra» invece di dichiarare
il limite. `TESTED_BUT_LIMITED` senza un limite scritto è `PROVEN` con un
vestito migliore.

### La distinzione che conta

Sette claim sono `TESTED_BUT_LIMITED` **per lo stesso motivo**: la misura vive
in uno script che scarica dalla rete (`validate_backtest`, `validate_models`,
`validate_m6`, `scan_hypotheses`) e non nella suite automatica. Sono
riproducibili, non automatici.

Questo include i risultati principali: mercato batte modello 10/10,
`MARKET + MODEL` non batte `MARKET` 0/10, CLV negativo 30/30. La suite verifica
**la macchina**; gli script verificano **il risultato**.

## 3. Cosa è provato e cosa no

I due estremi, per esteso:

> **C-200 — «Fiorino Quant può guadagnare»: NOT_DEMONSTRATED.**
> Nessuna strategia ha mai prodotto un CLV positivo fuori campione che non
> fosse definizionale. Elencato esplicitamente, con un test che impedisce di
> cambiarne lo stato in silenzio.

> **C-018 — nessuna situazione mal prezzata: TESTED_BUT_LIMITED.**
> Effetto minimo rilevabile **0.039–0.072** punti. Esclude mispricing
> grossolani, **non** un bias di 2–3 punti che sarebbe molto profittevole.

E i tre `UNTESTED`, che sono le porte ancora aperte:

* **C-103** — xG, infortuni, riposo, congestione, meteo: **mai testati**.
  Niente in M1–M6 li riguarda.
* **C-104** — il prior di lega non è mai stato esercitato dalla validazione:
  con `min_train = 60` tutte le squadre hanno già giocato al primo fit.
* **C-105** — handicap asiatici e totals sono quotati e internamente coerenti,
  ma senza una chiusura di riferimento non sono mai stati **misurati** contro il
  mercato.

---

## I rischi segnalati, e cosa è stato fatto

**B — tasso di fallback.** Implementato come gate, non come nota:
`MAX_FALLBACK_RATE = 0.25`, e `fit_and_price` **solleva** `FallbackTooHigh`
oltre quella soglia. Il fallback è onesto e contato, ma non è lo stesso modello:
ricava le lambda dai parametri invece che dalla griglia della libreria. Poche
fixture sono uno scudo contro un bug; una quota grande è una distribuzione di
previsioni materialmente diversa sotto lo stesso nome, e un risultato calcolato
su di essa non appartiene al confronto in cui verrebbe messo.

**A — Shin come grado di libertà del ricercatore.** Non ancora chiuso. Il metodo
è oggi un argomento con default; va fissato per dataset nel modulo
dell'esperimento, prima del test. Registrato come debito, non risolto.

**C — la potenza deve essere strutturale in ogni report.** Parzialmente: la
scansione la riporta e il registro la porta nei `limits` di C-018. Non è ancora
un campo obbligatorio di ogni report.

---

## Verdetto

```
1. clone pulito ricostruisce tutto          PASS  (dopo 4 correzioni)
2. ogni claim ha un test riproducibile      PASS  con la distinzione dichiarata:
                                                  15 automatici, 7 riproducibili
                                                  a mano, 5 non testabili o non
                                                  testati, 2 non affermati
3. lista machine-readable                   docs/research/CLAIMS.json,
                                            validata dalla suite
```

Il PR è coerente con ciò che dichiara. La cosa che **non** dichiara di essere è
un sistema che guadagna, ed è l'unica affermazione che conterebbe.
