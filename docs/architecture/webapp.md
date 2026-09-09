# La web app (V0)

```
iPhone → Safari → fiorinoquant.streamlit.app
                        │
                  Streamlit Community Cloud
                        │
                  repo GitHub (push → redeploy)
                        │
              magazzino DuckDB in memoria
                        │
              archivio Football-Data reale
```

Nessun calcolo sul telefono. Il telefono è solo l'interfaccia.

---

## Cosa mostra, e perché non mostra di più

La V0 mostra **lo stato reale del laboratorio**, che è: nessun edge validato.

Il vincolo non è nell'interfaccia, è nel codice:

```python
PROMOTED: dict[str, dict] = {}     # fiorino/decision/signal.py
```

Finché quel registro è vuoto, `classify()` **non può** restituire più di
`WATCH`. Non per prudenza dell'interfaccia: c'è un test che fallisce se il
soffitto viene alzato senza una promozione registrata, e un altro che verifica
che il meccanismo funzioni davvero promuovendo una strategia finta.

E non esiste un livello `BET`. Aggiungerlo è una decisione che richiede un
record di promozione, non una costante.

```
⚪ NO_SIGNAL   ⛔ nessun edge, o dato vecchio, o CLV storico negativo
🔵 WATCH       edge presente, evidenza insufficiente o non promossa
🟡 CANDIDATE   CLV storico positivo su campione sufficiente
🟢 QUALIFIED   ha superato tutti e sei i gate  ← irraggiungibile oggi
```

Sulla schermata di analisi ogni selezione mostra **NO_SIGNAL**, e la ragione è
un numero misurato: `model_edge` su ENG_PL 2017-18 ha CLV **−0.0336, t = −12.3**
su 676 scommesse. Un EV positivo del modello con quella storia non è un
segnale, è un errore già misurato.

## La black box

Ogni decisione porta le ragioni, quelle a favore e quelle contro. «Il modello
la vede bene» non è una ragione: una ragione nomina **una misura e una soglia**,
e c'è un test che lo verifica sul testo prodotto.

```
⚪ NO_SIGNAL
✅ EDGE — EV +0.0800 sopra +0.0200
⛔ NEGATIVE_CLV — CLV storico -0.0336, t=-12.3 — questa classe di
   segnale ha gia perso contro la chiusura
```

## L'ordine dei controlli conta

I disqualificanti girano per primi, così un prezzo vecchio è riportato **come
vecchio** e non come un piccolo edge. Chi legge solo la prima riga non deve
essere ingannato.

```
1. violazioni point-in-time   → NO_SIGNAL
2. dato stantio (> 30 min)    → NO_SIGNAL
3. nessuna previsione         → NO_SIGNAL
4. EV sotto soglia            → NO_SIGNAL
5. prior di lega              → non oltre WATCH
6. campione sottile           → non oltre WATCH
7. CLV storico negativo       → NO_SIGNAL
8. CLV storico positivo       → CANDIDATE, poi il soffitto
```

Il punto 5 chiude sullo schermo la stessa falla che M5 aveva nominato:
scommettere più forte proprio dove il modello sa meno.

---

## Il magazzino è costruito a runtime

Il repository contiene codice, schema e configurazione; il dataset vive sotto
`$FIORINO_DATA_ROOT`, **fuori dall'albero**, e Community Cloud non ha quella
directory.

Quindi l'app scarica un archivio Football-Data reale e costruisce un DuckDB in
memoria alla prima richiesta, con `@st.cache_resource`. Niente è finto: sono le
stesse partite, gli stessi prezzi e le stesse regole di identità su cui ha
girato la validazione. Le proposte di identità vengono **rifiutate**, non
approvate: un club non giudicato resta fuori dal dataset analitico invece di
essere fuso su un punteggio di somiglianza.

## Perché non è un live scanner

Non esiste una riga `TIMESTAMPED` in nessun dataset. `odds_as_of()` è scritto,
testato e mai esercitato. La pagina **Sistema** lo dice in rosso invece di
lasciarlo dedurre.

Un live scanner richiede quote timestampate — vedi
[`data-acquisition.md`](data-acquisition.md).

---

## Deploy

1. Streamlit Community Cloud → **New app** → questo repository
2. Branch: `claude/european-football-value-bet-ddqnq6`
3. Main file: `app/streamlit_app.py`
4. Le dipendenze vengono da `requirements.txt`

`requirements.txt` è deliberatamente minimale e **non** installa il pacchetto
locale: l'app aggiunge la radice del repository a `sys.path`, così Community
Cloud non deve compilare le estensioni Cython di penaltyblog, che la dashboard
non usa.

Ogni push sul branch fa il redeploy.

## Cosa manca per la V1

| | |
|---|---|
| Partite future | oggi il dataset è storico: non ci sono fixture da giocare |
| Quote timestampate | il blocco di tutto il resto |
| Formazioni | nessuna fonte pubblica con istante di pubblicazione |
| Aggiornamento automatico | GitHub Actions, quando ci sarà una fonte da aggiornare |
| Alert | solo dopo che esiste un segnale che valga la pena notificare |
