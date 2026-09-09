# Modulo di registrazione dell'esperimento

Si compila **prima** di guardare i dati. Una volta registrato, nessun campo
sopra la linea si modifica: se serve cambiarli, è un esperimento nuovo con un
id nuovo, e quello vecchio resta a registro con il suo esito.

Copiare in `docs/research/experiments/EXP-NNNN.md`.

---

```yaml
# ─────────── REGISTRATO PRIMA DI VEDERE I DATI ───────────
hypothesis_id:        EXP-0000
registered_at:        YYYY-MM-DDTHH:MM:SSZ
registered_by:
status:               REGISTERED     # REGISTERED | RUNNING | CLOSED

hypothesis: >
  Una frase. Che cosa sarebbe vero nel mondo se questa ipotesi fosse vera.

economic_mechanism: >
  PERCHE il mercato dovrebbe sbagliare qui. Se non si sa dire, l'ipotesi e
  data mining con una storia intorno. Un mercato non sbaglia per caso: o
  l'informazione arriva tardi, o e costosa da trattare, o chi la tratta non
  puo scommettere abbastanza.

data_required:
  - source:
    fields:
    timestamped:      true | false     # false => DATA GAP, non si procede
    available_from:
    coverage:

decision_timestamp: >
  L'istante in cui la decisione si prende. Ogni fatto usato deve precederlo.

prediction_horizon:
universe:                              # campionati, stagioni, mercati
sample_size_expected:
minimum_detectable_effect: >
  Calcolato PRIMA. Un esperimento che non puo rilevare l'effetto che cerca e
  gia fallito, e costa lo stesso.

control: >
  Contro che cosa si confronta. "Nessun controllo" non e ammesso: il mercato si
  muove comunque, mediana 2,29 punti di probabilita fra prematch e chiusura.

baselines:
  - MARKET
  - MARKET + FIORINO_BASELINE
  - MARKET + CANDIDATE

primary_metric:                        # una sola
secondary_metrics: []

multiple_testing_family: >
  A quale famiglia appartiene questo test, e quanti test contiene.

replication_requirement:
  leagues:            2
  periods:            2

stop_rule: >
  Che cosa fa dichiarare NO EVIDENCE. Scritto ora, non dopo.

# ─────────── COMPILATO DOPO L'ESECUZIONE ───────────
git_commit:
dataset_version:
random_seed:
environment:

result:
  n:
  point_estimate:
  ci_low:
  ci_high:
  p_value:
  q_value:                             # dopo Benjamini-Hochberg
  clv_mean:
  clv_t:
  clv_definitional_component: >
    Obbligatorio se il CLV e positivo. Vedi PROMOTION_GATES gate 4.

gates:
  pit:                  PASS | FAIL
  calibration:          PASS | FAIL | N/A
  incremental:          PASS | FAIL
  clv:                  PASS | FAIL
  robustness:           PASS | FAIL | NOT_REACHED
  economics:            PASS | FAIL | NOT_REACHED

adversarial:                           # solo se i gate 1-4 passano
  other_bookmaker:
  other_devig:
  drop_one_season:
  drop_one_league:
  drop_top_team:
  drop_outliers:
  by_price_band:
  alternative_control:
  placebo_event:
  temporal_stability:

outcome: >
  DATA GAP | NO EVIDENCE | UNREPLICATED | NO INCREMENTAL EDGE | CANDIDATE

decision: >
  PROMOTE | REPLICATE | REJECT | WAIT FOR DATA

notes: >
  Compreso cio che e andato storto e cio che si e imparato sullo strumento.
  Un difetto trovato dallo strumento vale quanto un risultato: in M6.5 un
  controllo positivo ha trovato un difetto nello scanner invece di un bias
  nel mercato, e quella era la cosa piu utile che potesse fare.
```
