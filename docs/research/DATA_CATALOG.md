# Catalogo dei dati

Che cosa c'è, che cosa manca, e che cosa è raggiungibile. Un'ipotesi che
richiede un dato non presente qui si chiude con **DATA GAP**, non con un proxy
non dichiarato.

---

## Superficie di rete raggiungibile

Verificata con 20 sonde. Il blocco vale anche per `WebFetch`: è la policy di
egress dell'ambiente, non un dettaglio del client.

| raggiungibile | bloccato |
|---|---|
| `raw.githubusercontent.com`, `github.com`, `objects.githubusercontent.com` | `football-data.co.uk`, `fbref.com`, `understat`, `api.football-data.org` |
| `gitlab.com` | `api.the-odds-api.com`, `api-sports.io`, `api.sofascore.com`, ESPN |
| `pypi.org` | `kaggle.com`, `huggingface.co`, `zenodo.org`, `figshare.com`, `arxiv.org` |
| | **`dropbox.com`**, **`drive.google.com`**, `historicdata.betfair.com`, `data.world` |

---

## Nel magazzino

| dominio | tabelle | copertura | timestamp |
|---|---|---|---|
| Anagrafica | `competitions`, `seasons`, `competition_seasons`, `source_coverage` | 8 campionati | — |
| Identità squadra | `teams`, `team_aliases`, `team_alias_proposals`, `team_identity_overrides`, `team_source_ids`, `team_season_membership` | completa | `decided_at` |
| Partite | `matches`, `match_results`, `match_source_ids`, `match_merges`, `match_kickoff_revisions`, `match_quarantine` | 10 campionati-stagione, 3.502 partite | `settled_at` |
| Quote | `odds_observations`, `odds_closing`, `fair_probabilities`, `bookmakers` | Pinnacle + bet365 | **PREMATCH e CLOSING soltanto** |
| CLV | `bets`, `bet_clv` | — | — |
| Backtest | `backtest_runs`, `cohorts`, `bet_settlements`, `equity_curve` | — | — |
| Modelli | `model_runs`, `predictions` | 219.010 predizioni | `trained_through` |
| Ensemble | `ensemble_weights`, `forecast_scores` | — | `train_max_settled_at` |
| Formazioni | `players`, `player_aliases`, `player_source_ids`, `lineups`, `lineup_slots` | **vuote** | `published_at` richiesto |

### Il fatto centrale

> **Non esiste una sola riga `TIMESTAMPED` in nessun dataset.**

Football-Data dà due punti per partita. `odds_as_of()` e il vincolo
`CHECK ((capture_precision = 'TIMESTAMPED') = (captured_at IS NOT NULL))` sono
scritti, testati e **mai esercitati**.

Ogni esperimento di microstruttura è quindi bloccato — non «non implementato».

---

## Fonti valutate

| fonte | timestamp | calcio | raggiungibile | verdetto |
|---|---|---|---|---|
| Football-Data (mirror GitHub) | no, 2 punti | sì | **sì** | **in uso**, base di M2–M6 |
| `Lisandro79/BeatTheBookie` | **sì, serie continue** | **sì, ~113.860 partite** | repo sì, **dati no** | **a una regola di allowlist** — Dropbox/Drive |
| `marcoblume/pinnacle.data` | sì, UTC | **no**, MLB | sì | sport sbagliato |
| `iredchuk/soccer-bookmaker-odds` | no | sì | sì | come Football-Data |
| `statsbomb/open-data` | **no** | sì | sì | **referto post-partita**, non l'XI pubblicato |
| formazioni con istante di pubblicazione | — | — | — | **nessuna fonte pubblica trovata** |

### La singola azione che sblocca di più

**BeatTheBookie** (Kaunitz, Zhong, Kreiner — arXiv:1710.02824) contiene serie
continue di quote con i movimenti per ~113.860 partite: 31.074 (set-2015 →
mar-2016, 553 campionati) e 82.786 (mar-2016 → nov-2016, 658 campionati).

Il repository è raggiungibile; i dati sono su Dropbox e Google Drive, **entrambi
bloccati**. Il clone porta solo lo script SQL.

> Mettere `dropbox.com` **o** `drive.google.com` in allowlist sblocca EXP-0012
> dal lato quote, con un ordine di grandezza più partite di quante ne servano.
>
> Resta da verificare, una volta accessibile, la granularità di campionamento e
> se gli istanti siano assoluti o relativi al kickoff.

---

## DATA GAP dichiarati

| gap | blocca | perché non è aggirabile |
|---|---|---|
| **Quote timestampate** | EXP-0012, 0013, 0014 | Un event study è una differenza fra due istanti. Senza istanti non c'è misura, e `require_timestamped()` solleva. |
| **Istante di pubblicazione delle formazioni** | EXP-0012, 0013 | `published_at` è `NOT NULL` senza default. Ricavarlo dal kickoff fabbricherebbe la quantità da misurare. |
| **Calendario coppe europee** | «squadre dopo la Champions» | `home_short_rest` è la cosa più vicina che i dati esprimono, e **non è la stessa** |
| **Infortuni con istante** | studio sulle assenze | Un'assenza nota 48 ore prima non è una ritirata a 15 minuti dal via |
| **xG** | mai testato | Non c'è. Nessun risultato del progetto ne stabilisce l'inutilità |
| **Geo degli stadi** | derby, viaggi | — |

---

## Regola sui proxy

Un proxy si usa solo se **dichiarato nel modulo dell'esperimento** e con la
differenza rispetto alla grandezza vera messa per iscritto.

Esempio già registrato: `dead_rubber` approssima «niente per cui giocare» con
punti e giornate residue invece della matematica reale della classifica. È
scritto nei limiti dell'esperimento, e con n_in = 60 non avrebbe comunque avuto
potenza.

Un proxy non dichiarato è la fine della riproducibilità: mesi dopo, nessuno sa
più che cosa è stato misurato davvero.
