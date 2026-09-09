# Archivio delle formazioni

Una riga JSON per poll, un file per giorno UTC: `YYYY/MM/DD.jsonl`.

**Append-only.** Un poll è un fatto su un istante e non si modifica dopo. Non
riscrivere questi file, non riordinarli, non deduplicarli a posteriori: un poll
che non ha trovato niente è l'evidenza che rende misurabile l'incertezza del
poll successivo, e cancellarlo allarga silenziosamente un intervallo che
qualcuno userà come se fosse stretto.

Sta dentro il repository — a differenza del bronze storico, che ne sta fuori —
per una ragione sola: l'orario del commit è un'attestazione di `observed_at`
fatta da GitHub e non da noi. Un istante di prima osservazione garantito solo
da chi lo ha scritto vale sensibilmente meno.
