# Audit delle fonti gratuite di quote timestampate

**Domanda:** quale fonte gratuita di quote storiche **timestampate** può
realisticamente alimentare Fiorino Quant nel prossimo PR?

Il requisito non è «quote disponibili». Una fonte è candidata solo se undici
proprietà sono **verificabili**, non plausibili. Ogni riga sotto è stata
accertata leggendo lo schema, il codice di export o la risposta HTTP — non
dedotta dalla descrizione.

---

## Classificazione

| stato | significa |
|---|---|
| `USABLE_NOW` | verificata, accessibile da qui, PIT-usabile |
| `USABLE_WITH_EXTERNAL_INGEST` | ha davvero le proprietà necessarie; **solo** l'accesso da questo ambiente manca |
| `PROMISING_BUT_UNVERIFIED` | plausibile, ma qualità del timestamp o dei campi **non accertata** |
| `NOT_SUITABLE` | verificata e priva di una proprietà necessaria |

**Regola di decisione applicata:** una fonte non può essere `USABLE_NOW` se
manca il timestamp necessario a una strategia PIT. Una fonte con timestamp
sconosciuto resta `PROMISING_BUT_UNVERIFIED` — non viene trattata come
timestampata.

---

## La tabella

| Source | Bookmaker | Markets | Historical depth | Timestamp quality | Future fixtures | Access method | Free | Current accessibility | PIT usable | Main limitation |
|---|---|---|---|---|---|---|---|---|---|---|
| **BeatTheBookie — dump SQL** | **32, per nome** | 1X2 | 2005→2016, ~113.860 partite nelle serie | **`odds_datetime` assoluto per osservazione** — verificato nello schema | no | download MySQL dump ~1,8 GB | sì | **bloccato** (Dropbox/Drive) | **sì** | environment access limitation; storico si ferma al 2016 |
| **BeatTheBookie — export `.txt`** | no: 32 righe anonime | 1X2 | idem | **griglia oraria a 72 punti**, ricampionata, relativa al kickoff | no | download zip | sì | **bloccato** (Dropbox/Drive) | **no** | il ricampionamento distrugge l'istante e anonimizza il book |
| Football-Data (mirror GitHub) | sì (Pinnacle, bet365…) | 1X2, AH, O/U | 1993→oggi | **nessuno**: 2 punti per partita, senza istante | no | HTTP su raw.githubusercontent | sì | **raggiungibile** | **no** | non è una serie temporale |
| openfootball | — | nessun mercato | 1888→2026-27 | n/a | **sì, 350** | HTTP su raw.githubusercontent | sì | **raggiungibile** | n/a (nessuna quota) | non porta quote |
| `iredchuk/soccer-bookmaker-odds` | no: media fra book | 1X2 | 2005-2019, 5 leghe | **nessuno** | no | HTTP | sì | raggiungibile | **no** | quote medie, un valore per partita |
| `marcoblume/pinnacle.data` | sì (Pinnacle) | moneyline, totals | MLB 2016 | **UTC reale** | no | pacchetto R | sì | raggiungibile | sì, ma | **non è calcio** |
| Betfair Historical Data | exchange, non book | molti | 2015→oggi | **millisecondo, dichiarato** | no | account + download | «Basic» gratuito | **bloccato** | **non verificato** | schema e licenza non ispezionati da qui |
| the-odds-api | sì | molti | limitato nel piano free | dichiarato per snapshot | sì | REST, chiave | free tier | **bloccato** | **non verificato** | profondità storica del piano free non accertata |
| **OddsPortal** (via OddsHarvester) | sì, per nome | 1X2, AH, O/U, BTTS… | molte stagioni, 100+ campionati | **non verificata, ma ora documentata**: il tooltip porta data e ora per variazione (`%d %b, %H:%M`), senza anno | sì | scraping Playwright | strumento gratuito | **bloccato** | **no** | termini d'uso di un aggregatore commerciale, non letti |
| **xgabora/Club-Football-Match-Data-2000-2025** | sì: bet365, più un massimo su ~17 book | 1X2, O/U 2.5, AH | 2000→2026, 238.858 partite, 211.067 con quota, **38 divisioni** | **nessuno**: un prezzo per partita | no | un CSV da 44 MB su raw.githubusercontent | sì (MIT) | **raggiungibile, scaricato** | **no** | nessun istante; ma è l'unica fonte qui che copra le serie inferiori |
| `eatpizzanot/soccer-dataset` | non verificato | 1X2 | dichiarate 673.966 partite, 186.813 con quota | **non verificata**: dichiara `known_at`, nessuna riga ispezionata | no | Hugging Face (completo), campioni su GitHub | sì | **bloccato** | **no** | letta solo la documentazione; avviso importante sull'xG di API-Football |
| `salimt/football-datasets` — infortuni | — | — | 143.195 storie di infortunio | **nessuno**: `from_date` è retrodatata, non è una pubblicazione | no | CSV nel repo, copia su Kaggle | sì | percorso non risolto | **no** | trappola di leakage: attribuirebbe conoscenza che il mercato non aveva |
| `datasets/football-datasets` (datahub) | sì | 1X2 | 1993→oggi, top 5 | **nessuno**: i commit quotidiani datano lo scraper, su partite già giocate | no | raw.githubusercontent / datahub.io | sì (PDDL) | **raggiungibile** | **no** | sembra la soluzione e non lo è: l'istante cade dopo l'esito |
| `api-sports.io`, `football-data.org`, SofaScore, FBref | — | — | — | — | — | REST | vario | **bloccati** | **non verificato** | nessuna proprietà accertabile da qui |

---

## BeatTheBookie, verificato campo per campo

Trattato come candidato separato, e **non** dichiarato migliore per la sola
profondità storica. La verifica ha trovato una distinzione che la descrizione
non lascia vedere: **la stessa fonte produce due artefatti con qualità PIT
opposte.**

### L'artefatto buono — il dump SQL

Dallo schema interrogato in `src/generate_odds_series_csv.php`:

```sql
SELECT oh.result, oh.disabled_date, ohs.odds, ohs.odds_datetime, oh.bookmaker
FROM odds_history oh
JOIN odds_history_series ohs ON oh.odds_history_id = ohs.odds_history_id
WHERE bettype = '1x2' ...
```

| requisito | esito |
|---|---|
| 1. bookmaker identificabile | **sì** — colonna `bookmaker`, 32 nomi reali (bet365, Pinnacle Sports, William Hill, bwin, Betfair Sports…) |
| 2. mercato identificabile | **sì** — `bettype = '1x2'` |
| 3. selezione identificabile | **sì** — `oh.result` ∈ {1, 2, 3} |
| 4. linea | n/a per 1X2 |
| 5. prezzo | **sì** — `ohs.odds` |
| 6. timestamp | **sì** — `ohs.odds_datetime`, istante assoluto **per osservazione** |
| 7. storico | 2005→2016; le serie coprono ~113.860 partite |
| 8. mapping alle fixture | `matches.ID` + data + squadre; **richiede il risolutore di identità M1** |
| 9. payload raw immutabile | sì: il dump è il payload |
| 10. modello PIT | **sì** — `odds_datetime` è un istante osservato, non dedotto |
| 11. accessibilità | **no da qui**: Dropbox e Google Drive bloccati |

→ **`USABLE_WITH_EXTERNAL_INGEST`**. Il difetto è **environment access
limitation**, non *source unavailable*: il dataset possiede davvero le
proprietà necessarie.

### L'artefatto ingannevole — i file `.txt`

Sono i file che il paper usa, e sono i più facili da trovare. Dal codice che li
genera:

```php
$time_window_hours = 72;
$interval_mins     = 60;
// le prime 72 colonne sono le quote HOME per le 72 ore precedenti la partita
```

E dal codice che li legge: `32 * 216` — **32 bookmaker × 216 colonne**, cioè
3 selezioni × 72 punti.

Quindi il `.txt`:

* **ricampiona** l'istante reale su una griglia oraria **relativa al kickoff**;
* **anonimizza** il bookmaker in un indice di riga;
* perde `odds_datetime`.

→ **`NOT_SUITABLE`**. Non è una serie timestampata: è una serie *ricampionata*,
e la differenza è esattamente ciò che questo progetto non deve confondere.

### La conseguenza che cambia la raccomandazione

**Una griglia oraria non può risolvere l'evento formazioni.** Le formazioni
escono 60–75 minuti dal kickoff; con punti a distanza di un'ora, l'evento e la
finestra di controllo cadono nella stessa cella. L'esperimento M6.5 **non è
eseguibile sui `.txt`**, per quanto storico contengano.

Sul dump SQL invece sì, perché `odds_datetime` è per osservazione.

E resta un limite indipendente dall'accesso: **le serie si fermano al 2016**.
Servono per studiare la microstruttura storica, non per alimentare un terminale
live.

---

## OddsPortal — l'offerta più ampia, e la meno verificabile

`OddsHarvester` (MIT, su PyPI) espone un flag `--odds-history`, documentato come
*«Include historical odds movement per match»*. Se quel movimento porta istanti
assoluti, sarebbe la fonte con la copertura più larga trovata: 100+ campionati,
sette mercati, e anche le partite future.

Due ragioni per cui resta `PROMISING_BUT_UNVERIFIED` e non sale:

1. **La struttura dei campi non è ispezionabile da qui.** `oddsportal.com` è
   bloccato. Che il movimento porti un istante assoluto è plausibile e non
   verificato, e la regola dice che una qualità di timestamp sconosciuta non
   viene trattata come timestampata.
2. **I termini d'uso non sono stati letti.** Lo strumento stesso avverte:
   *«ensure compliance with their terms of service»*. Lo scraping di un
   aggregatore commerciale è tipicamente vietato dai suoi termini. Non è una
   valutazione tecnica e non spetta a questo audit risolverla: va decisa
   leggendoli.

La seconda ragione non sparisce verificando la prima.

## Aggiornamento — ricerca su GitHub, settembre 2026

Quattro fonti nuove, tutte verificate per quanto questo ambiente permette. La
domanda dell'audit non cambia risposta: **nessuna delle quattro porta un
istante di osservazione.** Cambiano altre due cose.

### `xgabora/Club-Football-Match-Data-2000-2025` — l'unica che sblocca qualcosa

Scaricato il CSV vero, 44 MB: 238.858 partite, 211.067 con quota, 38 divisioni
in 27 paesi. Le colonne `OddHome/Draw/Away` sono la quota prematch di bet365 e
le `Max*` il massimo su circa 17 book, come dichiara il README. MIT. Nessun
timestamp: `MatchDate` e `MatchTime` sono il calcio d'inizio.

Non serve all'event study, e non è il punto. Contiene **Inghilterra fino alla
quinta serie, Scozia fino alla quarta, e le seconde divisioni di Germania,
Francia, Italia e Spagna**, cioè esattamente i mercati per cui C-106 è rimasta
`UNTESTED` in quattro milestone: non perché fosse difficile, ma perché il
campione era fatto di sole prime divisioni. Il risultato è in
[`docs/validation/division-efficiency.md`](../validation/division-efficiency.md).

Una cautela sulle colonne derivate: Elo, forma e i cluster `C_*` sono calcolati
dall'autore, e non è stato verificato che usino solo informazione anteriore
alla partita. Un cluster stimato sull'intero dataset conterrebbe l'esito. Per
C-106 sono state usate soltanto le colonne di quota.

### OddsPortal — l'evidenza si è irrobustita, la classificazione no

Leggendo `docs/agentic-gotchas.md` di `jordantete/OddsHarvester` (MIT) è emerso
il dettaglio che mancava: il tooltip **"Odds movement"** di OddsPortal contiene
le variazioni di prezzo **con data e ora**, parsate come `"%d %b, %H:%M"`, e da
lì si ricava anche la quota di apertura; la chiusura viene dalla riga
principale. Il documento precisa che quelle date **non sono localizzate** —
il bundle le rende con array di mesi inglesi fissi — e che l'orario è reso nel
fuso del browser, impostabile con `--timezone`.

Perché conta: il percorso del prezzo è sulla pagina di una partita **già
giocata**. In linea di principio consente un recupero *retrospettivo*, non solo
una raccolta in avanti. È la differenza fra una fonte storica e uno scraper che
si limita a marcare l'ora in cui ha girato, ed è la ragione per cui OddsPortal
resta il candidato più forte dopo BeatTheBookie.

Restano due buchi, ed è per questo che la classificazione **non cambia**:
il formato non porta l'anno, che andrebbe dedotto dal calcio d'inizio con un
rischio reale a cavallo di dicembre; e l'evidenza è la documentazione di terzi,
non un output osservato. Nel registro questo è scritto in
`timestamp_quality_expected`, un campo separato da `timestamp_quality` proprio
perché un'aspettativa non pesi quanto una verifica: un test impedisce che
possa sollevare `pit_usable`.

Una precisazione che evita un equivoco facile, perché è il tipo di campo che
si legge di sfuggita e si promuove per sbaglio: lo strumento espone un
`scraped_at_utc`, ma **solo nella modalità `live`**, cioè a partita in corso,
dove la copertura scende a 2–4 book e `--odds-history` è rifiutato. Non è un
timestamp sulle quote prematch, e non va confuso con le date del tooltip, che
sono l'unica evidenza qui rilevante.

E prima ancora della domanda tecnica resta quella legale: **i termini di
servizio di OddsPortal non sono stati letti.**

### Due fonti che sembrano utili e non lo sono

**`datasets/football-datasets`** committa ogni giorno via GitHub Actions. Un
repository che committa quotidianamente darebbe a ogni riga un istante
attestato da git — un limite superiore di conoscibilità onesto, mai inventato,
e nella direzione sicura, perché un fatto datato più tardi di quando era noto
non fa mai leakage. Ma i commit riguardano **partite già giocate**: l'istante
cade dopo l'esito e non vincola niente. La costruzione funzionerebbe solo su un
file di partite **future** con quota, committato prima del calcio d'inizio, che
questo repository non pubblica. Registrata proprio per questo: è il fallimento
più istruttivo del gruppo.

**`salimt/football-datasets`** porta 143.195 storie di infortunio da
Transfermarkt, e sarebbe la terza priorità della lista di ricerca. Lo schema,
letto nell'anteprima pubblicata dal manutentore, è
`player_id, season, injury_reason, from_date, end_date, days_missed, games_missed`.
`from_date` è la data a cui l'infortunio viene **fatto risalire**, compilata
retroattivamente, spesso giorni dopo. Non è grossolana: è una trappola nella
direzione pericolosa. Usarla come "noto da `from_date`" attribuirebbe al
modello una conoscenza che il mercato non aveva. Un infortunio annunciato 90
minuti prima del fischio d'inizio e uno registrato tre giorni dopo qui sono la
stessa riga. Per l'ipotesi degli infortuni dell'ultimo minuto **nessuna
trasformazione la rende utile.**

### Cosa non è stato trovato, dopo aver cercato

Nessun dataset pubblico, gratuito o a pagamento, che porti **l'istante di
pubblicazione di una formazione**. Le ricerche su archivi di formazioni con
snapshot temporizzati non hanno prodotto nulla, e i dataset di formazioni che
esistono (StatsBomb, schochastics, i vari scraper di WhoScored e SofaScore)
portano la formazione della partita, non il momento in cui è diventata
pubblica. Resta la conclusione già registrata: quell'istante **esiste solo se
lo si registra in avanti**, e nessuno lo ha registrato per noi.

---

## Cosa NON è stato assunto

Per esplicito requisito, nessuna di queste equivalenze è stata usata:

* `PREMATCH` **non** è `TIMESTAMPED` — Football-Data resta senza istante.
* `CLOSING` **non** è un istante esatto — è l'ultimo prezzo, di quando non si sa.
* Una pagina web **non** è una serie temporale.
* L'esistenza di un dataset **non** implica che sia scaricabile — BeatTheBookie
  esiste, è documentato, e da qui è irraggiungibile.
* Una quota senza istante **non** può sostenere un'affermazione su cosa il
  mercato sapesse a un dato momento.

Le fonti dietro API bloccate restano `PROMISING_BUT_UNVERIFIED` anche quando la
documentazione promette timestamp: **non è stato possibile ispezionarne lo
schema**, e la promessa di un fornitore non è una verifica.

---

## Risposte

### A. Fonte migliore attualmente disponibile

**Nessuna.** Nessuna fonte raggiungibile da questo ambiente fornisce quote
timestampate sul calcio. Le due raggiungibili sono utili per altro:
Football-Data per lo storico a due punti (già in uso da M2), openfootball per le
fixture future (già in uso da PR #2).

### B. Fonte migliore con ingestione esterna

**BeatTheBookie, dump SQL** — non l'export `.txt`.

È l'unico artefatto verificato che soddisfa tutti e dieci i requisiti di
contenuto, con `odds_datetime` per osservazione e 32 bookmaker per nome. Il
prezzo: ~1,8 GB da scaricare fuori da qui, storico fermo al 2016, e un lavoro di
identity resolution su nomi di squadra nuovi.

Betfair Historical Data è il secondo candidato ma resta
`PROMISING_BUT_UNVERIFIED`: dichiara il millisecondo, e non ho potuto
ispezionarne schema né licenza.

### C. Principale dato mancante

**L'istante di osservazione del prezzo.** Non le quote — quelle ci sono. Manca
`captured_at`, e senza di esso ogni domanda sul *quando* il mercato ha appreso
qualcosa è formalmente non ponibile, non solo difficile.

Subito dopo, e ancora più scarso: **l'istante di pubblicazione delle
formazioni**, per cui non esiste alcuna fonte pubblica, a pagamento o gratuita.

### D. Prossimo PR consigliato

**PR #3 — Timestamped Market Ingest, con l'adapter BeatTheBookie e nessun dato.**

Sembra un controsenso ed è la cosa giusta: l'adapter, lo schema di mapping e i
test si costruiscono *contro lo schema verificato sopra*, che è documentato e
non cambierà. Poi, appena il dump è disponibile, l'ingestione è un comando e
non un progetto.

Con una condizione da rispettare: **nessuna fixture di prova che finga
`odds_datetime`.** I test verificano la trasformazione, non inventano istanti.

Se invece l'allowlist di `dropbox.com` è ottenibile, PR #3 diventa un PR
completo con dati veri, e va fatto in quell'ordine.
