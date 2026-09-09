# Gate di promozione

Sei cancelli, in quest'ordine. **Il P&L è l'ultimo, non il primo.**

Un candidato che salta un gate non è «quasi pronto»: è fermo a quel gate.

---

```
   IPOTESI REGISTRATA
          │
   ┌──────▼──────┐
   │  GATE 1     │  POINT-IN-TIME
   │             │  zero leakage, pesi e parametri inclusi
   └──────┬──────┘
   ┌──────▼──────┐
   │  GATE 2     │  CALIBRAZIONE
   │             │  Brier, LogLoss, RPS, curva di affidabilità
   └──────┬──────┘
   ┌──────▼──────┐
   │  GATE 3     │  INFORMAZIONE INCREMENTALE
   │             │  market + X batte market, CI che esclude lo zero
   └──────┬──────┘
   ┌──────▼──────┐
   │  GATE 4     │  CLV
   │             │  positivo fuori campione, non per costruzione
   └──────┬──────┘
   ┌──────▼──────┐
   │  GATE 5     │  ROBUSTEZZA E ATTACCO
   │             │  replica, e sopravvive al tentativo di ucciderlo
   └──────┬──────┘
   ┌──────▼──────┐
   │  GATE 6     │  SOLO ADESSO: yield, drawdown, staking
   └──────┬──────┘
          ▼
     PAPER TRADING
```

---

## Gate 1 — Point-in-time

**Passa se:** `run_pit_chain_audit()` non restituisce nulla di `BLOCKING`, e
ogni parametro stimato dagli esiti dichiara il confine su cui è stato stimato.

Il peso dell'ensemble in M6 è stato l'unico parametro stimato dagli esiti di
tutto il milestone, ed è arrivato «da una porta che nessuno stava guardando»:
la disciplina PIT sorvegliava le previsioni, non i pesi.

**Non passa se:** l'audit riporta copertura vuota. Un audit che risponde «tutto
pulito» su un insieme vuoto è l'output più pericoloso del sistema.

## Gate 2 — Calibrazione

**Passa se:** Brier, LogLoss e RPS sono riportati **tutti e tre**, con la curva
di affidabilità per banda di prezzo.

Non `accuracy`. Per scommettere serve una probabilità buona, non il vincitore
più frequente.

**Riferimento misurato:** il prezzo Pinnacle de-viggato segue la frequenza
realizzata in ogni banda dal 3% all'85%, scostamento massimo |z| = 1,38.
Quello è il metro.

## Gate 3 — Informazione incrementale

**Passa se:** `MARKET + CANDIDATE` batte `MARKET` con un **intervallo di
confidenza bootstrap appaiato che esclude lo zero**, e il confronto è appaiato
sulle stesse partite.

**Non passa se** il CI contiene lo zero, per quanto favorevole sia la stima
puntuale. In M6 tutti e 20 gli intervalli contenevano lo zero e 18 stime su 20
erano dalla parte sbagliata: il gate ha funzionato.

**Attenzione al peso.** Un peso non nullo stimato sul training **non è** un
risultato: in tre dataset l'ottimizzatore ha trovato 17–21% e fuori campione non
ha prodotto nulla. Il guadagno in-sample è garantito non negativo, perché
`w = 0` è sempre ammissibile.

## Gate 4 — CLV

**Passa se:** il CLV medio è positivo fuori campione con t-stat riportato,
**e non è definizionale**.

Questa è la trappola centrale del progetto e si è presentata due volte:

1. Una previsione costruita **sulla chiusura** ha CLV positivo per costruzione —
   è l'oracolo chiaroveggente di M4 sotto altro nome.
2. In forma attenuata: l'arm `MARKET` di M6 mostrava CLV **+0,0234**, positivo
   in 7 dataset su 8. Decomposto: +0,0463 era vero **al momento della
   scommessa per costruzione**, e la deriva reale valeva **−0,0017**.

**Obbligo:** ogni CLV positivo va decomposto in
`edge_alla_scommessa + deriva_reale`. Se la parte definizionale spiega il
risultato, l'esito è **NO EVIDENCE**.

## Gate 5 — Robustezza, e il tentativo di uccidere

**Replica:** almeno 2 campionati e 2 periodi indipendenti.

**E poi si attacca.** Chi trova un edge ha l'onere di provare a distruggerlo:

* un altro book di riferimento
* un altro metodo di de-vig (Shin ↔ moltiplicativo)
* togliendo una stagione
* togliendo un campionato
* togliendo la squadra che contribuisce di più
* togliendo il 5% di outlier
* per banda di prezzo
* con una finestra di controllo alternativa
* con un **evento placebo** a un istante casuale
* stabilità temporale: il segno regge in ogni sotto-periodo?

Un edge che scompare togliendo una squadra non è un edge.

## Gate 6 — Solo adesso: economia

Yield, ROI, drawdown, turnover, numero di scommesse, CI bootstrap, ripartizione
per stagione e per campionato.

**Non si promuove nulla sul ROI isolato.** Nella validazione M4 il CLV era
corretto 30 volte su 30 e lo yield 23 su 30.

---

## Perché M7 è rinviata

Kelly su nessun edge è nessun edge, e spesso peggio: dimensionare un segnale
inesistente converte una perdita lenta in una veloce.

Il kernel matematico di Kelly resta nel repository come codice testato. Non deve
trasformare un edge non validato in una raccomandazione di puntata.

**M7 si apre quando un candidato ha superato tutti e sei i gate e ha una storia
di paper trading.** Non prima.
