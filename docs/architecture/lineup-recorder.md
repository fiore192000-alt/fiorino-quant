# Il registratore di formazioni

L'unico componente del progetto il cui valore cresce lasciando passare il
tempo, e l'unico la cui produzione non è recuperabile: un poll non fatto è un
fatto perso per sempre, a qualunque prezzo.

## Perché esiste

Tutto il resto si compra o si scarica dopo. L'istante in cui un undici titolare
è diventato pubblico no. L'audit delle fonti non ne ha trovata **nessuna**,
gratuita o a pagamento, che lo porti: i dataset di formazioni che esistono
registrano **quale** era l'undici, mai **quando** è diventato conoscibile.

Quindi esiste solo se qualcuno lo scrive mentre succede.

## Cosa significa `known_at`

Un poller non osserva una pubblicazione. Osserva la propria lettura riuscita.
Perciò qui `known_at` significa sempre e solo:

> l'istante in cui **il nostro** poll ha visto per la prima volta un undici
> CONFIRMED per quella partita

Mai l'orario di pubblicazione dichiarato dalla fonte, che è un numero che la
fonte calcola come vuole e che non abbiamo modo di verificare. Prenderlo
sarebbe lo stesso errore di leggere `from_date` da una riga di infortunio di
Transfermarkt: un fatto retrodatato da qualcun altro, adottato come se lo
avessimo saputo allora.

Essere un **avvistamento** e non una pubblicazione lo rende un **limite
superiore**: l'undici era pubblico a quell'istante o prima. È la direzione
sicura — un fatto datato più tardi di quando era noto non può far filtrare
informazione all'indietro — ma è sicura solo se la larghezza del limite viaggia
insieme al limite.

## L'incertezza fa parte della misura

Se il poll precedente su quella partita è passato 15 minuti prima
dell'avvistamento, tutto ciò che si sa è «da qualche parte in quei 15 minuti».

Va registrato, perché la domanda per cui questo dataset viene raccolto — cosa
ha fatto il mercato nei minuti dopo la comparsa dell'undici — **non è ponibile**
quando l'incertezza è larga quanto la finestra da misurare. È esattamente il
difetto che ha reso inutile la griglia oraria di BeatTheBookie.

Da cui tre regole, ognuna presente perché la sua assenza produce un numero
plausibile e sbagliato:

| regola | senza di essa |
|---|---|
| solo CONFIRMED fissa `known_at` | un undici *previsto* visto alle 14:00 sposterebbe l'istante di cinque ore e trasformerebbe un movimento reale in un non-evento |
| un poll fallito non chiude nessun intervallo | non guardare e guardare senza successo sono la stessa evidenza: nessuna. Contare il fallimento dimezzerebbe un'incertezza vera |
| un poll fuori scope non chiude nessun intervallo | un poll sulle partite di domani non dice niente su quelle di oggi |

E `None` non vuol dire «preciso»: è il caso in cui nessun poll precedente
copriva la partita, quindi l'undici poteva essere pubblico da ore.
`usable_for_window()` lo rifiuta sempre — zero sarebbe l'affermazione più
sicura ricavata dalla minor evidenza.

L'incertezza è calcolata dallo **scarto reale fra poll avvenuti**, mai dalla
cadenza dichiarata nel cron: le esecuzioni pianificate di GitHub Actions
vengono ritardate sotto carico, a volte di parecchio, e una cadenza dichiarata
è un'intenzione, non un'osservazione.

## Perché l'archivio sta dentro il repository

Il bronze storico ne sta fuori di proposito: è grande, è riscaricabile, e
committarlo seppellirebbe il codice. Questo archivio è l'opposto su ogni punto.
Pesa qualche kilobyte al giorno, **non è riscaricabile a nessun prezzo**, e
committarlo compra una proprietà che nessun altro storage dà: l'orario del
commit è un'attestazione di `observed_at` fatta da GitHub e non da noi. Un
istante di prima osservazione garantito solo da chi lo ha scritto vale
sensibilmente meno.

Append-only per costruzione. Un poll è un fatto su un istante e non si modifica
dopo.

## La fonte, e perché questa

| fonte | perché no |
|---|---|
| football-data.org | il piano gratuito **non porta formazioni** |
| API-Football | ~100 chiamate al giorno sul piano gratuito; il polling ne richiede ~300 |
| SofaScore, FotMob | endpoint non ufficiali, termini non letti — la stessa obiezione sollevata contro OddsPortal, e sarebbe incoerente sollevarla lì e ignorarla qui |
| **SportMonks** | undici confermati sul piano gratuito, API ufficiale documentata, token di registrazione gratuita |

Stretta: il piano gratuito copre due competizioni. Ma due competizioni raccolte
onestamente valgono più di dodici raccolte con termini che nessuno ha letto. E
l'adapter è sostituibile: la parte che conta — la disciplina su `known_at` — è
indipendente dalla fonte.

**L'adapter non è verificato.** Nessuna richiesta è mai partita: ogni API
esterna è bloccata dalla policy di egress di questo ambiente, quindi i nomi dei
campi vengono dalla superficie pubblicata dell'API e non da una risposta che
qualcuno abbia visto. Per questo esiste `--verify`, e per questo la prima
esecuzione va lanciata a mano in quella modalità: riporta la forma che l'API ha
davvero restituito invece di dare per buono questo file.

## Far partire la raccolta

Una cosa sola, e non posso farla io:

1. registrarsi su SportMonks (piano gratuito) e copiare il token;
2. repository → *Settings* → *Secrets and variables* → *Actions* → *New
   repository secret* → nome `SPORTMONKS_TOKEN`;
3. *Actions* → `record-lineups` → *Run workflow* con **verify** spuntato, e
   leggere cosa riporta.

Prima di tutto questo serve però il **merge sul branch di default**: GitHub
elenca `workflow_dispatch` ed esegue `schedule` soltanto per i workflow
presenti lì. Finché `record-lineups.yml` sta solo sul branch di lavoro, in
*Actions* non c'è niente da lanciare.

## Cosa stampa `--verify`, e cosa non può stampare

Diagnostica soltanto: non scrive, non archivia, e non condivide alcun percorso
di codice con la raccolta — `probe()` è separata da `fetch()` proprio perché
niente di ciò che si vede qui possa diventare un record.

```
REQUEST=fixtures/date/2026-09-10?include=lineups
HTTP_STATUS=200
FIXTURES_FOUND=2
FIXTURES_WITHOUT_CONFIRMED_LINEUP=1
CONFIRMED=1
PREDICTED=UNSUPPORTED_BY_ADAPTER
KNOWN_AT_UNCERTAINTY_SECONDS=None  # richiede due poll riusciti
FIRST_TEAM_ID=53
FIRST_PLAYER_IDS=[...]
FIRST_RAW_FIXTURE_PAYLOAD={ ... }
```

Due righe meritano di essere lette per quello che dicono:

`PREDICTED=UNSUPPORTED_BY_ADAPTER` non è mai `0`. L'adapter legge solo le righe
dei titolari: non guarda. **Zero** affermerebbe che ha guardato e non ha
trovato niente, che è un fatto diverso — la stessa regola che `SOURCES.json`
applica alla qualità dei timestamp.

`KNOWN_AT_UNCERTAINTY_SECONDS=None` non è simulato. Al primo avvistamento in
assoluto non esiste un poll precedente su cui misurare, quindi `None` è il
valore vero e qualunque numero sarebbe inventato. Diventa reale al secondo
poll riuscito, ed è lì che va verificato — non nel verify.

Il token non compare mai nell'output, nemmeno nel corpo di un errore: è il
punto in cui un provider tende a rimandare indietro la richiesta, e questo
output è fatto per essere incollato.

Senza il secret il workflow resta verde e non scrive niente: un workflow che
fallisce ogni dieci minuti finché non lo configuri è un workflow che si mette
in muto, e un collector in muto è un collector fermo.
