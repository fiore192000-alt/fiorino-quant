# Il registratore di quote prematch

Football-Data non e un **market feed**. E una **timestamped snapshot source**, ed e la descrizione onesta di cio che sa fare.

Chiude il blocco 2 della scheda partita — e solo quello, con una parte del 3.
Va detto subito perché la tentazione è di venderlo per di più.

## Cosa risolve, e cosa no

`football-data.co.uk/fixtures.csv` è un file di **partite non ancora giocate**
con le quote di più bookmaker, fra cui **Pinnacle** (`PSH/PSD/PSA`) — il book
contro cui è tarata tutta la metodologia M3, M5 e M6.

Leggerlo a un istante che possiamo nominare rende `captured_at` un istante
vero. Sono quindi le **prime quote TIMESTAMPED del progetto**, quelle che le
quattro viste `v_market_*` aspettano restituendo zero righe.

| blocco | effetto |
|---|---|
| 2 · Mercato | ✅ si chiude, con Pinnacle |
| 3 · Movimento | ⚠️ uno o due punti, non un percorso |
| 4 · Consenso | ❌ serve un feed vero |
| 6 · Reazione | ❌ idem |

Football-Data raccoglie le quote del weekend il venerdì e quelle infrasettimanali
il martedì. Non è un feed: è un'istantanea che si muove un paio di volte a
settimana. Non dirà mai niente sulla microstruttura.

## Perché questa fonte e non uno scraper

È un file che il sito **pubblica per il download**, non una pagina da scrapare.
Non solleva nessuna delle domande che tengono OddsPortal classificato come non
verificato. È gratuito, ha la stessa convenzione di colonne che il progetto già
legge, e — la cosa che conta di più in pratica — **non richiede nessun token,
nessun account, nessun secret**.

L'unica cosa fra questo file e una raccolta attiva è il merge sul branch di
default, perché GitHub elenca `workflow_dispatch` ed esegue `schedule` solo per
i workflow presenti lì.

## Tre parole che non sono sinonimi

```
poll         Fiorino ha guardato. Registrato comunque, anche a vuoto.
observation  un prezzo e stato registrato, perche differiva dal precedente.
movement     un'observation che non e la prima per quella coppia.
```

`is_first_sighting` separa la seconda dalla terza. Una prima osservazione non e
un movimento: e il momento in cui siamo arrivati.

E `captured_at` significa **quando Fiorino ha letto il file**. Non quando il
book ha fissato il prezzo, e non quando Football-Data ha aggiornato il file:
nessuno dei due e conoscibile da qui. E un'osservazione vera di Fiorino, e non
e un `market_price_at`.

## Il file si muove più lentamente dei poll

È la differenza rispetto al registratore di formazioni, e definisce il rischio
principale: un collector che tratta ogni lettura come un'osservazione produce
una serie temporale fitta e sicura di sé a partire da un file che nessuno ha
toccato. Un mercato piatto che sembra misurato ed è soltanto stato guardato.

Da cui la separazione:

```
ogni poll        viene registrato   — è ciò che rende misurabile il gap successivo
solo un CAMBIO   diventa un prezzo  — perché solo quello è un movimento
```

Stessa forma di `fold_sightings`: il flusso dei poll è l'evidenza, il risultato
ripiegato è il fatto.

Una sfumatura che il test fissa: un prezzo che torna al valore precedente conta
come **due** movimenti, non zero. Deduplicare contro tutta la storia
cancellerebbe il secondo, e un mercato che si è mosso ed è tornato indietro si
è mosso due volte.

## Cosa non è verificato

**Nessuna richiesta è mai partita da qui**: `football-data.co.uk` è bloccato
dalla policy di egress di questo ambiente. Le colonne dell'adapter vengono
dalle note pubblicate dal sito, lette da un mirror, e dal fatto che le sue
librerie client leggono il file delle partite future con gli stessi nomi. È
possibile che `fixtures.csv` ne porti meno di un file di stagione.

Per questo `--verify` stampa `COLUMNS` per intero e le prime righe grezze, e
per questo la prima esecuzione va fatta in quella modalità. Il percorso è stato
esercitato contro un finto server locale, quindi la forma dell'output è
osservata; ciò che resta ipotizzato è solo il contenuto reale del file.

E i termini d'uso non commerciale del sito non sono stati riletti.

## Cosa questo NON recupera

Le partite del 7, 8 e 9 settembre 2026. Nessuna fonte raggiungibile porta
quelle quote: il mirror `datasets/football-datasets` committa ogni giorno ma il
suo `process.py` scrive 22 colonne e **nessuna quota**, e `xgabora` arriva al 3
settembre. Un collector raccoglie in avanti. Il passato che non è stato
registrato resta un `DATA_GAP`, ed è esattamente il motivo per cui la data di
partenza conta.
