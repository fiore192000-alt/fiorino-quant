# Protocollo di ricerca

Questo documento vincola chiunque lavori su Fiorino Quant, umano o agente.
Non è una raccomandazione di stile: è ciò che separa una scoperta da un
artefatto, e il progetto ha già prodotto abbastanza artefatti da sapere che
aspetto hanno.

---

## Il fatto che giustifica tutto il resto

M4 ha misurato, su dati reali:

> `take_home` su ENG_PL 2019-20: **+11,91% di yield, +287% di crescita**.
> CLV −0,0272, t = **−11,5**.

Una tearsheet con quei numeri verrebbe presentata come una scoperta. Era rumore,
e solo il CLV lo diceva. Ogni regola sotto esiste per rendere quell'errore
difficile da commettere di nuovo.

---

## 1. L'ipotesi si registra prima di guardare i dati

Nessuno modifica un'ipotesi dopo aver visto un risultato. Non la soglia, non la
finestra, non l'universo, non la metrica primaria.

Se guardando i dati viene un'idea migliore, **è una nuova ipotesi**, si
registra come tale, e conta nella famiglia dei test multipli. Non sostituisce
la precedente: la precedente resta a registro con il suo esito.

Il modulo è in [`EXPERIMENT_TEMPLATE.md`](EXPERIMENT_TEMPLATE.md).

## 2. Il benchmark è il mercato, non il risultato

Prevedere bene i risultati non è la domanda. La domanda è se un'informazione
aggiunge qualcosa a ciò che il prezzo già contiene.

Ogni candidato si misura contro tre riferimenti, sempre:

```
  MARKET             il prezzo de-viggato, da solo
  MARKET + BASELINE  il mercato più il modello Fiorino corrente
  MARKET + CANDIDATE il mercato più l'informazione nuova
```

Mai `modello nuovo contro niente`. **M6 ha già stabilito che il modello
Dixon-Coles non batte questo benchmark**: una proposta che riparte da zero
ignora un risultato già acquisito.

## 3. Se non è timestampato, non entra

Un fatto senza istante non può entrare in un esperimento point-in-time. Non
come approssimazione, non «più o meno», non con il kickoff al posto della
pubblicazione.

`fiorino.research.event_study.require_timestamped()` **solleva** invece di
avvisare. È l'unico punto del sistema dove rifiutare di calcolare è il
comportamento corretto: altrove un rapporto su dati incompleti è comunque
informativo, qui un numero prodotto ugualmente sarebbe indistinguibile da uno
vero.

## 4. Ogni misura ha un controllo

Il mercato si muove comunque: mediana **2,29 punti di probabilità** fra prematch
e chiusura, oltre 1 punto nell'**83%** delle partite. Senza controllo si misura
«il prezzo è cambiato», non «è cambiato per questo».

Il controllo dev'essere equivalente nella durata **e nella posizione rispetto
al kickoff**, perché i prezzi si muovono più in fretta avvicinandosi all'inizio.

## 5. La correzione per test multipli non è opzionale

Testare 41 nulle vere al 5% produce **~2 falsi positivi**. Il sopravvissuto di
cento test è una statistica d'ordine, non evidenza.

Benjamini-Hochberg sull'intera famiglia, controlli inclusi nel denominatore.
Escluderli renderebbe la soglia più facile per tutto il resto.

## 6. La potenza si dichiara insieme al risultato

«Nessun effetto trovato» è privo di significato senza «avremmo potuto trovarne
uno grande X». La scansione delle ipotesi riporta un effetto minimo rilevabile
di **0,039–0,072 punti**: esclude mispricing grossolani, non bias di 2–3 punti
che sarebbero comunque molto profittevoli.

## 7. Un risultato positivo non è un risultato finché non replica

Almeno **2 campionati** e **2 periodi indipendenti**. Un segno che vale in una
lega-stagione e in nessun'altra è come appare l'overfitting visto da dentro.

## 8. Un risultato positivo va attaccato prima di essere creduto

Vedi [`PROMOTION_GATES.md`](PROMOTION_GATES.md), gate 5. Chi trova un edge ha
l'onere di provare a ucciderlo.

## 9. I risultati negativi restano a registro

Non si cancellano e non si ritentano in silenzio cambiando soglia o
definizione. Il registro esiste perché la stessa idea non venga provata dieci
volte finché una versione passa.

## 10. Ciò che non è dimostrato non si afferma

Il progetto ha già ritirato tre proprie affermazioni: l'asimmetria HOME/AWAY nel
drift, la «firma della miscalibrazione», e la conclusione che mancasse «una
classe di informazione». Tutte e tre sembravano solide su un campione.

La formulazione corretta di un risultato negativo è:

> **«Non abbiamo trovato effetti superiori a X con questo campione e questo
> disegno»**, non «questa cosa non funziona».

Il peso dell'evidenza basta per **ordinare** le priorità di ricerca. Non basta
per **eliminare** una direzione senza averla misurata.

---

## Vocabolario obbligatorio degli esiti

Un esperimento termina con una di queste, e con nessun'altra:

| esito | significato |
|---|---|
| **DATA GAP** | manca un dato necessario. Non è stato sostituito con un proxy. |
| **NO EVIDENCE** | l'effetto non supera il controllo, o il CI contiene lo zero. |
| **UNREPLICATED** | positivo su un campione, non replicato. Non è un candidato. |
| **NO INCREMENTAL EDGE** | il mercato contiene già l'informazione. |
| **CANDIDATE** | supera tutti i gate. Va al paper trading, non a una scommessa. |

«Promettente», «incoraggiante» e «da approfondire» non sono esiti.
