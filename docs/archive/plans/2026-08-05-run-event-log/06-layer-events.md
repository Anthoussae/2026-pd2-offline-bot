# P6 — Layer events

Part of [plan.md](plan.md). Size: `sm`. Dependencies: P1, P2.
Independent of P5. Review gate: none.

## Scope

The events that live in the stateful layers rather than in the action
funnel: town chores, the stash, NPCs, the waypoint, area transitions,
chicken, and the vitals-bearing survival actions.

Out of scope: perception-derived events (P7), enemy deaths (deferred,
Q6).

## Implementation

Each layer takes a `runlog` (defaulting to `NullRunLog`) the way it
already takes `narrate`, wired in `wiring.py`.

### Town (`town.py`)

| Kind | When | Fields |
|---|---|---|
| `stash.deposit` | each item that provably left the inventory | `item_kind`, `item_name`, `quality`, `sockets`, `tab`, `cell`, `attempts` |
| `stash.gold` | gold deposited | `amount`, `before`, `after` |
| `stash.refused` | an item that would not go in after its retries | `item_kind`, `item_name`, `attempts`, `reason` |
| `npc.interact` | `open_npc_dialog` / `open_object_panel` succeeds | `npc`, `kind`, `panel`, `position` (describe), `requested: true` |
| `npc.accidental` | a panel/dialog opened that nobody requested (Q7) | `panel`, `names`, `recovered` |
| `inventory.cleanse` | a cleanse runs | `dropped`, `kept`, `position` (describe), `items` (kind + name each) |
| `preamble.station` | each station completes | `station`, `dur_s`, `outcome` |

`npc.accidental` is the existing stray-panel concept (`_clear_stray_ui`,
`recover_panels`) finally *named*: nothing in the field opens a panel on
purpose, so one being open is an accident, and it has cost real runs
(stage B's tenth attempt; the tome misclick). Same for the R117
accidental pickup, which P7 covers.

### Waypoint (`waypoint.py`)

| Kind | When | Fields |
|---|---|---|
| `waypoint.open` | the panel is verified open | `position` (describe), `attempts` |
| `waypoint.tab` | an act tab is clicked | `act`, `point`, `fraction` |
| `waypoint.select` | a destination row is clicked | `dest_area`, `dest_name`, `point`, `fraction` |
| `waypoint.arrived` | the area id proves arrival | `dest_area`, `dest_name`, `dur_s`, `arrival` (describe) |

### Area transitions (`steps.py`)

| Kind | When | Fields |
|---|---|---|
| `area.transition` | an area id change is proven | `from_area`, `from_name`, `to_area`, `to_name`, `via` (`staircase`/`waypoint`/`unknown`), `exit_position` (describe), `arrival` (describe), `dur_s`, `clicks` |

The user asked specifically for departing *and* target area names, so
both ids and both names are recorded, from `offsets.AREA_NAMES` with an
honest `area <n>` fallback.

### Safety (`safety.py`) and reflex (`reflex.py`)

| Kind | When | Fields |
|---|---|---|
| `chicken` | the monitor fires | `reason` (`life`/`mana`), `hp`, `max_hp`, `hp_pct`, `mana`, `max_mana`, `threshold`, `area`, `position` |
| `death` | the death latch trips | `hp`, `area`, `position` — the run's last event |
| `reflex.potion` | a drink rung fires | `rung`, `column`, `potion_type`, `hp`, `mana` (before) |
| `reflex.merc_feed` | the merc rung fires | `column`, `merc_hp_pct` |
| `reflex.escape` | blood warp | `from` (describe), `to` (describe), `hp`, `mana`, `trigger` |
| `reflex.armor` | armor recast | `absorb_pct`, `mana` |

Vitals on every one of these, per the user's brief. The `chicken` and
`death` events matter most: they are the two moments the operator most
wants a precise record of, and today the chicken reason is a printed
string that survives only in a drill capture.

## Testing

Each layer's existing tests gain a capturing log and assert the event
and its fields. Specifically:

- A stash deposit of three items emits three `stash.deposit` events with
  resolved names.
- A stray panel emits `npc.accidental`, not `npc.interact`.
- A waypoint trip emits open → tab → select → arrived in order.
- A traverse emits exactly one `area.transition` with both names.
- A chicken emits vitals matching the snapshot that triggered it.

## Style and conventions

- Layers take the log the same way they take `narrate` — a callable/
  object defaulting to silence, never a global.
- Names resolved through the existing tables; honest fallbacks.
- Never raise from an emit.

## Docs

Running schema list; `docs/architecture/game-cycle.md` gains a note that
chicken and death are now recorded events.

## ADR expectation

**None.**

## Agent reminders

- Do not commit unless asked.
- Do not change town, waypoint or safety behavior — observe only. The
  safety invariant (after a detected death the bot sends no input, ever)
  is untouchable; the `death` event is written by the monitor that
  already latched, not by a new code path.
- Do not suppress warnings or disable tests.
- Stop and report if wiring a log into a layer would change its
  constructor in a way that ripples through the cycle.
- Report what changed, what was validated, and any deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

## Definition of done

Every layer event in the tables above is emitted and tested; a sim run's
rendered log shows the town chores, the waypoint trip and the area
transitions as a readable sequence; suite green and ruff clean.
