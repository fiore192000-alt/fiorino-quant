# Registro delle ipotesi

Tutto ciò che è stato testato, con l'esito. **I risultati negativi non si
cancellano**: il registro esiste perché la stessa idea non venga riprovata dieci
volte cambiando soglia finché una versione passa.

Aggiornare **prima** di eseguire (stato `REGISTERED`) e di nuovo dopo
(`CLOSED`).

---

## Stati di un esperimento

Un esperimento non è «riuscito» o «fallito». Attraversa stati, e ognuno ha una
condizione di uscita scritta prima.

```
  REGISTERED ──► RUNNING ──┬──► NEGATIVE ──────► (resta a registro, per sempre)
                           │
                           ├──► PROMISING ──► REPLICATED ──► PROMOTED
                           │         │              │
                           │         └──► NEGATIVE  └──► NEGATIVE
                           │
                           └──► FAILED  (l'esperimento non è stato eseguibile,
                                         non è un risultato: di solito DATA GAP)
```

| stato | significa | come si esce |
|---|---|---|
| `REGISTERED` | ipotesi scritta, dati non ancora guardati | eseguendo |
| `RUNNING` | in esecuzione | dal risultato |
| `FAILED` | non eseguibile — di norma DATA GAP | acquisendo il dato |
| `NEGATIVE` | eseguito, nessuna evidenza | **non si esce.** Resta |
| `PROMISING` | positivo su un campione | replica |
| `REPLICATED` | 2 campionati e 2 periodi | suite avversariale |
| `PROMOTED` | tutti e sei i gate | va al paper trading |
| `RETIRED` | promosso e poi decaduto | resta a registro con la data |

`NEGATIVE` non è uno stato transitorio. Un esperimento negativo si ripropone
solo dichiarando **cosa è cambiato** — dati nuovi, campione maggiore, meccanismo
diverso — mai una soglia diversa.

---

## Famiglie di test multipli

Una famiglia è l'insieme entro cui si applica Benjamini-Hochberg. Le famiglie
non si ridefiniscono dopo aver visto i risultati.

| famiglia | contenuto | m | correzione |
|---|---|---|---|
| `F-MODEL` | modello contro mercato, M5 | 10 dataset × 2 metriche | riportato per dataset |
| `F-ENSEMBLE` | informazione incrementale, M6 | 20 (10 dataset × 2 esperimenti) | CI appaiato |
| `F-SITUATIONS` | scansione situazioni | 41 | Benjamini-Hochberg q = 0,10 |
| `F-LINEUP` | event study formazioni | non ancora eseguita | BH, q = 0,10 |

---

## Chiuse

| id | ipotesi | famiglia | esito | evidenza |
|---|---|---|---|---|
| **EXP-0001** | Un Dixon-Coles addestrato in walk-forward batte la chiusura de-viggata | `F-MODEL` | **NO INCREMENTAL EDGE** | mercato migliore in **10/10** dataset; Brier medio −0,01012. [M5](../validation/model-validation.md) |
| **EXP-0002** | `MARKET + MODEL` batte `MARKET` | `F-ENSEMBLE` | **NO INCREMENTAL EDGE** | 0/10; **tutti e 20 i CI contengono lo zero**, 18/20 stime peggiori. Peso ottimo non vincolato **negativo in 5/10**, fino a −0,51. [M6](../validation/incremental-information.md) |
| **EXP-0003** | Il modello trova value sfruttabile a soglie di EV crescenti | `F-MODEL` | **NO EVIDENCE** | CLV negativo **30 volte su 30**, e peggiore del controllo senza opinione in 7/10 |
| **EXP-0004** | Il riposo breve è mal prezzato (casa e trasferta) | `F-SITUATIONS` | **NO EVIDENCE** | non supera BH; \|z\| max 1,99 |
| **EXP-0005** | Il vantaggio relativo di riposo è mal prezzato | `F-SITUATIONS` | **NO EVIDENCE** | n_in 105–113, nessuna replica |
| **EXP-0006** | La congestione (3ª partita in 8 giorni) è mal prezzata | `F-SITUATIONS` | **NO EVIDENCE** | non supera BH |
| **EXP-0007** | Le partite senza obiettivi di classifica sono mal prezzate | `F-SITUATIONS` | **NO EVIDENCE** | n_in = 60, potenza insufficiente. Approssimazione dichiarata |
| **EXP-0008** | Infrasettimanali e periodo festivo sono mal prezzati | `F-SITUATIONS` | **NO EVIDENCE** | \|z\| max 1,74 |
| **EXP-0009** | Le prime giornate sono mal prezzate | `F-SITUATIONS` | **NO EVIDENCE** | z = 2,16 grezzo, **q = 0,77** dopo correzione. Replica 4/6 |
| **EXP-0010** | Il bias favorito-longshot è presente su Pinnacle 1X2 | `F-SITUATIONS` | **NO EVIDENCE** | Il de-viggato segue la frequenza in ogni banda, \|z\| max 1,38. Sul grezzo il margine cresce verso i **favoriti**, non verso i longshot |
| **EXP-0011** | I movimenti prematch→chiusura contengono informazione sfruttabile | `F-MODEL` | **NO EVIDENCE utile** | segno negativo in 10/10 (effetto **reale**), ma significativo in 1/10 e vale **0,00099 Brier** — un decimo del divario del modello |

### Potenza dichiarata

`F-SITUATIONS`: effetto minimo rilevabile **0,039–0,072** punti di probabilità.
Quindi tutti i `NO EVIDENCE` sopra significano **«nessun effetto più grande di
~4–7 punti»**, non «nessun effetto». Un bias di 2–3 punti sarebbe altamente
profittevole e resta sotto la soglia.

---

## Ritirate

Affermazioni che il laboratorio ha fatto e poi smentito da sé. Restano qui
perché sono la prova che il metodo funziona.

| affermazione | perché sembrava vera | perché è falsa |
|---|---|---|
| Asimmetria HOME/AWAY nel drift (−0,0043 / +0,0045) | solida su ENG_PL 2017-18 | non replica: AWAY positivo in 4-5/10, medie quasi identiche |
| «Firma della miscalibrazione»: lo yield decresce con la soglia | vera su un dataset | decresce in 4/10; solo le medie aggregate sono monotone |
| Baseline CLV −0,028, t −10,66 come costante | una stagione | varia da −0,029 a −0,065 |
| «Non manca una feature, manca una classe di informazione» | il divario è 10× | misura la **taglia** del divario, non la sua **composizione** |
| Il rapporto divario/canale è 12× | due numeri plausibili | mescolava campioni; sugli stessi 10 dataset è **10,2×** |

---

## Aperte

| id | ipotesi | stato | blocco |
|---|---|---|---|
| **EXP-0012** | La pubblicazione delle formazioni muove il mercato oltre il movimento normale | `REGISTERED` | **DATA GAP** — nessuna fonte con istante di pubblicazione |
| **EXP-0013** | L'effetto varia per categoria (portiere, attaccante, difensore, assenze multiple, XI a sorpresa) | `REGISTERED` | **DATA GAP** + potenza: servono 600–1.000 partite, non 200 |
| **EXP-0014** | Il movimento residuo dopo le formazioni predice l'esito oltre la chiusura | `REGISTERED` | dipende da EXP-0012 |

---

## Mai proposte di nuovo senza una ragione nuova

Riproporre una di queste richiede di dichiarare **che cosa è cambiato** — dati
nuovi, campione maggiore, meccanismo diverso — non una soglia diversa.

* «Un modello di gol più sofisticato batterà il mercato.» → EXP-0001, EXP-0002.
  Serve una **fonte informativa** nuova, non un algoritmo nuovo.
* «CatBoost / LightGBM / stacking risolveranno il problema.» → in M6 **un solo
  parametro**, vincolato a [0,1], stimato su duecento partite, ha migliorato il
  training e non il fuori campione. Più capacità nasconde quel fenomeno, non lo
  risolve.
* «Il line shopping ha CLV positivo.» → EXP-0002, arm MARKET: definizionale.
  Decomposto, la parte reale è **negativa**.
