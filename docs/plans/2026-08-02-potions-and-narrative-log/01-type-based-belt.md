# P1 — Type-based belt: drink anywhere, refill by minimums, halt only for real failures

Size: sm. Dependencies: none.

## The rule (user, R179 — the contract this phase implements)

Full belt when possible; >=1 column-equivalent each healing/mana/rejuv
when stock allows; fourth column don't-care; column ORDER must never
matter; emptiness is normal and never a crash or a needless halt.

## Changes

1. **Drink by type, not column** (`behavior/reflex.py`): where a rung
   drinks (`_column_potion` + `DrinkPotion(cfg.X_column, ...)`), search
   ALL four columns for the needed type — configured column first (it
   is still the preferred home), then the others. The belt read already
   carries per-column occupants; the change is the search, and
   `DrinkPotion` already takes the column to press.
2. **Refill by type minimums** (`town.py` `fill_belt` and the
   "belt below minimum after refill" halt): count column-equivalents
   per TYPE across the whole belt (misplaced potions count where they
   SIT); top up gaps from inventory/stash stock by type; the configured
   layout remains the preference for where new potions go, never a
   requirement for what is already there. The halt narrows to: a type
   minimum unmet AND matching stock existed that could not be loaded
   (clicks failing = mechanical failure worth a human). Unmet minimum
   with NO stock = a loud log line and continue (user: normal).
3. **Config**: type minimums already exist (`min_healing` etc., single
   source in the class config, review 004); reuse them — no new keys.

## Tests

- Ladder: rejuv in the "wrong" column still gets drunk when rung 3
  fires; the configured column is preferred when both hold the type.
- Town (fakes): the exact R178 belt — mana potion in a healing column —
  refills around it and does NOT halt; a click-failure refill (fake
  refuses the move) still halts; an empty-stock refill logs and
  continues.
- No regression: the existing belt/refill suites.

## Reminders

Do not commit unless asked · no scope creep (no column re-sorting) ·
stop if blocked · report changes + validation.

## Validation

```powershell
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m pytest -q
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m ruff check .
```

Done when: the R178 shape passes as a test, suite green, ruff clean.
