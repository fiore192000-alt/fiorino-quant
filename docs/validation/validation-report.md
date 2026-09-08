# Validation Report — M1–M3

Verifica fuori campione della catena identità → mercato → CLV.

**Riproducibile:** `python scripts/validate_clv.py --json out.json`
Ogni numero qui viene da quell'esecuzione. Le fonti sono archivi reali di
Football-Data.co.uk mirrorati su GitHub, con gli URL nel file.

---

## Perimetro

**10 campionati-stagione, 7 leghe, 6 stagioni, 37.482 scommesse.**

| Dataset | Partite | Scommesse |
|---|---:|---:|
| ENG_PL 2017-18 | 380 | 2.280 |
| ENG_PL 2018-19 | 380 | 2.280 |
| ENG_PL 2019-20 | 380 | 4.560 |
| ENG_PL 2020-21 | 380 | 4.560 |
| ESP_LL 2019-20 | 380 | 4.554 |
| ITA_SA 2019-20 | 380 | 4.560 |
| DEU_BL1 2024-25 | 306 | 3.672 |
| FRA_L1 2024-25 | 306 | 3.672 |
| NLD_ED 2024-25 | 306 | 3.672 |
| PRT_L1 2024-25 | 306 | 3.672 |

La strategia replay è indiscriminata: prende ogni prezzo pre-match. **Non è
una strategia** — è lo strumento che valida la macchina e fissa il baseline.

---

## Risultati

| Dataset | Chiusura | Pre-match | Gap | CLV_ev | t | beat-close |
|---|---:|---:|---:|---:|---:|---:|
| ENG_PL 2017-18 | 0.0206 | 0.0203 | −0.0003 | −0.0316 | −18.9 | 0.456 |
| ENG_PL 2018-19 | 0.0223 | 0.0223 | +0.0000 | −0.0359 | −20.3 | 0.481 |
| ENG_PL 2019-20 | 0.0289 | 0.0295 | +0.0007 | −0.0371 | −26.5 | 0.473 |
| ENG_PL 2020-21 | 0.0233 | 0.0236 | +0.0003 | −0.0290 | −20.6 | 0.465 |
| ESP_LL 2019-20 | 0.0314 | 0.0325 | +0.0011 | −0.0419 | −27.5 | 0.469 |
| ITA_SA 2019-20 | 0.0326 | 0.0327 | +0.0001 | −0.0427 | −26.7 | 0.483 |
| DEU_BL1 2024-25 | 0.0295 | 0.0349 | +0.0054 | −0.0465 | −28.7 | 0.472 |
| FRA_L1 2024-25 | 0.0294 | 0.0349 | +0.0055 | −0.0471 | −28.5 | 0.455 |
| NLD_ED 2024-25 | 0.0360 | 0.0543 | **+0.0183** | −0.0573 | −31.3 | 0.446 |
| PRT_L1 2024-25 | 0.0353 | 0.0522 | **+0.0169** | −0.0651 | −34.2 | 0.426 |

---

## Cosa ha replicato

**CLV_ev negativo in 10/10.** Media −0.0434, range [−0.0651, −0.0290]. Chi
scommette indiscriminatamente perde il margine, ovunque, sempre. t fra −18.9 e
−34.2.

**Il CLV segue il margine.** Premier League 2017-18 (chiusura 2.06%) →
CLV −0.032; Liga Portugal 2024-25 (3.53%) → CLV −0.065. La relazione è quella
che la teoria prevede, e regge su leghe e stagioni diverse.

**Il margine di chiusura Pinnacle è stabile:** mediana 2.95%, range
[2.06%, 3.60%], più largo nelle leghe minori — come atteso.

**Nessuna scommessa porta un orologio inventato:** 0 su 37.482.

---

## Cosa NON ha replicato — e va corretto

### L'asimmetria HOME/AWAY era un artefatto

Sulla sola Premier League 2017-18 avevo riportato:

```
HOME  clv_price  −0.0043
AWAY  clv_price  +0.0045
```

e l'avevo descritta come «una proprietà osservata del mercato: il denaro
tardivo va sui favoriti di casa».

**Fuori campione non regge:**

| | |
|---|---|
| HOME drift negativo | 7/10 |
| AWAY drift **positivo** | **4/10** — un lancio di moneta |
| media HOME | −0.0098 |
| media AWAY | −0.0105 — praticamente identica, non opposta |

Era un artefatto di una stagione. **Non è una feature, non è un controllo di
qualità, non va usata.** È esattamente il tipo di risultato che una sola
stagione produce per caso e che una validazione multi-stagione uccide.

### Il gap pre-match/chiusura non è uniforme

In 8/10 dataset il prezzo pre-match ha lo stesso margine della chiusura
(gap ≤ +0.55%): sono di fatto co-temporali.

In **2/10** — NLD_ED e PRT_L1 2024-25 — il gap è **+1.8% e +1.7%**: lì la
colonna pre-match è un prezzo di **apertura**, non di poco prima del kickoff.

**Conseguenza:** un baseline CLV calcolato su una colonna di apertura non è
confrontabile con uno calcolato su una co-temporale. Il controllo
`check_prematch_margin_divergence` ora segnala esattamente questi casi.

### Il baseline non è un numero unico

Avevo proposto **−0.028 / t −10.66** come «il benchmark da battere». È
sbagliato: quel numero è la Premier League 2017-18 con la sola Pinnacle.

Il baseline è **per dataset**, e varia da −0.029 a −0.065 secondo il margine
del mercato. Un modello va confrontato con il baseline **del proprio**
campionato-stagione, non con una costante globale.

---

## Il numero più importante

| Book | Margine di chiusura (mediana) |
|---|---:|
| pinnacle | 2.95% |
| bet365 | ~5.7% |
| **market_max** (miglior prezzo) | **0.59%** [0.26%, 1.19%] |

Facendo shopping del prezzo migliore fra i book, il margine effettivo scende da
**2.95% a 0.59%**. È la differenza fra dover trovare un edge del 3% e uno dello
0.6%.

Non rende l'edge facile. Sposta però la soglia di fattibilità di un fattore
cinque, ed è misurato su 10 campionati-stagione, non ipotizzato.

---

## Difetti trovati da questa validazione

| # | Difetto | Stato |
|---|---|---|
| 1 | L'asimmetria HOME/AWAY non replica | **corretto nella documentazione** |
| 2 | Il baseline presentato come costante globale | **corretto: è per dataset** |
| 3 | Overround mediato **fra book diversi**, mescolando Pinnacle al 2% con bet365 al 5.7% | **corretto: ora per book** |
| 4 | Con Pinnacle presente, bet365/Max/Avg venivano **scartati in silenzio** | **corretto: si ingeriscono tutti** |
| 5 | Nessun controllo sul gap pre-match/chiusura | **aggiunto** |

Il difetto 4 è quello che nascondeva il numero più utile del progetto: senza
i book aggregati, il margine dello 0.59% non era visibile.

---

## Verdetto

La macchina è corretta: lo dimostra l'identità analitica sotto de-vig
moltiplicativo (scarto 6.2e-06) e la coerenza del segno su 10/10 dataset.

Le **conclusioni** tratte da una sola stagione non lo erano. Due su tre sono
state ritirate.

Questa è la ragione per cui la review andava fatta prima di costruirci sopra.
