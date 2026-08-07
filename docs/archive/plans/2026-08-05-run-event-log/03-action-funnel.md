# P3 — The action funnel

Part of [plan.md](plan.md). Size: `sm`. Dependencies: P1, P2.
Review gate: none.

## Scope

Every action the bot actually sends becomes an event, emitted from the
one place they all pass through.

Covers from the user's brief: movement commands (with both coordinate
frames), attack commands, all spellcasting, potion drinking, merc potion
feed. Item collection and interaction are emitted here as *attempts*;
their outcomes (collected, accidental) come in P7.

Out of scope: town/waypoint/stash/chicken layers (P6), perception-derived
events (P7), tick records (P4).

## Why one place

`GameActionExecutor._record(action, detail)` is already the single funnel
for `MoveTo`, `AttackUnit`, `CastAtPoint`, `CastSelf`, `PickUpItem`,
`InteractObject`, `DrinkPotion`, `GiveMercPotion` and `ParkSkill` — every
action reaches the game through `execute()` and every path calls
`_record`. Instrumenting there covers most of the user's list at one
site and, more importantly, **cannot be forgotten by a future action
type**: a new action that skips `_record` has no trace today either, so
the invariant is already load-bearing.

## Implementation

1. **Wire the log into the executor.** `GameActionExecutor` takes a
   `runlog` (defaulting to `NullRunLog`) and a `frame` provider (P2).
   `wiring.py` passes the real one; `RecordingExecutor` gets the same
   parameter so the sim can exercise it.

2. **Emit per action type**, at `_record` time — i.e. *after* the send
   completed, so an event means "this reached the game", and a refusal
   is a different event (P4 records those):

   | Action | Kind | Fields beyond the standard envelope |
   |---|---|---|
   | `MoveTo` | `action.move` | `target` (P2 `describe`), `toward` unit id when set, `blocking` |
   | `AttackUnit` | `action.attack` | `unit_id`, `target`, monster kind + `super_unique` id when readable |
   | `CastAtPoint` | `action.cast` | `skill_id`, `skill_name`, `target` |
   | `CastSelf` | `action.cast_self` | `skill_id`, `skill_name` |
   | `PickUpItem` | `action.pickup_attempt` | `unit_id`, `item_kind`, `item_name`, `target`, `attempt`, `aim_offset` |
   | `InteractObject` | `action.interact` | `target`, object kind + name when readable, `click_screen` |
   | `DrinkPotion` | `action.drink` | `column`, `potion_type`, `hp`, `max_hp`, `mana`, `max_mana` |
   | `GiveMercPotion` | `action.merc_feed` | `column`, `merc_hp_pct` |
   | `ParkSkill` | `action.park_skill` | `skill_id`, `skill_name` |

   Every `target` is a P2 `describe(...)` payload: world, area-local,
   character-relative, distance, bearing. That is the user's "relative
   AND absolute coordinates" requirement, satisfied uniformly rather
   than per call site.

3. **Record the screen point for clicks.** `click_world` already returns
   the projected screen point; carry it on `action.interact` and
   `action.pickup_attempt` as `click_screen`. This is directly load
   bearing for the open Tower question — whether a staircase click aims
   where it should — and it costs nothing, since the value is already
   computed and thrown away.

4. **Skill names** from the class config's `[skills]` table, reversed
   (id → name). Fall back to `skill <id>` — never guess.

5. **Item names** via a reverse lookup over the existing
   code-anchored tables (Q5): add `ItemTable.name_for(kind)` in
   `pickit.py` returning the verified name or `None`. The log formats
   `None` as `kind <n>`. Never invent a name (R144).

## Testing

- Each action type emits its kind with the expected fields, driven
  through `RecordingExecutor` with a capturing log.
- `MoveTo` carries all three frames and a bearing.
- A `DrinkPotion` event carries HP and mana as read at send time (the
  user asked for vitals on every potion event).
- An unnamed item kind renders `kind 1234`, not a guess.
- The sim (`python -m tests.simworld countess`) produces a log whose
  event count matches its executor trace length — the instrument agrees
  with the thing it instruments.

## Style and conventions

- The emit must not change execution order or timing semantics: log
  after `_record`, never between a guard and its send.
- Never raise from the emit path (P1's rule).
- Comments cite why the funnel is the right site.

## Docs

Add the emitted kinds to the running schema list (finalized in P7).

## ADR expectation

**None.**

## Agent reminders

- Do not commit unless asked.
- Do not change what any action does — this phase only observes.
- Do not add a second naming path for items or skills.
- Do not suppress warnings or disable tests.
- Stop and report if any action type turns out to bypass `_record`.
- Report what changed, what was validated, and any deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

## Definition of done

Every action type emits a schema'd event with full coordinates; the sim
produces a log consistent with its trace; suite green and ruff clean.
