# Il layer modelli e il pricing multi-mercato (M5)

M5 è il primo pezzo del sistema che ha un'opinione. M1–M4 costruiscono
misurazione: identità, mercato, CLV, motore. Qui entra una previsione, e con
essa l'unica domanda che conta davvero — **la previsione batte la chiusura?**

La risposta, misurata, è **no**. Il documento spiega com'è costruito il layer e
perché quel «no» è il risultato più utile che potesse produrre.

---

## penaltyblog come dipendenza, non come core

L'adapter è deliberatamente sottile: `PenaltyblogModel` prende risultati
regolati, restituisce coefficienti di attacco/difesa e un `rho`, e lì finisce.
Tutto ciò che il sistema fa con quei numeri — griglia, mercati, EV, staking,
CLV — è codice di Fiorino.

Questo confine non è ideologico, è operativo. Se ne è avuta la prova durante
M5:

> `model.predict()` di penaltyblog solleva **«goal_matrix contains negative
> probabilities»** quando il `rho` stimato cade fuori dai limiti imposti dalle
> lambda. L'ottimizzatore della libreria non impone quei limiti; il correttivo
> Dixon-Coles li richiede.

Con la libreria al centro, l'unica risposta sarebbe stata aspettare una patch
upstream. Con la libreria come dipendenza, l'adapter ricade sui parametri
grezzi e ricostruisce la griglia in casa:

```
lambda_home = exp(attack_home + defence_away + hfa)
lambda_away = exp(attack_away + defence_home)
```

e `score_grid` **satura** il rho dentro
`[max(-1/λh, -1/λa), min(1, 1/(λh·λa))]` invece di emettere una distribuzione
che non è una distribuzione. Il fallback è contato (`fallback_count`) e finito
nei `params` del `model_run`: silenziare l'incidente non è la stessa cosa che
gestirlo.

Una seconda trappola della stessa libreria, normalizzata in un solo punto:
`model.predict(max_goals=15)` restituisce una griglia 15×15 (gol 0..14),
`create_dixon_coles_grid(max_goals=15)` una 16×16 (gol 0..15). `MAX_GOALS`
fissa la convenzione una volta sola, così nessun consumatore deve sapere quale
delle due ha in mano.

---

## Una griglia, tutti i mercati

```
              ┌──────────────┐
  λh, λa, ρ → │  score_grid  │ → P(i,j) per i,j in 0..15, normalizzata
              └──────┬───────┘
                     │
      ┌──────────────┼──────────────┐
      ▼              ▼              ▼
    1X2         handicap        totals
                asiatici       (over/under)
      └──────────────┴──────────────┘
                     │
              55 selezioni per fixture,
              tutte con le CINQUE probabilità
              di regolamento
```

La coerenza fra mercati non è una proprietà da testare a valle: è vera **per
costruzione**, perché ogni mercato è una proiezione della stessa matrice. Un
modello che quota separatamente 1X2 e Over/Under può essere arbitrato contro se
stesso; questo no.

Il test resta comunque, perché la costruzione può rompersi:
`OVER + UNDER = 1` su ogni linea a mezzo gol, `HOME + DRAW + AWAY = 1` su ogni
fixture, e le cinque probabilità sommano a uno su **ogni** riga.

### Perché cinque probabilità e non una

Un handicap intero fa push, un quarto di linea si divide a metà. La riga di
predizione porta quindi `prob_win`, `prob_half_win`, `prob_push`,
`prob_half_lose`, `prob_lose`, e l'EV le usa tutte:

```
EV = p_win·(q−1) + p_half_win·(q−1)/2 + p_push·0 − p_half_lose·0.5 − p_lose
```

Comprimere questo in un `prob_win` booleano — la tentazione naturale, e quella
che l'utente aveva chiesto esplicitamente di non prendere — non sbaglia lo
stake di Kelly, ma **sottostima l'EV esattamente di `p_push`**. Su una linea
0.0 con `p_push` intorno al 25% non è un dettaglio.

### Perché la scala di linee è una scelta

Quotare ogni quarto di linea da −3 a +3 produce migliaia di righe per fixture,
quasi tutte per linee che nessun book offre. `DEFAULT_HANDICAPS` e
`DEFAULT_TOTALS` coprono ciò che Football-Data pubblica. Ampliare la scala è
una riga di configurazione; farlo senza un book che quoti quelle linee è
generare dati che non si possono né validare né giocare.

---

## Walk-forward: dove la regola R1 lavora davvero

Fino a M4 la disciplina point-in-time proteggeva da errori di misura. Qui
protegge dall'unico errore che rende un backtest completamente privo di senso:
addestrare su partite che si stanno quotando.

```
  as_of = t
      │
      ├── fit   ← PointInTimeView.at(t).results()      solo REGOLATE prima di t
      │
      └── price ← PointInTimeView.at(t).upcoming()     solo NON ancora giocate
                  entro t + 8 giorni

  t += 7 giorni, si ripete
```

Il passo settimanale è un compromesso esplicito: rifittare a ogni partita è
corretto e lento, a ogni stagione è veloce e stantio. Una settimana è la
cadenza con cui un campionato si aggiorna davvero — un turno.

Orizzonte 8 giorni e passo 7 si **sovrappongono di proposito**: un turno
rinviato resta coperto. La conseguenza è che una fixture è quotata da due fit
diversi, e il primo tentativo di join ha prodotto candidati duplicati e una
collisione di chiave primaria. La correzione non è una `DISTINCT`: la strategia
prende il **fit più fresco il cui confine precede la decisione**, che è insieme
la semantica corretta e la deduplicazione.

```sql
row_number() OVER (PARTITION BY match_id, bookmaker_id, market_type, line, selection
                   ORDER BY r.trained_through DESC, v.model_run_id)
...
WHERE r.trained_through <= view.as_of     -- R1, dove conta di più
```

L'invariante corrispondente è verificato su tutti i dataset di validazione:
**nessuna predizione ha un `trained_through` pari o successivo al kickoff della
partita che quota.** Zero violazioni non è un risultato statistico, è la
condizione perché tutto il resto significhi qualcosa.

### Squadre mai viste

A inizio stagione (e a ogni neopromossa) il fit non ha coefficienti. Il modello
ricade su un prior di lega e **marca la riga** con `used_prior`. `ModelEdge`
per default non scommette quelle righe: sono previsioni oneste ma deboli, e
scommetterle significa puntare più forte proprio dove il modello sa meno.

---

## Il confronto che decide tutto

Il modello viene misurato contro la **chiusura di riferimento de-viggata**, non
contro la propria log-likelihood. Una log-likelihood alta dice che il modello
descrive bene i risultati passati; solo il confronto con la chiusura dice se
sa qualcosa che il mercato non sa.

`v_model_calibration` mette i due fianco a fianco su Brier e log-loss. Il
numero riportato nel report di validazione usa il fit più fresco per
(match, selection) — lo stesso che la strategia scommetterebbe — perché la
vista, raggruppando per `model_run_id`, conta due volte le fixture coperte da
due orizzonti.

### Il `edge_ev` alto non è una misura di edge

`edge_ev` misura **disaccordo** fra modello e book, e il disaccordo ha due
cause possibili: il modello sa qualcosa, oppure il modello sbaglia. Il numero da
solo non distingue i due casi, ed è per questo che non decide nulla.

Avevo previsto che la distinzione emergesse dalla monotonia: un edge vero
migliora alzando la soglia (la soglia seleziona), una miscalibrazione peggiora
(la soglia seleziona le fixture sbagliate più forte). **La validazione non lo
conferma.** Alzando la soglia da 5% a 30% lo yield decresce in 4 dataset su 10,
e il CLV pure in 4 su 10; solo le medie aggregate sono monotone
(CLV −0.0439 → −0.0470 → −0.0474). Su un singolo campionato-stagione lo yield
è troppo rumoroso perché la firma sia leggibile, ed è la stessa lezione di M4 —
lo yield sbaglia, il CLV no — che si ripresenta un livello più su.

Quello che distingue davvero i due casi resta il confronto diretto con la
chiusura: Brier e log-loss contro `closing_fair_prob`. Lì la risposta non è
rumorosa, è **10 dataset su 10**.

---

## Risultati

Vedi [`docs/validation/model-validation.md`](../validation/model-validation.md).
