# Piano di acquisizione dati

**Il codice è congelato. Il dato no.**

Per almeno 30 giorni: nessun modello nuovo, nessuno score nuovo, nessuna pagina
nuova, nessun backtest nuovo. Il valore marginale del codice è ormai basso; il
valore marginale del dato è alto.

Questo documento è l'unico posto da cui ripartire.

---

## Perché il congelamento è la scelta giusta

Le ultime misure hanno prodotto risultati **negativi e utili**, ognuno dei quali
elimina una direzione:

| misura | conseguenza |
|---|---|
| il mercato batte il modello 10/10 | non serve un modello migliore di quel tipo |
| `MARKET + MODEL` non batte `MARKET` | non serve mescolarlo meglio |
| 0/14 situazioni sopravvivono | non serve cercarne altre nel calendario |
| **dispersione fra campionati < incertezza dentro un campionato** | non c'è una lega top da cui partire |
| il canale movimenti vale 0.00099 Brier | non c'è un tesoro nella microstruttura misurabile oggi |

L'ultima riga merita di essere ripetuta: **non abbiamo alcuna evidenza che una
lega sia più battibile di un'altra.** Abbiamo una classifica numerica, non una
differenza statistica. Sono cose diverse, e confonderle costerebbe mesi.

Tutto ciò che resta non dimostrato richiede **dati che non abbiamo**.

---

## Stato delle fonti

Vocabolario di acquisizione, derivato dallo stato tecnico in
[`SOURCES.json`](SOURCES.json) più l'accessibilità:

| stato | significa | azione |
|---|---|---|
| `READY` | usabile adesso, per ciò che fa | già in uso |
| `PARTIAL` | accessibile, ma priva di una proprietà necessaria | nessuna |
| `BLOCKED` | ha le proprietà, non è raggiungibile da qui | **acquisire fuori** |
| `UNVERIFIED` | plausibile, campi o termini non ispezionati | **verificare** |
| `UNKNOWN` | non valutata | valutare |

| Fonte | Costo | Licenza | Copertura | Timestamp | Bookmaker | Stato |
|---|---|---|---|---|---|---|
| **openfootball** | gratis | public domain | 1888→2026-27, fixture future | n/a | — | **`READY`** |
| **Football-Data** (mirror) | gratis | uso personale; mirror senza licenza | 1993→oggi, 8 leghe | **nessuno** | sì | **`PARTIAL`** |
| **BeatTheBookie — dump SQL** | gratis | GPL-3.0 sul codice; dati a corredo del paper | 2005-2016, ~113.860 partite | **assoluto per osservazione** | **32, per nome** | **`BLOCKED`** |
| BeatTheBookie — export `.txt` | gratis | idem | idem | griglia oraria, relativa | anonimo | **`PARTIAL`** |
| **OddsPortal** (via OddsHarvester) | strumento gratis | MIT lo strumento; **termini dei dati non letti** | 100+ campionati, 7 mercati | **non verificato** | sì | **`UNVERIFIED`** |
| Betfair Historical | piano Basic gratis | **termini non letti** | 2015→oggi | dichiarato al ms, **non verificato** | exchange | **`UNVERIFIED`** |
| the-odds-api | free tier a quota | **termini non letti** | ignota nel free tier | non verificato | sì | **`UNVERIFIED`** |
| statsbomb/open-data | gratis | licenza propria | molte competizioni | **nessuno** (referto post-partita) | — | **`PARTIAL`** |
| iredchuk/soccer-odds | gratis | non dichiarata | 2005-2019, 5 leghe | nessuno | **no**, media fra book | **`PARTIAL`** |
| marcoblume/pinnacle.data | gratis | CRAN | MLB 2016 | assoluto | sì | **`PARTIAL`** (non è calcio) |
| Formazioni con istante di pubblicazione | — | — | — | — | — | **nessuna fonte esiste** |

**Una sola fonte è PIT-usabile** (`beatthebookie-sql`) e non è raggiungibile da
qui. Un test lo asserisce, così aggiungerne una seconda diventa un atto
deliberato con evidenza.

---

## Fase A — le tre azioni fuori da questo ambiente

Nessuna richiede codice. Tutte richiedono una decisione o un accesso.

### A1 — Sbloccare BeatTheBookie · **priorità massima, sforzo minimo**

L'unica fonte verificata come PIT-usabile. Due modi:

* mettere `dropbox.com` **o** `drive.google.com` nell'allowlist di egress
  dell'ambiente, oppure
* scaricare il dump altrove e portarlo dentro.

Da verificare **appena accessibile**, prima di costruirci sopra:

* la granularità reale delle osservazioni in `odds_history_series` (il `.txt`
  ricampiona a un'ora, il dump no — ma **quanto è fitto davvero?**);
* la copertura per campionato: 113.860 partite su 658 leghe sono in media 170
  partite per lega, quindi la distribuzione conta più del totale;
* la mappatura squadre verso il nostro risolutore di identità.

L'adapter e le viste esistono già. Con il dump in mano l'ingestione è un comando.

**Limite noto:** le serie si fermano al 2016. Servono per studiare la
microstruttura storica, **non** per alimentare un terminale live.

### A2 — Leggere i termini di OddsPortal e Betfair · **sforzo basso**

Entrambe sono `UNVERIFIED` per due ragioni indipendenti: campi non ispezionati
**e** termini non letti. La seconda non sparisce verificando la prima, e non è
una domanda tecnica.

OddsPortal ha la copertura più ampia trovata — 100+ campionati, sette mercati,
e un flag `--odds-history` documentato come movimento per partita. Se i termini
lo consentono e i campi portano istanti assoluti, è la fonte migliore in
assoluto. Due «se», nessuno dei quali risolvibile da qui.

### A3 — Decidere la fonte per le formazioni · **il vero collo di bottiglia**

**Non esiste alcuna fonte pubblica**, gratuita o a pagamento, che archivi
l'istante di pubblicazione di una formazione. È un fatto effimero che nessuno
conserva.

Quindi non è un problema di ricerca: è una decisione su **quale fonte
interrogare ogni giorno**, e va presa prima di poter iniziare.

---

## Fase B — Lineup Dataset v1

Il primo dataset proprietario. Non enorme, non perfetto, solo **esistente**.

Lo schema c'è già (migrazione `0014_lineups.sql`) e rifiuta da solo i dati
inutilizzabili:

```sql
published_at   TIMESTAMPTZ NOT NULL     -- nessun DEFAULT: non ricavabile dal kickoff
lineup_status  VARCHAR NOT NULL         -- CONFIRMED != PREDICTED
CHECK (match_method <> 'FUZZY')         -- regola 9, sui giocatori
```

Cosa raccogliere, per partita:

| campo | perché |
|---|---|
| `published_at` | **la ragione per cui il dataset esiste** |
| `retrieved_at` | quando *noi* l'abbiamo visto: la differenza è la nostra latenza |
| formazione **prevista** | il riferimento contro cui misurare la sorpresa |
| formazione **ufficiale** | l'evento |
| panchina, portiere | le categorie dell'event study |
| identificatore giocatore della fonte | per il risolutore, mai il nome come chiave |

### Quanto serve, misurato e non stimato

| domanda | eventi necessari | partite | tempo |
|---|---|---|---|
| **aggregata** — «il mercato si muove dopo le formazioni più che in una finestra di controllo?» | ~125 per gruppo | **~250** | **meno di una stagione, un campionato** |
| **per categoria** — portiere, attaccante, 3+ assenze | ~31 per categoria | **600–1.000** | **due campionati in parallelo, una stagione** |

La domanda aggregata è quella che decide se continuare, ed è la più economica.
Se non c'è effetto lì, non c'è niente da ripartire e si sono risparmiati mesi.

**Ma senza quote timestampate il dataset formazioni da solo non risponde a
nulla.** Servono entrambi. A1 e A3 sono paralleli, non sequenziali.

---

## Fase C — Market Observatory reale

Le viste esistono e sono vuote: `v_market_path`, `v_market_moves`,
`v_market_summary`, `v_market_breadth`, `v_path_coverage`.

Diventano utili alla **prima riga** con `fixture, timestamp, bookmaker, price`.
Prima no, e costruirci sopra adesso significherebbe simulare — che è la cosa che
questo progetto non fa.

---

## Come allocare il prossimo mese

| attività | ore |
|---|---|
| nuovi modelli | **0** |
| nuove dashboard | **0** |
| nuovi backtest | **0** |
| ricerca e sblocco fonti (A1, A2) | 20 |
| pipeline formazioni (A3, B) | 40 |
| pipeline quote timestampate (C) | 40 |

---

## La domanda che sostituisce tutte le altre

Non:

> «Come prevediamo meglio una partita?»

Ma:

> **«Quale informazione osservabile oggi non è ancora incorporata nel prezzo
> quando viene pubblicata?»**

Il laboratorio è costruito per rispondere. Gli manca solo di poter guardare.
