# Scansione di ipotesi — 14 situazioni, 3.502 partite

```
python scripts/scan_hypotheses.py --json docs/validation/hypothesis-scan.json
```

Le fasi 2–6 del metodo, automatizzate: genera ipotesi, testale tutte, misura,
replica, scarta. Con la correzione che quel metodo richiede e che è facile
dimenticare.

---

## L'aritmetica che rende pericolosa «100 ipotesi, scarta il 99%»

Testare 41 nulle vere al 5% produce **circa 2 falsi positivi in media**. La
procedura poi riporta il migliore. Il sopravvissuto di cento test non è
evidenza: è una **statistica d'ordine**.

Non è un problema di attenzione, è un fatto matematico. Tre difese:

1. **Benjamini-Hochberg** sull'intera famiglia, controllando il false discovery
   rate invece di ogni test in isolamento.
2. **Replica su più dataset** — un segno che vale in una lega-stagione e in
   nessun'altra è come appare l'overfitting visto da dentro.
3. **Potenza dichiarata** — vedi sotto. È la difesa che mancava alla prima
   versione di questo documento.

---

## Il risultato

> **Nessuna delle 14 situazioni sopravvive.** Zero superano BH a q = 0.10, e
> zero replicano in ≥ 7/10 dataset.

Le ipotesi testate — tutte calcolabili dal magazzino esistente, nessun feed che
non c'è:

| famiglia | ipotesi |
|---|---|
| riposo | `home_short_rest`, `away_short_rest`, `home_rest_advantage`, `away_rest_advantage` |
| congestione | `home_congested`, `away_congested` (terza partita in 8 giorni) |
| motivazione | `dead_rubber`, `mismatch_late_season` |
| calendario | `midweek`, `festive`, `season_opening` |
| prezzo | tre split sul prezzo della selezione |

Le coppie riposo/congestione sono **simmetriche di proposito**: un bias che
appare su un solo lato di una coppia simmetrica è quasi sempre rumore, e non lo
si può vedere se non si testano entrambi.

Il valore più estremo osservato è `dead_rubber / DRAW`, delta −0.067, che è
sotto la soglia corretta e ha `n_in = 60` — un campione su cui non si
costruisce niente.

---

## Quanto avrebbe potuto trovare — la parte che qualifica il risultato

```
  z critica                        3.03 (rango 1) .. 1.64 (rango m)
  effetto minimo rilevabile        0.0716 (severa) / 0.0388 (lasca)
  effetto massimo osservato        0.0666
```

> **«Nessun bias trovato» significa «nessun bias più grande di ~4–7 punti di
> probabilità».**

Un bias di **2–3 punti** sarebbe estremamente profittevole su un mercato con
3,3% di margine — e resta interamente sotto la soglia di rilevabilità con 3.502
partite. Questa scansione può escludere solo mispricing grossolani.

Il vincolo è il campione, non il metodo: per scendere a 2 punti servirebbe
all'incirca un ordine di grandezza in più di partite.

---

## La calibrazione del mercato, e perché i controlli sono falliti

Prima versione di questo lavoro: tre «controlli positivi» basati sul bias
favorito-longshot, il mispricing più documentato in letteratura. Nessuno è
scattato, e l'output stesso diceva che senza una spiegazione non si poteva
concludere nulla. Ecco la spiegazione.

| banda (prezzo grezzo) | n | grezzo | de-viggato | realizzato | grezzo − real | fair − real | z |
|---|---|---|---|---|---|---|---|
| 0.00–0.05 | 64 | 0.0417 | 0.0334 | 0.0312 | +0.0105 | +0.0021 | +0.10 |
| 0.05–0.10 | 412 | 0.0780 | 0.0682 | 0.0874 | −0.0093 | −0.0191 | −1.38 |
| 0.10–0.15 | 645 | 0.1263 | 0.1161 | 0.1023 | +0.0240 | +0.0138 | +1.16 |
| 0.15–0.20 | 930 | 0.1753 | 0.1651 | 0.1817 | −0.0064 | −0.0166 | −1.31 |
| 0.20–0.30 | 3475 | 0.2581 | 0.2480 | 0.2446 | +0.0135 | +0.0034 | +0.47 |
| 0.30–0.40 | 1906 | 0.3383 | 0.3278 | 0.3332 | +0.0051 | −0.0053 | −0.49 |
| 0.40–0.50 | 1070 | 0.4460 | 0.4347 | 0.4299 | +0.0161 | +0.0048 | +0.32 |
| 0.50–0.65 | 1072 | 0.5707 | 0.5576 | 0.5513 | +0.0193 | +0.0063 | +0.42 |
| 0.65–0.80 | 639 | 0.7186 | 0.7035 | 0.6933 | +0.0253 | +0.0103 | +0.56 |
| 0.80–1.01 | 293 | 0.8511 | 0.8328 | 0.8532 | −0.0021 | −0.0204 | −0.99 |

**Il prezzo de-viggato segue la frequenza realizzata in ogni banda**, dal 3% al
85%. Scostamento massimo |z| = 1.38, senza alcun andamento sistematico.

E il bias favorito-longshot **non c'è**: guardando `grezzo − real`, il margine
non cresce verso i longshot. A 0.05–0.10 vale **−0.0093** (i longshot vincono
*più* di quanto il prezzo grezzo implichi) e a 0.65–0.80 vale **+0.0253**. Su
questo mercato Pinnacle carica più margine sui favoriti che sui longshot —
l'opposto del bias classico.

Un controllo che cerca un bias **assente dal mercato che sta controllando** non
può validare niente. La validazione dello scanner sta altrove, dove deve stare:
[`test_m7_hypothesis_scan.py`](../../test/fiorino/test_m7_hypothesis_scan.py)
pianta un bias noto di 20 punti e verifica che venga trovato, e pianta uno split
arbitrario e verifica che **non** venga trovato.

### Un difetto di disegno che il controllo ha scoperto

La prima versione definiva il longshot a livello di **partita**:

```sql
raw_home < 0.12 OR raw_away < 0.12
```

Ma questo seleziona partite in cui un lato è un longshot **e l'altro è un
grosso favorito**. Testando `HOME` dentro quel sottoinsieme si mescolano i due
casi e il bias si annulla quasi esattamente — z = +0.63 sul mispricing più
documentato della letteratura.

Il bias favorito-longshot è una proprietà di un **prezzo**, non di una partita.
Da qui `selection_level`: il predicato porta un token `{prob}` sostituito con la
probabilità della selezione stessa.

Il controllo non ha trovato il bias — ma ha trovato un difetto nello scanner.
È esattamente il suo lavoro.

---

## Limiti dichiarati

* **Potenza.** Vedi sopra. Il risultato esclude bias grossolani, non piccoli.
* **`dead_rubber` è un'approssimazione.** «Niente per cui giocare» è
  ricostruito da punti e giornate residue, non dalla matematica reale della
  classifica (salvezza, Europa, titolo). Con `n_in = 60` non avrebbe comunque
  potenza.
* **«Squadre dopo la Champions» non è testabile.** Serve il calendario delle
  coppe europee, che non è nel magazzino. `home_short_rest` è la cosa più
  vicina che questi dati esprimono, e non è la stessa.
* **Un solo mercato.** 1X2, un solo book di riferimento.
* **Il contrasto, non il bias assoluto.** La statistica è
  `bias(S) − bias(non S)` perché il de-vig può essere esso stesso distorto —
  Shin ombreggia i longshot per costruzione. Il contrasto annulla ogni bias che
  il de-vig applichi uniformemente, ma non uno che vari con la banda di prezzo.

---

## Cosa significa per la roadmap

Il risultato **non contraddice** la priorità già stabilita — quote timestampate,
formazioni, infortuni — la rafforza per una ragione precisa: le situazioni
derivabili dal calendario e dalla classifica sono state cercate, e non c'è
niente di grosso. Restano le fonti che portano informazione **esogena** al
prezzo, e quelle non sono raggiungibili da qui.

E aggiunge un vincolo quantitativo alla fase successiva: con 3.502 partite non
si vede sotto i 4 punti di probabilità. Un esperimento sulle formazioni
progettato per trovare un effetto di 2 punti ha bisogno di **più dati di
quanti ne serva raccoglierne per una stagione su due campionati**, e conviene
saperlo prima di iniziare a raccoglierli.
