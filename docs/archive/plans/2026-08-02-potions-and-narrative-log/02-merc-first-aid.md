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

## Implementation Result

Status: done
Completed: 2026-08-02
Commit: pending

- Changed: `input.py` (`VK_MENU`, `press_key_with_alt` — gated chord, Alt
  settled down before the key, release in a `finally`), `skills.py`
  (`belt_give_merc`), `behavior/actions.py` (`GiveMercPotion`),
  `behavior/execute.py` (keypress path, before the cast check like
  DrinkPotion), `behavior/reflex.py` (rung 7.5 merc_heal: below every
  player rung, above armor upkeep; paced on attempt; never in town; uses
  P1's type search), `behavior/combat.py` (loader keys),
  `config/necro.toml` (merc_heal_below_pct = 50.0, merc_heal_retry_s =
  3.0 — R179, the user's numbers).
- Tests: fires at 49% not 50/51; dead merc/no merc quiet; town quiet;
  pacing across failed sends; wrong-column healing serves the merc;
  player rejuv outranks; chord ordering + gate + stuck-Alt release;
  executor chord test + never-queues-behind-a-cast test.
- Validated: full suite 801 passed, ruff clean.
- Deviations: none.
