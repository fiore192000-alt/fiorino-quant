# La scheda partita, misurata contro i dati che esistono davvero

Nove blocchi, dal più importante al meno. La domanda non è se siano i blocchi
giusti — lo sono. La domanda è **quanti se ne possono riempire oggi**, e la
risposta è il piano di acquisizione dati scritto in una forma diversa.

| # | Blocco | Stato | Perché |
|---|---|---|---|
| 1 | **Partita** | ✅ **disponibile** | openfootball, 350 fixture future, public domain |
| 2 | **Mercato** (prezzi correnti) | ⬛ **DATA_GAP** | nessun feed di quote live: le fonti raggiungibili sono tutte storiche e post-partita |
| 3 | **Movimento** (open/now/%) | ⬛ **DATA_GAP** | `v_market_summary` esiste e calcola deriva netta e percorso totale — su zero righe |
| 4 | **Consenso** (27/32 book) | ⬛ **DATA_GAP** | `v_market_breadth` esiste — su zero righe |
| 5 | **Formazioni** (`known_at`) | ⬛ **DATA_GAP** | `lineups.published_at` è `NOT NULL` **senza default**: nessuna riga può entrare senza un istante vero, e nessuna fonte lo pubblica |
| 6 | **Reazione mercato** | ⬛ **DATA_GAP** | dipende da 3 e da 5; `require_timestamped()` **solleva** invece di stimare |
| 7 | **Modello** (fair/edge) | ⚠️ **disponibile e fuorviante** | il numero si calcola, ma è il numero che dichiara «value» in un terzo delle selezioni con CLV negativo 30 volte su 30 |
| 8 | **CLV storico per famiglia** | ⬛ **NO_SIGNAL** | la macchina CLV è validata 30/30; `PROMOTED` è vuoto: nessuna famiglia ha mai replicato |
| 9 | **Decisione** | ✅ **disponibile** | `SignalLevel`, con `DATA_GAP` fuori dalla scala e nessun `BET` |

**Due blocchi su nove si riempiono oggi.** Uno è il titolo della partita e
l'altro è la parola che dice che non si scommette.

## La parte che conta

I sei `DATA_GAP` **non sono sei problemi.** I blocchi 2, 3, 4 e 6 si chiudono
tutti con lo stesso identico input — quote con `captured_at` — e il blocco 6 si
chiude solo se arriva anche il 5. Cioè:

```
  quote timestampate      →  sblocca i blocchi 2, 3, 4
  + formazioni con known_at →  sblocca il blocco 6
```

Il codice per tutti e quattro è **già scritto e già testato**: le quattro viste
`v_market_*` filtrano `capture_precision = 'TIMESTAMPED'` e restituiscono zero
righe perché l'unico adapter che può produrre quel valore
(`sources/beatthebookie.py`) non ha mai ingerito niente. Non manca una
funzione. Manca la riga.

Questo è il motivo per cui una pagina «Market Observatory» costruita domani
mostrerebbe una tabella vuota, e perché non è nella lista di cose da fare
adesso: la pagina non è il pezzo mancante.

## Il blocco 7 merita una nota separata

È l'unico blocco pieno che può fare danno. `Fair 2.05 · Market 2.10 · Edge
+2.4%` è tipograficamente identico a un edge vero, e viene da un modello che in
M5 perde contro la chiusura in **10 dataset su 10** e in M6 non aggiunge
informazione in **nessuno**. Mostrarlo accanto agli otto blocchi vuoti lo fa
sembrare l'unica cosa che funziona, quando è l'unica cosa che è già stata
misurata e trovata insufficiente.

Se un giorno comparirà in una scheda, va accanto al suo CLV, non da solo.

## Cosa dice questa tabella che il piano non diceva

Il piano di acquisizione elenca le fonti. Questa tabella dice **quanto costa
ciascun blocco in termini di fonti**, ed è più utile per decidere:

- il blocco 5 (formazioni) è l'unico che richiede una fonte **che non esiste**
  e quindi una raccolta in avanti, mesi di attesa, nessuna scorciatoia;
- i blocchi 2-4 richiedono una fonte che **esiste** ed è ferma su un ostacolo
  di rete o di termini d'uso, cioè giorni, non mesi;
- il blocco 8 non richiede dati nuovi ma **tempo**: la macchina c'è, servono
  segnali che replichino, e nessuno ha ancora replicato.

Quindi l'ordine non è «tutto in parallelo». È: sbloccare le quote (giorni),
avviare la raccolta formazioni **lo stesso giorno** perché è quella con il
tempo di attesa più lungo, e lasciare il blocco 8 al calendario.
