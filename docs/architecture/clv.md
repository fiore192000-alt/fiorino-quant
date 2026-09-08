# CLV — il segnale primario (M3)

M3 misura. Non dimensiona, non seleziona, non regola: niente staking, niente
strategie, niente bankroll. Quelli sono M4 e M7.

---

## Perché è la priorità

Il CLV converge sulla verità in **centinaia** di scommesse; il P&L ne richiede
**migliaia**. Una strategia con CLV negativo e P&L positivo è fortunata, e
saperlo in anticipo vale più del P&L stesso.

Tre numeri, tutti misurati contro la chiusura **de-viggata del book di
riferimento** — mai contro il book con cui si è scommesso, perché confrontare
un book soft con se stesso non misura nulla.

```
clv_price = price_taken / closing_price - 1
clv_ev    = closing_fair_prob * price_taken - 1     ← il numero di riferimento
clv_log   = ln(closing_fair_prob * price_taken)     ← additivo fra scommesse
```

`clv_ev` è sulla stessa scala dello yield, quindi «CLV +2%, yield −1%» è
un'affermazione leggibile sulla fortuna anziché due grandezze incomparabili.

---

## Il calibration check

La verifica che **dimostra** la catena invece di limitarsi a esercitarla.

Prendendo il prezzo di chiusura stesso, sotto de-vig moltiplicativo vale
`fair_i = (1/price_i)/S`, quindi `fair × price = 1/S` per ogni selezione e

```
CLV_ev  ==  1/(1 + overround) - 1  ==  -overround / (1 + overround)
```

un numero **noto in anticipo**. Misurato sulla Premier League 2017-18 reale:

| De-vig | CLV_ev medio | −ov/(1+ov) | Scarto |
|---|---:|---:|---:|
| Moltiplicativo | −0.02066376 | −0.02066992 | **6.2e-06** |
| Shin | −0.02879403 | −0.02066992 | 8.1e-03 |

Il moltiplicativo riproduce la forma chiusa a livello di arrotondamento: la
macchina è corretta.

**Shin devia per costruzione**, e la deviazione non è rumore. Shin ridistribuisce
il margine, quindi `fair × price` non è costante:

| Selezione | `fair × price` |
|---|---:|
| HOME | 0.9781 |
| DRAW | 0.9706 |
| AWAY | 0.9648 |

> La scelta del metodo di de-vig sposta il CLV di **~80 bps**, in modo
> asimmetrico fra selezioni — più di molti edge dichiarati. Per questo il
> metodo è memorizzato per riga anziché assunto.

---

## Il baseline che ogni modello dovrà battere

Prendere ogni prezzo pre-match, senza discriminare, su 918 scommesse reali:

| Metrica | Valore |
|---|---:|
| CLV_ev medio | **−0.02799** |
| t-stat | **−10.66** |
| Beat-close rate | 0.489 |
| Drift medio del prezzo | +0.0007 |

Chi scommette tutto perde il margine, e la perdita è statisticamente
inequivocabile. Il drift medio quasi nullo dice che il mercato non è
sistematicamente generoso.

> **Ritirato.** Su questa stagione i prezzi casa mostravano un drift medio di
> −0.0043 e quelli trasferta di +0.0045, e l'avevo descritto come un effetto
> reale di mercato. **La validazione fuori campione su 10 campionati-stagione
> lo ha falsificato:** il drift trasferta è positivo in 4 casi su 10, e le
> medie dei due lati sono praticamente identiche (−0.0098 e −0.0105), non
> opposte. Era un artefatto di una singola stagione.
> Vedi `docs/validation/validation-report.md`.

---

## Rifiutare di rispondere fa parte del rispondere

Tre esclusioni, tutte contate e mai scartate in silenzio:

| Motivo | Quando |
|---|---|
| `no_reference_close` | il book di riferimento non ha prezzato quella partita |
| `line_not_matched` | ha prezzato una linea **diversa** |
| `no_fair_probability` | la chiusura esiste ma il mercato era incompleto |

Confrontare contro una linea diversa non è una misura più debole: è una misura
**sbagliata**. `v_clv_coverage` riporta quanta parte del ledger si è potuta
davvero valutare — un CLV calcolato sul sottoinsieme che per caso aveva una
chiusura non è un campione casuale.

---

## L'onestà sui timestamp, portata nel ledger

Una scommessa presa a un prezzo `PREMATCH` eredita l'ignoranza di quel prezzo:
sappiamo che era disponibile prima del kickoff, e nulla più. `placed_at` è
quindi `NULL`, imposto dallo schema:

```sql
CHECK ((price_precision = 'TIMESTAMPED') = (placed_at IS NOT NULL))
```

Verificato: **nessuna scommessa replayed porta un orologio inventato**.

---

## Cosa manca per un CLV che significhi qualcosa

Gli strumenti di replay non sono strategie: servono a validare la macchina e a
fissare il baseline. Un CLV **positivo e significativo** richiede un modello
che selezioni, ed è M5. M4 costruisce il backtest che lo renderà credibile.
