# Efficienza per campionato — misurata, non cercata

```
python scripts/scan_league_efficiency.py --json docs/validation/league-efficiency.json
```

Test dell'ipotesi registrata **C-106**, «nei campionati minori nascono gli
edge». La domanda posta non è *dov'è il vantaggio* ma **dove la chiusura segue
peggio la realtà**. Un mercato mal calibrato può restare imbattibile; un
mercato ben calibrato non è battibile da nessuno, e conviene saperlo prima di
spendere una stagione a raccogliere dati.

---

## Il risultato

| | Brier | scarto calibr. | peggior banda | margine | guadagno pre→close |
|---|---|---|---|---|---|
| ITA_SA 2019-20 | 0.18858 | **0.0234** | 0.0454 | 0.0319 | +0.00098 |
| DEU_BL1 2024-25 | 0.19684 | 0.0218 | 0.0750 | 0.0303 | +0.00043 |
| ENG_PL 2018-19 | 0.17341 | 0.0186 | 0.0903 | 0.0235 | +0.00030 |
| PRT_L1 2024-25 | 0.18240 | 0.0168 | 0.0965 | 0.0362 | +0.00169 |
| ENG_PL 2017-18 | 0.18568 | 0.0162 | 0.0329 | 0.0211 | +0.00083 |
| ENG_PL 2019-20 | 0.19154 | 0.0135 | 0.0363 | 0.0286 | +0.00007 |
| NLD_ED 2024-25 | 0.18542 | 0.0131 | 0.0316 | 0.0366 | +0.00230 |
| FRA_L1 2024-25 | 0.18798 | 0.0130 | 0.0445 | 0.0304 | +0.00077 |
| ENG_PL 2020-21 | 0.19748 | 0.0115 | 0.0890 | 0.0239 | +0.00190 |
| ESP_LL 2019-20 | 0.19470 | **0.0114** | 0.0493 | 0.0313 | n/d |

**Questa classifica non va usata.**

```
  dispersione del Brier fra campionati        0.02407
  ampiezza media del CI dentro un campionato  0.02507
```

> **La differenza fra campionati è più piccola dell'incertezza dentro un
> singolo campionato.** La tabella sopra è un ordinamento del rumore: con
> questo campione nessuna di queste leghe è distinguibile dalle altre.

Serie A appare in cima e La Liga in fondo, ma l'intervallo di confidenza di
ciascuna contiene comodamente l'altra. Presentare la prima riga come «il
campionato meno efficiente» sarebbe esattamente l'errore che questo laboratorio
ha già commesso una volta, con l'asimmetria HOME/AWAY che sembrava solida su una
stagione e non ha replicato.

---

## Cosa questa misura dice davvero

**Sui campionati maggiori:** sono indistinguibili fra loro per calibrazione
della chiusura. Non c'è un membro debole del gruppo da cui partire.

**Sul margine:** varia da **2.1%** (ENG_PL 2017-18) a **3.7%** (NLD_ED
2024-25) — quasi il doppio. Il margine è misurabile con precisione molto
maggiore della calibrazione, ed è l'unica dimensione su cui i campionati si
separano chiaramente. Ma un margine più alto è un **costo** più alto, non un
mercato più sbagliato: rende quel campionato più difficile da battere, non più
facile.

**Sul guadagno prematch→chiusura:** positivo in 9 casi su 9 misurabili, sempre
minuscolo — da +0.00007 a +0.00230 di Brier. Coerente con il tetto già misurato
per l'intero canale dei movimenti di quota.

---

## Cosa NON dice, ed è la parte importante

Sono **dieci stagioni di sette prime divisioni**. Serie C, settore giovanile,
calcio femminile e campionati scandinavi **non ci sono**, e sono esattamente i
mercati di cui parla C-106.

Quindi:

* L'ipotesi **non è confutata**. È delimitata.
* Se le prime divisioni si fossero separate nettamente fra loro, l'ipotesi
  avrebbe avuto un meccanismo visibile e un punto di partenza. Non si separano.
* Resta interamente possibile che un campionato minore sia molto meno
  efficiente. Semplicemente **nessun dato di questo progetto lo riguarda**.

C-106 resta `UNTESTED`, con la prossima azione invariata: acquisire quote per
almeno un campionato minore e ripetere questa stessa misura. Non cercare edge —
misurare calibrazione.

> **Aggiornamento, settembre 2026.** I dati sono arrivati e la misura è stata
> rifatta su 38 divisioni, comprese le serie inferiori che qui mancavano:
> [efficienza fra divisioni](division-efficiency.md). C-106 è ora
> `TESTED_BUT_LIMITED`. La risposta è più interessante di un sì o di un no —
> il mercato è meno affilato nelle serie inferiori (6 paesi su 6) ma non più
> scalibrato, e il margine sale insieme all'ignoranza del book. Questa pagina
> resta come la misura sulle sole prime divisioni, che è ancora corretta per
> ciò che copre.

---

## Una nota sul metodo

Lo scarto di calibrazione è la differenza media, pesata per numerosità, fra
prezzo e frequenza realizzata per banda. Le bande con meno di 30 selezioni sono
escluse: una banda da nove osservazioni produce uno scarto grande per costruzione
e dominerebbe la media.

La colonna «peggior banda» è riportata accanto alla media proprio perché le due
divergono: PRT_L1 ha lo scarto medio quinto ma la peggior banda più alta di
tutte (0.0965). Un mercato può essere ben calibrato quasi ovunque e sbagliare
in una zona di prezzo — che è una cosa diversa, e più interessante, di essere
mal calibrato ovunque. Con questi campioni per banda, però, anche quel numero è
rumoroso.
