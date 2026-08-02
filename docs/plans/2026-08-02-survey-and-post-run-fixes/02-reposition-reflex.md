# P2 — Damage-while-stationary reposition reflex

Size: sm. Dependencies: none. Parallel-safe with P1.

## Why

The R173 run stood in ground fire (invisible to perception — no unit to
see) until chicken fired at 49%. Nothing in the ladder says "you are
slowly losing health and not moving; stand somewhere else." User
observation: *"If the character takes damage, they should consider
repositioning soon, even if it's low damage."*

## Numbers (user-approved, R176 Q3 — do not change without a request)

- Trigger: ≥2% of max HP lost within the last 2.5 s AND the character
  moved <3 subtiles over that same window.
- Action: one `MoveTo` 10 subtiles away — `retreat_point` away from
  hostiles when any are visible, otherwise rotate through walkable
  candidate directions (the shake-loose angle pattern).
- Cooldown: 2 s between fires.
- Rank: BELOW rungs 3-6 (rejuv, warp, heal, mana) and above rung 7
  (armor). Emergencies always win the tick.

## Changes

- `pd2bot/behavior/reflex.py`: new config fields on `ReflexConfig`
  (`reposition_loss_pct`, `reposition_window_s`,
  `reposition_still_subtiles`, `reposition_step`,
  `reposition_cooldown_s`) with defaults above; position-history
  tracking alongside the existing `_hp_samples` (record position with
  each sample — extend the sample tuple rather than adding a parallel
  deque); the rung in `evaluate` after mana, rung name `"reposition"`.
  Direction: reuse `retreat_point` when hostiles exist; else pick the
  first walkable of 8 rotated candidates — the ladder has no grid, so
  "walkable" here means "emit the MoveTo and let the navigator handle
  it" (the navigator already absorbs unreachable targets; a failed
  reposition costs nothing).
- `config/necro.toml` `[reflex]`: the five keys, with the approved
  values and a comment citing R176 Q3.
- `pd2bot/behavior/combat.py` config loader: add the keys to the
  required-fields table (same pattern as the existing reflex keys).

## Tests (tests/test_reflex*.py — follow existing ladder test style)

- Chip damage while stationary → `reposition` fires with a MoveTo ~10
  away; moving during the window → does not fire; damage above the
  rejuv/warp thresholds → those rungs fire instead (rank respected);
  cooldown holds; in town → never fires.

## Reminders

Do not commit unless asked · no scope creep · numbers are frozen by
R176 Q3 · stop if blocked · report changes + validation.

## Validation

```powershell
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m pytest -q
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m ruff check .
```

Done when: the scripted scenarios pass, full suite green, ruff clean.
