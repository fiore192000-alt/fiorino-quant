# Audit delle fonti gratuite

Richiesto per capire quali parti di Fiorino Quant si possono alimentare **senza
pagare API**. Ogni riga è una sonda eseguita, non una supposizione.

> L'architettura software è ormai molto più avanti della disponibilità di dati
> live. Questo documento dice esattamente di quanto.

---

## Il risultato in una tabella

| serve per | fonte gratuita raggiungibile? | stato |
|---|---|---|
| **Fixture future** | **sì — openfootball** | ✅ **sbloccato** |
| Risultati storici | sì — openfootball, Football-Data (mirror) | ✅ in uso |
| Quote storiche (2 punti/partita) | sì — mirror Football-Data su GitHub | ✅ in uso |
| **Quote timestampate** | **no** | ❌ **blocca tutto il resto** |
| **Formazioni con istante di pubblicazione** | **no** | ❌ blocca l'event study |
| Formazioni post-partita | sì — StatsBomb open-data | ⚠️ referto, non pre-partita |
| xG | non verificato (Understat/FBref bloccati) | ❓ |

---

## Fixture future — sbloccato

`openfootball/football.json` è raggiungibile e contiene la **stagione in corso**:

```
2026-27  en.1.json   380 partite | con risultato 30 | future rispetto al 09/09/2026: 350
         prossima:   2026-09-12 15:00  Crystal Palace FC - Ipswich Town FC
2025-26              380 partite | tutte concluse
```

Quindi la pagina «partite di oggi» è costruibile **adesso**, gratis. Con tre
avvertenze da mettere per iscritto prima di costruirla:

* **Non è un feed live.** È un repository aggiornato a commit. La freschezza si
  misura dall'ultimo commit, non da un orologio, e la dashboard deve mostrarla
  come tale.
* **I nomi delle squadre sono diversi** da quelli di Football-Data
  («Manchester United FC» contro «Man United»). Passa dal risolutore di
  identità di M1 come qualunque altra fonte — nessuna eccezione, nessun
  matching per somiglianza.
* **Nessuna quota.** openfootball dà calendario e risultati. Le partite future
  compariranno senza prezzo, quindi senza probabilità di mercato e senza
  decisione possibile: `NO_SIGNAL` con ragione `NO_EDGE_COMPUTED`.

Quest'ultimo punto è il vero limite: **si possono mostrare le partite di
domani, non analizzarle.**

## Quote timestampate — nessuna fonte gratuita

Sonde: `the-odds-api` (bloccata), `api-sports` (bloccata), `football-data.org`
(bloccata), `historicdata.betfair.com` (bloccata). Su GitHub esiste il dato
giusto — **BeatTheBookie**, ~113.860 partite con serie continue di quote — ma i
file sono su Dropbox e Google Drive, entrambi bloccati.

Anche fuori da questo ambiente, il quadro non cambia molto: le quote
timestampate live sono il prodotto che i fornitori vendono, ed è raro trovarle
gratis con una copertura utilizzabile.

## Formazioni con istante di pubblicazione — nessuna fonte, gratuita o no

Non è una questione di prezzo. «Quando questo è diventato noto» è un fatto
effimero che quasi nessuno archivia: i dataset di formazioni disponibili sono
**referti post-partita**, con i minuti delle sostituzioni.

Il vincolo `published_at NOT NULL` senza default li rifiuta automaticamente, che
è il comportamento corretto.

Questo dato va **raccolto in avanti**, ed è il vero collo di bottiglia del
progetto.

---

## Cosa si può costruire gratis, in ordine

```
✅ V0   dashboard su dati storici                      fatto
✅      fixture future (openfootball)                  sbloccato, da costruire
❌      quote sulle partite future                     nessuna fonte
❌      quote timestampate                             nessuna fonte
❌      formazioni con istante                         nessuna fonte
```

Quindi la V1 gratuita realistica è:

> **Un terminale che mostra le partite in arrivo e, per quelle storiche, tutta
> la catena analitica — senza poter analizzare quelle future.**

Non è il prodotto finale. È onestamente ciò che i dati gratuiti consentono, ed
è più di quanto la V0 mostri oggi.

## Le due azioni che cambierebbero il quadro

1. **Mettere `dropbox.com` o `drive.google.com` in allowlist.** Sblocca
   BeatTheBookie e con esso l'intera classe di esperimenti sui movimenti di
   quota, su ~113.860 partite. È una modifica alla policy di egress
   dell'ambiente, non al codice.
2. **Iniziare una raccolta in avanti delle formazioni**, con l'istante di
   pubblicazione, su un campionato. Richiede una fonte contattabile e un
   processo che giri ogni giorno. Il dato non esiste retroattivamente: è tempo,
   non calcolo.

Nessuna delle due è un problema di modellazione.
