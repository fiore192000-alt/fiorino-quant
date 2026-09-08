# Identity ledger

`ledger.json` is the human decision log for team identity: which canonical
clubs exist, which source names map to them, which overrides were applied, and
which fuzzy proposals were accepted or rejected.

**It is committed on purpose.** A dataset has two inputs — raw bronze and these
decisions — and only one of them can be regenerated. Bronze can always be
re-fetched; a thousand adjudications cannot. It is also small, sorted and
diffable, so a pull request shows exactly which identity call changed.

The bulk data does not live here. See `fiorino/config/storage.py`.

## Reviewing a change

A diff that adds a team is routine — a promoted club, a new season. A diff that
*moves* an alias between teams deserves a second look: that is the shape of a
merge that should not have happened. On real data the fuzzy matcher proposes
Manchester United and Manchester City as the same club at 0.926, so this file
is the last line of defence against exactly that.
