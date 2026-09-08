# Storage e versionamento del dataset

Risposte alle cinque domande poste prima di M2. Ogni comando in questo
documento è stato eseguito su dati reali openfootball, non solo progettato.

---

## 0. Una correzione al progetto precedente

Avevo scritto che «il rebuild dal bronze riproduce il dataset». **È falso come
formulato.** Lo stesso bronze aggiudicato in modo diverso produce un dataset
diverso, e le decisioni di identità non sono derivate da nulla: niente può
rigenerarle.

Un dataset ha **due input**:

```
bronze  +  identity ledger  ──►  silver/gold
```

Questo cambia dove vivono le cose:

| Cosa | Natura | Dove |
|---|---|---|
| bronze | massivo, generato da macchina, ri-scaricabile | data store |
| identity ledger | curato, kilobyte, scritto da umani, **non rigenerabile** | **git** |
| warehouse DuckDB | derivato, usa e getta | data store |

Il ledger sta nel repository per la stessa ragione delle migrazioni: è un
registro piccolo e ispezionabile di decisioni, e perderlo significa
ri-aggiudicare ogni club a mano.

---

## 1. Architettura storage finale

```
repository (git)                      $FIORINO_DATA_ROOT
├── fiorino/            codice        ├── bronze/      raw immutabile
│   └── data/db/migrations/  schema   │   └── raw/source=…/competition=…/season=…/
├── configs/                          │        run=<run_id>.parquet
│   └── identity/ledger.json  ← input ├── manifests/   versioni + HEAD
├── test/fiorino/fixtures/  fixture   │   ├── ds_<data>_<hash>.json
└── .github/workflows/                │   ├── ds_<data>_<hash>.ledger.json
                                      │   └── HEAD
                                      └── warehouse/   DuckDB ricostruibile
```

Il root è `$FIORINO_DATA_ROOT`, con default `~/.fiorino/data` — **fuori dal
working tree**, così il dataset resta fuori da git per costruzione e non per
disciplina. Il layout è agnostico rispetto allo storage: DuckDB legge e scrive
Parquet su `s3://` e `gs://` via httpfs, quindi spostare il root su object
storage cambia una funzione e nient'altro.

---

## 2. Come viene versionato il bronze

Il bronze non viene versionato: **è append-only e immutabile**. Ogni fetch
scrive una partizione nuova con la propria `run_id`; nessun file viene mai
riscritto. `write_bronze` solleva `FileExistsError` se il file esiste.

Ciò che viene versionato è il **manifest**: l'insieme esatto dei file che
compone un dataset, ciascuno con il proprio SHA-256.

---

## 3. Come si identifica una versione del dataset

Una versione è un **hash di contenuto su entrambi gli input**:

```
ds_20260908_a8ebda082445
   │        └─ blake2b su [ path:sha256 di ogni file bronze ] + identity_digest
   └─ data, per ordinamento umano
```

Stesso contenuto → stessa versione, sempre. Contenuto diverso → versione
diversa, sempre. Ri-aggiudicare un club cambia la versione **senza cambiare un
byte di bronze**, ed è corretto che sia così.

Il manifest registra: file e hash, versione genitore, sha del codice, digest
del ledger, **digest logico** del dataset risultante, esito dell'audit.

---

## 4. Come si fa rollback

```console
$ fiorino versions
* ds_20260908_1297081abe0e  2 files  audit=PASS
  ds_20260908_a8ebda082445  1 files  audit=PASS

$ fiorino rollback --to ds_20260908_a8ebda082445
HEAD -> ds_20260908_a8ebda082445
  logical digest f6619c08852ba4176bb55d6c291b55fb matches the recorded value
  identity ledger restored from ds_20260908_a8ebda082445.ledger.json
```

Verificato in vivo: dopo il rollback il warehouse contiene `['ITA_SA']` e 380
partite; tornando avanti, `['ITA_SA','PRT_L1']` e 686.

Tre proprietà lo rendono esatto:

1. **Il rebuild legge solo i file che il manifest nomina**, non un glob. Bronze
   arrivato dopo non entra: altrimenti una vecchia versione acquisirebbe dati
   nuovi e smetterebbe di essere ciò che dichiara.
2. **Il ledger viene ripristinato** dalla copia congelata accanto al manifest.
   Senza, si rigiocherebbe vecchio bronze sotto le aggiudicazioni di oggi.
3. **Il digest logico viene confrontato** prima di spostare HEAD. Se non
   corrisponde, il rollback fallisce invece di produrre qualcosa etichettato
   male. *(Questo è successo davvero in fase di test, prima che il ledger
   venisse congelato per versione — il sistema se n'è accorto.)*

---

## 5. Come si verifica che il rebuild produca lo stesso dataset logico

```console
$ fiorino verify
ds_20260908_1297081abe0e: 2 files, integrity OK
  logical digest MATCHES: 9316d56a7bb558f034886617486c87e4
```

Due controlli distinti:

**Integrità** — ogni file elencato viene ri-hashato. È ciò che rende
«immutabile» un'affermazione verificata anziché una convenzione. Provato
manomettendo un file: `integrity FAILED — size changed: …`.

**Equivalenza logica** — `logical_digest()` fa l'hash della proiezione
canonica di match, risultati, squadre, membership e source id, confrontando i
**nomi canonici** e non i `team_id`, che sono surrogati casuali e cambiano
legittimamente fra due build.

> Come concordato: **semanticamente identico, non byte-identical**. La
> rappresentazione fisica di DuckDB varia fra versioni e build, e prometterne
> l'uguaglianza sarebbe una promessa che il motore di storage non fa.

---

## 6. Il workflow, corretto

```
06:15 UTC
   ↓
FETCH ──► BRONZE STORAGE (append, mai commit)
   ↓
REBUILD DuckDB (in staging, poi swap atomico)
   ↓
DATA QUALITY AUDIT
   ↓
├── OK   → pubblica versione + aggiorna HEAD
└── FAIL → nessuna versione, ALERT
```

Il repository riceve **solo** il ledger d'identità e il riassunto dell'audit:
kilobyte, leggibili, revisionabili in un diff. Mai il bronze.

Il gate è reale: durante il test una nuova lega ha portato due nomi non
aggiudicati e `snapshot` ha rifiutato di pubblicare, lasciando le partite in
quarantena invece di scartarle in silenzio.
