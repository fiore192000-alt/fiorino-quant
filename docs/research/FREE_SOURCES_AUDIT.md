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
