# EXP-001 — Il line shopping produce CLV positivo in qualche regione del mercato?

**Stato: PRE-REGISTRATO. Nessun risultato ancora visto.**

Questo file è committato **prima** che il codice di misura esista e **prima**
che il laboratorio giri. Il commit precedente a quello dei risultati è ciò che
rende la pre-registrazione un fatto verificabile invece di un'affermazione. Se
leggi questo file in una versione successiva ai risultati, controlla la storia
git: se le celle sono cambiate dopo il run, la pre-registrazione non vale
niente e il risultato va buttato.

---

## Perché questo esperimento e non un altro

Il 10/09/2026, con il de-vig Shin realmente attivo per la prima volta, il
laboratorio CLV ha misurato su 369.562 osservazioni e 23.381 partite che il
**line shopping** — prendere il prezzo più lungo disponibile sul mercato — è
l'unica regola di microstruttura che produca un effetto grande e riproducibile:

| book | differenza dentro il book | t |
|---|---:|---:|
| BETFAIR_EX | +0,0784 | +54,5 |
| BWIN | +0,0354 | +49,4 |
| BET365 | +0,0228 | +36,0 |

Scomponendo i livelli, l'exchange preso quando è il più lungo del mercato dà
**−0,0192**: il punto più vicino alla parità mai misurato nel progetto, e
ancora dalla parte sbagliata.

Le celle testate finora sono sempre state **marginali** — o per book, o per
banda, o per serie, mai incrociate. Non è mai stata testata una singola
interazione. E lì c'è una tensione che i dati rendono esplicita:

- C-106 ha misurato che il mercato è **meno affilato** nelle divisioni minori
  (6 paesi su 6, test dei segni p=0,031)
- il CLV misura che `LOWER` è **più negativo** di `TOP` (−0,0659 contro −0,0572)

Cioè nelle serie minori il mercato sbaglia di più **e** ti fa pagare di più. I
due effetti si oppongono, e la regione dove il saldo è a nostro favore — se
esiste — non è mai stata guardata.

Sotto Shin, inoltre, le bande corte sono la parte meno tassata della tabella
(−0,0340 sulla banda 1,0–1,6 contro −0,1265 sulla 9,0+). Questa è la seconda
ragione teorica per cui l'incrocio banda × serie è il posto giusto dove
guardare, e non una scelta fatta dopo aver visto i risultati: è scritta qui
prima.

---

## Ipotesi primaria

**H1**: esiste almeno una cella pre-specificata in cui il CLV medio della
strategia di line shopping è **positivo** e sopravvive al controllo della
molteplicità.

**H0**: nessuna cella lo è. Il line shopping riduce la perdita ma non la
inverte in nessuna regione del mercato coperta da questi dati.

---

## Celle, fissate qui e non modificabili dopo

Il disegno è il prodotto pieno di tre dimensioni. **24 celle.**

| dimensione | livelli | n |
|---|---|---:|
| banda di prezzo | 1,0–1,6 · 1,6–2,2 · 2,2–3,2 · 3,2–5,0 · 5,0–9,0 · 9,0+ | 6 |
| serie | TOP · LOWER | 2 |
| strategia | `MERCATO` · `EXCHANGE` | 2 |

`MERCATO` = si prende il prezzo più lungo fra i book veri presenti nella riga.
`EXCHANGE` = si prende Betfair Exchange **solo quando è il più lungo**, e non
si scommette altrimenti.

Le due strategie sono diverse per una ragione economica, non statistica:
l'exchange ha una commissione, gli altri no, e senza separarle si mescolerebbe
un prezzo lordo con uno netto.

`MARKET_MAX` e `MARKET_AVG` **non** partecipano come book: sono statistiche
sugli altri, non quotazioni prendibili. Questa regola esiste già nel progetto
e non viene toccata per questo esperimento.

---

## Regole di misura, fissate qui

1. **Metrica**: `CLV = probabilità equa di chiusura × prezzo netto − 1`.
2. **De-vig**: Shin. Se il ripiego su moltiplicativo si attiva, il run è
   **nullo** e va rifatto — non interpretato. Il banner lo dichiara.
3. **Benchmark di chiusura**: `AvgCH/AvgCD/AvgCA`, lo stesso di `clv_lab.py`.
   Vedi i limiti dichiarati sotto.
4. **Commissione**: 2% sulla vincita netta per la strategia `EXCHANGE`
   (`netto = 1 + (prezzo − 1) × 0,98`), 0% per `MERCATO`.
5. **Errori standard**: raggruppati per partita. Le righe della stessa partita
   non sono osservazioni indipendenti.
6. **Filtro sui CLV assurdi**: `|CLV| > 0,50`, identico a quello esistente, e
   lo split per segno degli scarti va stampato.
7. **Numerosità minima**: una cella entra nella famiglia solo con **≥ 200
   righe e ≥ 100 partite**. Sotto quella soglia non viene testata e viene
   dichiarata come non testata, mai riportata come nulla.

---

## Criterio di decisione, fissato qui

Una cella **sopravvive** se e solo se, congiuntamente:

1. media del CLV **> 0**;
2. **q < 0,10** con Benjamini-Hochberg calcolato **sull'intera famiglia di 24
   celle**, incluse quelle fortemente negative;
3. il **segno tiene in ciascuna delle 4 stagioni** prese separatamente, con
   ≥ 100 righe per stagione. Una cella che cambia segno fra stagioni non è un
   effetto, è un anno fortunato.

Se **zero celle sopravvivono**, H1 è respinta e va scritto in `FINDINGS.md`
che il line shopping è chiuso su questo dataset. Questo è l'esito che mi
aspetto e che va registrato con la stessa enfasi dell'altro.

---

## Cosa NON faremo dopo aver visto i risultati

- aggiungere celle, dimensioni o livelli;
- cambiare `ABSURD_CLV`, il benchmark di chiusura o la commissione;
- passare da BH a un controllo più permissivo;
- riportare una cella che fallisce il punto 3 come «promettente»;
- ripetere il run con parametri diversi finché qualcosa passa.

Se dopo i risultati verrà voglia di fare una di queste cose, la cosa da fare è
scrivere **EXP-002** con la sua pre-registrazione, non modificare questa.

---

## Limiti dichiarati prima, non dopo

- **Il benchmark contiene il book valutato.** `AvgC` è la media di mercato alla
  chiusura e include anche il book di cui si misura il prezzo: è una
  contaminazione di ordine 1/N che schiaccia ogni CLV verso la media. La
  sensibilità al benchmark è un lavoro aperto e separato; questo esperimento
  usa il metro esistente per restare confrontabile con i numeri storici.
- **Massimo contro media.** Il prezzo più lungo è un massimo su N; il benchmark
  è una media su N. Per Jensen l'overround di una media di quote è più basso
  della media degli overround. Parte di qualunque differenza contiene questa
  componente aritmetica, che non è esecuzione.
- **Il CLV non è profitto.** È la metrica di verità del progetto perché il suo
  verdetto è risultato corretto 30 volte su 30 dove il rendimento sbagliava 7
  volte su 30, ma una cella con CLV positivo resta **un candidato il cui
  comportamento fuori campione non è mai stato osservato**.
- **Nessun limite di puntata è modellato.** Un prezzo più lungo della media è
  spesso più lungo perché è più piccolo: la liquidità disponibile a quel prezzo
  non è in questi dati.
- **Copertura.** 21 divisioni, 4 stagioni, i soli book presenti nei file di
  Football-Data. Non è «il mercato»: è questo mercato.

---

## Cosa succede se H1 sopravvive

Niente scommesse. Una cella sopravvissuta entra come **candidata** e deve
passare i sei cancelli di promozione già definiti dal progetto prima di essere
qualcosa. `PROMOTED` resta **0** fino ad allora, e in particolare serve una
verifica **in avanti**, su partite non ancora giocate al momento in cui questo
file è stato scritto: è l'unica prova che nessuna scelta retrospettiva può
fabbricare.
