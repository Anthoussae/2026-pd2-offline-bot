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

## Implementation Result

Status: done
Completed: 2026-08-02
Commit: pending

- Changed: `behavior/reflex.py` (`_potion_column` type search; rungs 3/5/6
  drink from whichever column holds the type, configured column preferred;
  module docstring updated to the R179 contract), `town.py`
  (`assert_belt_minimums` narrowed: halts only when a short type has
  inventory stock AND a column that would take it — otherwise loud notice
  and continue; `refill_belt` delegates to it; new `_belt_accepts`),
  `offsets.py` (`BELT_ROWS = 4`).
- Tests: fake upgraded from per-type capacity to honest column routing
  (squatters cost their slot); R178 mixed-belt, fully-squatted,
  click-failure, no-stock, and charm-space cases; 4 reflex type-search
  tests. Two old tests updated to the new contract (no-stock halt ->
  notice-and-continue).
- Validated: full suite 788 passed, ruff clean.
- Deviations: "inventory/stash stock" in the phase file — stock is counted
  from the main inventory only, because the refill can only reach the
  inventory (no stash-withdrawal machinery exists; potions are never
  stashed by policy). A stash-only restock still produces the notice, not
  a halt.
