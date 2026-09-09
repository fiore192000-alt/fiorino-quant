# M6.5 — acquisizione dati

**Stato: 2 deliverable completati (audit PIT, event study). L'acquisizione
delle due fonti resta bloccata sull'accesso di rete, con prove — ma una delle
due è a una regola di allowlist di distanza.**

---

## La superficie raggiungibile

Venti sonde. Raggiungibili solo tre famiglie di host:

| raggiungibile | bloccato |
|---|---|
| `raw.githubusercontent.com`, `github.com`, `objects.githubusercontent.com` | `football-data.co.uk`, `fbref.com`, `api.football-data.org` |
| `gitlab.com` | `api.the-odds-api.com`, `api-sports.io`, `api.sofascore.com`, ESPN |
| `pypi.org` | `kaggle.com`, `huggingface.co`, `zenodo.org`, `figshare.com`, `arxiv.org` |
| | **`dropbox.com`**, **`drive.google.com`**, `historicdata.betfair.com`, `data.world` |

Il blocco vale anche per `WebFetch`, non solo per `curl`: è la policy di egress
dell'ambiente, non un dettaglio del client.

## Il dato giusto esiste, ed è a una regola di distanza

Questa è la scoperta più azionabile della ricerca.

**`Lisandro79/BeatTheBookie`** — il dataset del paper di Kaunitz, Zhong e
Kreiner, *«Beating the bookies with their own numbers»* (arXiv:1710.02824) —
contiene esattamente ciò che manca:

> **serie continue di quote con i movimenti**, per **31.074 partite** da
> settembre 2015 a marzo 2016 su 553 campionati, più **82.786 partite** da marzo
> a novembre 2016 su 658 campionati. Circa **113.860 partite** con la storia del
> prezzo, non due punti.

Il repository GitHub è raggiungibile e contiene il codice. **I dati no**: sono
ospitati su Dropbox e Google Drive, entrambi bloccati. Il clone (15 MB) porta
solo lo script di export SQL.

> **Se `dropbox.com` o `drive.google.com` entrassero nell'allowlist, il
> Deliverable 1 si sbloccherebbe immediatamente** — con un ordine di grandezza
> più partite di quante ne servano.

Resta da verificare, una volta accessibile, con quale granularità temporale le
serie sono campionate e se gli istanti sono assoluti o relativi al kickoff. Il
paper parla di serie continue; la forma esatta va guardata prima di
promettere qualcosa.

### Le altre fonti esaminate

| fonte | timestamp? | calcio? | verdetto |
|---|---|---|---|
| `Lisandro79/BeatTheBookie` | **sì**, serie continue | **sì**, 113k partite | **dati su Dropbox/Drive, bloccati** |
| `marcoblume/pinnacle.data` | sì, UTC reali | no — MLB 2016, formato R | sport sbagliato |
| `iredchuk/soccer-bookmaker-odds` | no, un valore per partita | sì, 5 leghe | come Football-Data |
| `statsbomb/open-data` | **no** | sì, formazioni reali | vedi sotto |
| formazioni con istante di pubblicazione | — | — | **nessuna fonte pubblica trovata** |

Forzare le quote di baseball di `pinnacle.data` nel magazzino calcistico
richiederebbe di inventare partite e squadre per contenerle: un test verde che
non dimostra nulla.

Sulle formazioni la ricerca non ha trovato **nessuna** fonte pubblica con
istante di pubblicazione. È prevedibile: «quando questo è diventato noto» è un
fatto effimero che nessuno archivia gratuitamente, e i dataset di formazioni
disponibili sono referti post-partita.

### StatsBomb: raggiungibile, ma è un referto

`statsbomb/open-data` è accessibile e porta formazioni reali con `player_id`
stabili e nomi realmente sporchi — *Martin Braithwaite Christensen*,
*Sergio Busquets i Burgos*. Ma le posizioni riportano i minuti di sostituzione:
**è il referto della partita, non l'undici pubblicato prima**. Non ha un
`published_at` e non può entrare nell'event study.

Il vincolo `published_at NOT NULL` della migrazione 0014 lo rifiuta
automaticamente, che è il comportamento corretto. Resta utilizzabile per una
cosa sola: validare l'**identità giocatore** su nomi veri.

> **Conclusione, basata su prove: non esiste una fonte raggiungibile di quote
> timestampate né di formazioni con istante di pubblicazione. La prima esiste
> ma è dietro un host bloccato.**

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
## Deliverable 4 — l'event study, costruito e validato ✅

`fiorino/research/event_study.py`, 15 test. Non eseguibile sui dati reali —
non ce ne sono — ma validato come lo scanner di ipotesi: piantando un effetto
noto in dati sintetici e verificando che venga trovato, e piantandone nessuno e
verificando che non venga inventato.

La regola che avete dato è **applicata, non raccomandata**:

```python
def require_timestamped(con) -> None:
    # Refuse to run on data that cannot answer the question.
    ...
```

Solleva invece di avvisare. È l'unico punto del sistema in cui rifiutare di
calcolare è il comportamento corretto: ogni altro audit riporta e prosegue,
perché un rapporto su dati incompleti è comunque informativo. Qui no — un event
study su prezzi senza istanti misura nulla, e un numero prodotto ugualmente
sarebbe indistinguibile da uno vero.

Il disegno (doppia differenza), il punteggio di shock e il dimensionamento del
pilot sono in [`next-experiment.md`](next-experiment.md).

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
