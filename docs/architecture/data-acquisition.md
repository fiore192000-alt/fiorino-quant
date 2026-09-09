# M6.5 — acquisizione dati

**Stato: 1 di 3 deliverable completato. Gli altri due sono bloccati sull'accesso
di rete, con prove.**

---

## Cosa è raggiungibile da qui

Otto sonde, una risposta:

| host | esito |
|---|---|
| `raw.githubusercontent.com` | **200** |
| `api.football-data.org` | irraggiungibile |
| `api.the-odds-api.com` | irraggiungibile |
| `www.football-data.co.uk` | irraggiungibile |
| `fbref.com` | irraggiungibile |
| `api.sofascore.com` | irraggiungibile |
| `v3.football.api-sports.io` | irraggiungibile |
| `site.api.espn.com` | irraggiungibile |

Solo contenuti statici su GitHub. Nessun feed live, nessuna API.

### E su GitHub non c'è il dato che serve

Due candidati verificati, entrambi inutilizzabili per M6.5:

| repository | ha i timestamp? | è calcio? |
|---|---|---|
| `marcoblume/pinnacle.data` | **sì**, UTC reali da Pinnacle | **no** — MLB 2016 e elezioni USA, in formato R |
| `iredchuk/soccer-bookmaker-odds` | **no** — un valore per partita | sì, 5 leghe 2005-2019 |

Il primo ha esattamente la forma giusta e lo sport sbagliato. Forzare quote di
baseball nel magazzino calcistico richiederebbe di inventare partite, squadre e
competizioni per contenerle: un test verde che non dimostra niente, cioè
precisamente il tipo di cosa che questo progetto esiste per non produrre.

Il secondo ha la stessa forma di Football-Data — quote medie, nessun istante —
quindi non aggiunge nulla a ciò che è già stato validato in M2.

> **Conclusione, basata su prove e non su assunzioni: non esiste una fonte
> raggiungibile di quote timestampate sul calcio, né di formazioni con istante
> di pubblicazione.**

---

## Deliverable 1 — fonte di quote timestampate

**Bloccato.** Nessun host raggiungibile la fornisce.

Non è stato costruito un adapter su fixture. Un adapter validato solo su file
di prova afferma di funzionare senza averlo dimostrato, ed è una decisione già
presa in questo progetto quando si è scelto di validare M2 su storico reale
invece che su fixture.

Il contratto che una fonte deve soddisfare è specificato in
[`next-experiment.md`](next-experiment.md). Con una fonte scelta, l'adapter è
meccanico: `fiorino/data/ingest/sources/` ha già la forma, e lo schema di
destinazione esiste da M2.

## Deliverable 2 — fonte di formazioni timestampate

**Bloccato** per la stessa ragione.

Ciò che è stato costruito è **l'entità**, che è indipendente dalla fonte
(migrazione `0014_lineups.sql`):

```
players          id opaco, come team_id
player_aliases   status PROPOSED|APPROVED|REJECTED
                 CHECK (match_method <> 'FUZZY')      ← regola 9
lineups          published_at NOT NULL, NESSUN DEFAULT
                 lineup_status CONFIRMED | PREDICTED
lineup_slots     STARTER | BENCH | GOALKEEPER
v_analytic_lineups
```

Tre decisioni che meritano di essere motivate:

**`published_at` è `NOT NULL` e non ha default.** È la colonna per cui esiste
l'intera milestone. Ricavarla dal calcio d'inizio meno un'ora fabbricherebbe
esattamente la quantità da misurare — lo stesso errore che M2 ha rifiutato per
le quote, rifiutato di nuovo qui.

**`PREDICTED` non è `CONFIRMED`.** Una formazione probabile è una previsione
*della* formazione: un fatto diverso, con un istante diverso e un contenuto
informativo diverso. `v_analytic_lineups` ammette solo `CONFIRMED`.

**La regola 9 vale di più qui, non di meno.** I nomi dei giocatori collidono
molto più di quelli dei club — iniziali, traslitterazioni, padri e figli, due
omonimi nello stesso campionato. Un giocatore mal identificato produce
un'assenza inattesa fantasma, che si presenterebbe **come segnale**.

## Deliverable 3 — verifica PIT end-to-end ✅

**Completato**: `fiorino/data/quality/pit_chain.py`, 8 controlli, 16 test.

Ogni controllo è esercitato due volte — su dati che lo soddisfano e su dati
costruiti per violarlo. Una guardia che non ha mai scattato è una guardia che
nessuno ha testato.

### La correzione all'ordinamento

La specifica diceva:

```
decision_time < formation_time < kickoff < settlement_time
```

Questo è corretto per una strategia che **non** legge le formazioni — e vieta
esattamente quella per cui esiste la milestone. Se la decisione precede la
pubblicazione, la formazione non può averla informata.

L'invariante generale, che è quella implementata:

> **ogni fatto usato da una decisione precede quella decisione.**

Ne discendono due ordinamenti ammissibili:

```
  cieca alle formazioni   decision < published_at < kickoff     (formazione inutilizzata)
  informata               published_at <= decision < kickoff    (formazione usata)
```

L'audit verifica il secondo solo per le decisioni che dichiarano una formazione
fra i propri input. Cablare l'ordinamento della specifica avrebbe reso
l'esperimento impossibile da eseguire **e l'audit avrebbe detto che andava
tutto bene.**

### I controlli

| controllo | severità | cosa cattura |
|---|---|---|
| `decision_after_kickoff` | BLOCKING | scommessa piazzata al proprio calcio d'inizio o dopo |
| `settlement_before_kickoff` | BLOCKING | risultato regolato prima dell'inizio |
| `price_after_decision` | BLOCKING | prezzo catturato dopo la scommessa che lo usa |
| `fit_after_decision` | BLOCKING | modello addestrato dopo la scommessa che informa |
| `weight_trained_past_boundary` | BLOCKING | l'audit M6, ripiegato nella catena |
| `lineup_published_after_kickoff` | WARNING | formazione retro-inserita: non può informare nulla |
| `bet_used_unpublished_lineup` | BLOCKING | scommessa che dichiara una formazione più recente di sé |
| `no_timestamped_odds` / `no_lineups` | WARNING | **la copertura è dichiarata, non assunta** |

L'ultima riga è la più importante oggi. Senza una riga `TIMESTAMPED`, i
controlli sui prezzi sono soddisfatti **a vuoto**. Un audit che risponde «tutto
pulito» su un insieme vuoto è l'output più pericoloso che questo modulo possa
produrre, quindi lo dice ad alta voce:

```
WARNING  no_timestamped_odds: 0 of N odds observations are TIMESTAMPED:
         the price-before-decision link is untested, not proven
```

---

## Un difetto trovato scrivendo i test

La prima versione di `v_analytic_lineups` escludeva le formazioni contenenti un
giocatore senza riga in `players`. Un test ha dimostrato quella guardia
**irraggiungibile**: la foreign key su `lineup_slots` rende già impossibile
inserire una riga simile.

Il rischio reale è quello che M1 aveva trovato per le squadre — un giocatore che
**esiste** ma il cui alias non è stato giudicato, che è il modo in cui una
collisione di nomi entra nel dataset indossando un id valido. La vista ora
rispecchia `v_analytic_matches` ed esclude le formazioni con un alias non
`APPROVED`.

Codice morto in una guardia di sicurezza è peggio di nessuna guardia: dà la
stessa rassicurazione senza la protezione.

---

## Dove sta davvero il vincolo

```
schema quote timestampate       ✅ M2, mai esercitato
lettore PIT timestampato        ✅ M2, mai esercitato
schema formazioni + identità    ✅ M6.5
audit catena PIT end-to-end     ✅ M6.5
ablation, bootstrap, gate       ✅ M6
CLV, backtest, settlement       ✅ M3, M4
────────────────────────────────────────────
dati timestampati                 ✗
```

Il motore è costruito e verificabile. Manca il carburante, e non è un problema
di modellazione: è **trovare, ottenere e conservare** dati timestampati di
qualità sufficiente.

La prossima azione non è una riga di codice. È la decisione su **quale fonte** e
**con quale accesso** — e richiede un ambiente con una policy di egress diversa
da questo.
