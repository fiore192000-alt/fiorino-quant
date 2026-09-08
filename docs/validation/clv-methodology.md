# Metodologia CLV

Come il Closing Line Value è definito, calcolato e interpretato in Fiorino
Quant. Ogni numero in questo documento proviene da
`scripts/validate_clv.py` su 10 campionati-stagione reali, 37.482 scommesse.

---

## 1. Le tre metriche, e perché sono diverse

```
clv_price = price_taken / closing_price − 1
clv_ev    = closing_fair_prob × price_taken − 1
clv_log   = ln(closing_fair_prob × price_taken)
beat_close = price_taken > closing_price
```

| Metrica | Cosa misura | Quando usarla |
|---|---|---|
| `clv_price` | miglioramento **puro di prezzo** | diagnostica del movimento di linea |
| **`clv_ev`** | **ROI atteso** se la chiusura equa è la verità | **decidere** |
| `clv_log` | crescita logaritmica, **additiva** fra scommesse | aggregare senza bias |
| `beat_close` | frazione di volte che hai battuto la chiusura | intuizione, non decisione |

**`clv_price` ignora l'overround.** Su un mercato largo lusinga: puoi battere il
prezzo di chiusura e avere comunque EV negativo, perché il margine è ancora
tutto lì. Riportalo, non deciderci.

**`clv_ev` è sulla stessa scala dello yield.** «CLV +2%, yield −1%» è
un'affermazione leggibile sulla fortuna. Due grandezze incomparabili non lo
sarebbero.

**`clv_log` è additivo.** La media aritmetica di rapporti ha un bias verso
l'alto; `ln(p·o)` si somma, quindi una sequenza aggrega senza distorsione.

---

## 2. Contro cosa si misura

Contro la chiusura **de-viggata del book di riferimento** — Pinnacle — **mai**
contro il book con cui si è scommesso. Confrontare un book soft con se stesso
non misura nulla.

`bookmakers.is_reference` è di fatto una costante: cambiarla invalida ogni
numero di CLV storico.

---

## 3. La scelta del de-vig

De-vig **sempre su mercato completo**, mai su singola selezione: il margine è
una proprietà dell'intero set di prezzi.

### Perché Shin di default

I book non spalmano il margine uniformemente: lo caricano sugli outsider, per
proteggersi da chi sa qualcosa su un esito improbabile. Il de-vig
moltiplicativo assume una distribuzione uniforme e quindi **sovrastima i
longshot** — esattamente dove guarda un value bettor.

Misurato su una chiusura Pinnacle reale (1.49 / 4.73 / 7.25):

| Metodo | HOME | DRAW | AWAY |
|---|---:|---:|---:|
| Moltiplicativo | 0.6577 | 0.2072 | 0.1352 |
| **Shin** | 0.6626 | 0.2052 | **0.1321** |

Differenza sul longshot: **−30 bps**.

### Perché il CLV cambia di ~80 bps

Sotto de-vig moltiplicativo vale `fair_i = (1/price_i)/S`, quindi
`fair × price = 1/S` **per ogni selezione**, e prendendo la chiusura stessa:

```
CLV_ev  ==  1/(1 + overround) − 1  ==  −overround/(1 + overround)
```

Un numero noto in anticipo. Verificato sulla Premier League 2017-18:

| De-vig | CLV_ev misurato | Forma chiusa | Scarto |
|---|---:|---:|---:|
| Moltiplicativo | −0.02066376 | −0.02066992 | **6.2e-06** |
| Shin | −0.02879403 | −0.02066992 | 8.1e-03 |

Il moltiplicativo riproduce l'identità a livello di arrotondamento: **è la
prova che la catena è corretta.**

Shin devia **per costruzione**: ridistribuendo, `fair × price` non è più
costante.

| Selezione | `fair × price` sotto Shin |
|---|---:|
| HOME | 0.9781 |
| DRAW | 0.9706 |
| AWAY | 0.9648 |

Gli ~80 bps sono quella ridistribuzione. **Non sono rumore, e sono più di molti
edge dichiarati** — per questo il metodo è memorizzato riga per riga.

### Quando usare quale

| Metodo | Quando |
|---|---|
| **Shin** | default per tutto ciò che decide: pricing, edge, CLV di riferimento |
| Moltiplicativo | quando serve l'identità analitica come test di correttezza; e per confrontare con letteratura che lo assume |
| Power / Odds-ratio / Logaritmico | disponibili per confronto; nessuno è default |

Il metodo è una colonna, non un'assunzione: due de-vig possono coesistere sulla
stessa chiave e si confrontano senza re-ingestione.

---

## 4. Quando il CLV **non** viene calcolato

Rifiutare di rispondere fa parte del rispondere. Tre esclusioni, contate e mai
silenziose:

| Motivo | Quando |
|---|---|
| `no_reference_close` | il book di riferimento non ha prezzato quella partita |
| `line_not_matched` | ha prezzato una linea **diversa** |
| `no_fair_probability` | la chiusura esiste ma il mercato era incompleto |

Confrontare contro una linea diversa non è una misura più debole: è
**sbagliata**. `v_clv_coverage` riporta quanta parte del ledger si è potuta
valutare — un CLV calcolato sul sottoinsieme che per caso aveva una chiusura
non è un campione casuale.

---

## 5. Come si legge un CLV

`v_clv_summary` espone il **t-stat** contro zero. Con qualche centinaio di
scommesse un |t| > 2 è segnale reale; lo yield ne richiede migliaia.

Dimostrazione numerica, su una strategia deliberatamente chiaroveggente con 108
scommesse:

```
CLV t-stat      +19.23              inequivocabile
yield 95% CI    [−2.7%, +95.9%]     comprende ancora lo zero
```

| CLV | Yield | Lettura |
|---|---|---|
| + | − | sfortunato, edge plausibile |
| − | + | **fortunato, aspettati che finisca** |
| − | − | nessun edge |
| + | + | coerente con un edge |
