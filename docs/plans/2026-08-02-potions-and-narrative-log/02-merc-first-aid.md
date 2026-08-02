# P2 — Merc first aid: Alt+NUM below 50%

Size: sm. Dependencies: P1 preferred first (uses its type-search).

## Changes

1. **Alt-chord input** (`input.py`): a guarded chord primitive — hold
   Alt, wait one frame, press the belt key, release both, in that
   order. The Shift+click race (P3, "when the tools lie") is the
   design constraint: the modifier must provably be down before the
   key. Same gate as every world send (`GatedInput`, no bypass).
2. **The rung** (`behavior/reflex.py`): upkeep-tier, BELOW every
   player-survival rung and above the armor upkeep. Trigger:
   `snap.merc` is not None, alive, `hp/max_hp < merc_heal_below_pct`
   (new ReflexConfig field + `config/necro.toml` key, default 50.0,
   user's number, R179). Action: Alt+<key> of a column holding a
   healing potion (P1's type search). Paced via `on_attempt`
   (`merc_heal_retry_s`, default 3.0) — the stage-B-run-9 rule: a
   failing send must not refire at tick rate. Never in town (the
   preamble heals the merc there).
3. **Loader** (`behavior/combat.py`): the two new `[reflex]` keys in
   `_REFLEX_NUMBERS`; TOML gets them with a comment citing R179.

## Tests

- Fires at 49%, not at 51%; never with no merc or a dead one; never in
  town; pacing holds across failed sends; a belt with healing only in
  the "wrong" column still serves the merc (P1 integration); the
  player's own rejuv rung outranks it when both trigger.

## Reminders

Do not commit unless asked · numbers are the user's (50%) — do not
tune · stop if blocked · report.

## Validation

```powershell
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m pytest -q
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m ruff check .
```

Done when: the scripted scenarios pass, suite green, ruff clean.
