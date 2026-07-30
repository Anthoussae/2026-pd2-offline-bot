# P5 — Necro combat module and pickit

Part of [plan.md](plan.md) (M5). Size: `sm`. Dependencies: P1–P4.
Sequential per R50. **Sim only — no live input in this phase.**
**Review gate at the end: the go/no-go before anything runs live.**

## Scope

The offense and the loot: the necro combat module implementing the
user's skirmish pattern, desecrate→revive maintenance, target
selection, the human-readable pickit + pickup loop, and the Cold
Plains run definition exercised end-to-end against a scripted fake
game.

Out of scope: live execution of any of it (P6), vendor UI, stat-based
pickit rules (M6), TP tome / bone wall usage (future, low prio —
carry the note into behavior.md in P6).

## Context you need

- The R47 kit record in [notes.md](notes.md) — the skirmish pattern
  below is the user's own description of how this character fights;
  encode it, don't invent.
- P4's interfaces: `CombatModule` protocol, the reflex ladder (runs
  above everything here), `config/necro.toml`, the step registry.
- P1/P2 primitives: corpse detection, revive counting, verified
  skill switch (`ensure_right_skill` — **no cast on an unverified
  skill**), stand-still click, `GroundItem` (kind + quality only —
  the pickit's vocabulary is bounded by this).
- Left skill is permanently Poison Strike (R47.1a): offense is
  left-click on the monster; the right skill is for utility only.

## Design

### The skirmish pattern (`behavior/necro.py`)

Per engagement cycle, as the user fights it (R47.2):

1. **Contact**: hostiles within engage radius (config,
   default ~40 subtiles) → combat state.
2. **Wait for tanks**: if revives exist and haven't engaged yet,
   hold ~`wait_for_revives_s` (config, default 1.5 s) at range.
3. **Dash**: approach the selected target to melee range
   (~3 subtiles) via `walk_to` (short leash — abort approach if the
   ladder fires).
4. **Strike**: left-click the target monster (poison applies).
5. **Retreat**: run back out of the pack (`retreat_subtiles`,
   default ~12, away from hostile centroid, known-walkable).
6. **Re-armor** if the ladder says so; **repeat** until the pack is
   dead. Poison does the killing — target selection should prefer
   un-poisoned/healthiest-nearest targets rather than re-stabbing
   the same one every cycle: track last-strike time per unit id,
   re-strike after `restrike_s` (default 6 s) if still alive.

Target selection: nearest live hostile, preferring ones currently
targeting/adjacent to the player (stun-lock risk first), then
un-struck ones. Champions/bosses get no special handling in M5
(Cold Plains packs only; note for M6).

### Desecrate → revive maintenance (upkeep rung 8, out of town only)

When `revive_count < 3`: verified-switch F5, right-click open ground
near the player (not on a unit); poll for new corpses; then
verified-switch F6 and right-click corpse positions until revives
reach 3 or corpses run out (then desecrate again, bounded rounds).
Revives last ~300 s — the count check every tick self-heals expiry.
Never during rungs 3–7, never mid-dash, never in town (R47.4).

### Pickit (`pd2bot/pickit.py` + `config/pickit.toml`)

Human-readable and easily editable is an explicit requirement
(R46 Q3). TOML with comments; rules are small tables evaluated
top-down, first match wins, e.g.:

```toml
# Picked in order; first matching rule decides. "keep" goes to the
# stash in the town preamble; "belt" potions route to the belt.
[[rule]]
name = "rejuvs while belt short"     # R47.6: unbuyable — always worth it
kinds = ["rejuv_small", "rejuv_full"]
when_belt_rejuvs_below = 4
action = "belt"

[[rule]]
name = "quality loot"
qualities = ["rare", "set", "unique"]
action = "keep"

[[rule]]
name = "gold piles"
kinds = ["gold"]
min_gold = 500
action = "pick"
```

Kind names map to P1's id tables (the loader resolves names → ids;
unknown names fail loudly at load). Evaluator is pure and heavily
unit-tested. The pickup loop (a run step, `pickup`): for each
matching ground item, walk near, gated left-click the item, verify
it left the ground; potions verify via belt/inventory counts.
Inventory-full guard: if an item persists after bounded attempts and
free cells are exhausted, skip further non-belt pickups for the rest
of the game and log it loudly (the town preamble's stash deposit is
the durable fix next game).

### Clearance step (`clear_radius`)

From the arrival point (the Cold Plains waypoint): engage hostiles
within radius 150 (R46 Q2) until none remain alive in radius for
`clear_settle_s` (default 5 s). Movement between packs goes through
`walk_to` on the atlas+live grid; the never-idle invariant (P4) and
the full ladder run throughout. Opportunistic pickup of
rule-matching items during clearance is allowed (potions
especially); the dedicated `pickup` step sweeps afterwards.

### Sim acceptance (this phase's exit test)

A scripted fake-session run of the **entire Cold Plains run** —
preamble (fake town), waypoint, a choreographed Cold Plains with
packs, corpses, drops, a ladder-triggering damage spike, an
inventory-full moment — asserting the full decision trace: verified
switches before casts, ladder priority wins, desecrate/revive counts,
pickit decisions, clearance termination, `IdleBail` on a contrived
stall. This trace is the go/no-go artifact.

## Work items

1. `behavior/necro.py`: skirmish FSM, target selection, maintenance;
   config-driven numbers in `config/necro.toml`.
2. `pd2bot/pickit.py` + `config/pickit.toml` (starter list per the
   example above, reviewed at the gate) + loader/evaluator tests.
3. `pickup` and `clear_radius` step handlers registered with P4's
   engine; `runs/cold-plains.toml` completed.
4. The scripted end-to-end sim + its decision-trace report.
5. Unit tests throughout (pattern states, restrike bookkeeping,
   maintenance bounds, pickit evaluation incl. rejuv rule and
   first-match-wins, inventory-full guard).

## Review gate (end of phase) — go/no-go for live

Present to the user: the sim decision trace, the pickit file
contents, final `config/necro.toml` numbers (R49 defaults), and any
deviation. Ask explicitly: **go/no-go to begin P6's staged live
acceptance, and any threshold changes first?** Log as a 🔶 decision
request.

## Conventions and reminders

- Encode the user's pattern; where a judgment call is needed
  (engage radius, waits), make it a commented config default —
  never hardcode.
- No cast without a verified skill switch; no click without its
  gate; the ladder always outranks offense; monitor exceptions
  propagate untouched.
- Do not commit unless asked. Do not expand scope. No live runs —
  not even "one quick check": that is P6's ladder, behind the gate.
- Report what changed, the sim trace summary, deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

## Definition of done

Necro module, pickit, run steps and the Cold Plains run definition
complete and sim-proven end-to-end; decision trace produced; gate
question asked and answered; tests/lint green; zero live input sent.
ADR expectation: none new (P4's draft stands until P6).
