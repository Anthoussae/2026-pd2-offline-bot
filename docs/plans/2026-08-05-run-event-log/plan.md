---
kind: plan
size: md
depth: implementation
status: active
repo: 2026-pd2-offline-bot
created: 2026-08-05
adr: expected
---

# The run event log

A structured, machine-written record of everything a run does, so that
diagnosing a failure is reading data rather than reconstructing a story.

## Why `md`

Seven small phases, each independently shippable and testable, with one
live review gate in the middle (P5, the Forgotten Tower diagnosis). One
agent can run the whole thing end to end, but the phase boundaries are
real: the log core must exist before anything emits into it, and the
diagnosis must not start before the instrument is trustworthy.

## Goal

After this plan, any run — live or simulated — leaves behind a complete,
timestamped, schema'd record in a central directory, and a human can
read that record without an agent interpreting it for them.

The immediate use is the failure that motivated it: **the bot cannot
reliably cross an empty square room.** That is the template case for
every space in the game, and it must be fixed by debugging, never by
special-casing the room.

## Acceptance criteria

1. Every run writes `logs/runs/<YYYYMMDD-HHMMSS>-<runname>/events.jsonl`
   plus a `run.json` header, with no opt-in required (Q11).
2. Every event carries an ISO wall-clock stamp **and** monotonic seconds
   since run start (Q4).
3. Every spatial event carries world, area-local and character-relative
   coordinates, plus a compass bearing (Q3).
4. `python -m pd2bot.runlog <run-dir>` prints a readable timeline (Q1).
5. The events named in the user's brief are emitted: movement, attack,
   spellcast, item drop detected, item collected (with accidental flag),
   NPC interaction (with accidental flag), stash deposit (items + gold),
   waypoint panel/selection, area transition (departing + target names),
   inventory cleanse, potion drink / merc feed / chicken (with HP and
   mana). **Not** enemy deaths — deferred, Q6.
6. Per-tick timing is recorded: tick duration and the snapshot / ladder /
   step / send split (Q9).
7. A rerun of the Forgotten Tower produces a log that unambiguously
   identifies where the 144 s went, and the underlying defect is fixed.

## Scope

In: the log module, the coordinate frame, instrumentation of the
executor / engine / town / waypoint / safety / reflex / steps, the
renderer, the diagnosis and fix of the empty-room traversal.

Out: enemy-death events (Q6, deferred to future work); log pruning;
any behavior change not proven necessary by P5's diagnosis;
re-deriving the atlas/A* findings already proven in
`docs/plans/2026-08-03-m6-countess/navigation-diagnosis.md`.

## Discovery summary

See [notes.md](notes.md). The short version: five separate logging
surfaces exist, none of them persisted as data, none uniformly
timestamped — so T71's 144 s in an empty room produced five log lines
out of ~150 decisions, and the analysis that followed was guesswork.
The atlas and A* are proven innocent; routing was never even invoked in
that room, because the staircase was inside `click_range`.

## Files expected to change

**New:** `pd2bot/runlog.py` (event log + renderer), `pd2bot/mapframe.py`
(coordinate frames), `tests/test_runlog.py`, `tests/test_mapframe.py`.

**Changed:** `pd2bot/behavior/execute.py` (the action funnel),
`pd2bot/behavior/engine.py` (tick records, step decisions),
`pd2bot/behavior/steps.py` (decision notes, area transitions, revert of
`exit_block_radius`), `pd2bot/town.py` (stash, NPC, cleanse),
`pd2bot/waypoint.py` (panel, tab, selection, arrival),
`pd2bot/safety.py` (chicken), `pd2bot/behavior/reflex.py` (potions,
merc feed), `pd2bot/wiring.py` (open the log, pass the sink),
`pd2bot/snapshot.py` or a small observer for drop detection,
`pd2bot/pickit.py` (reverse name lookup), plus their tests.

## Documentation expected to change

- `docs/architecture/behavior.md` — the logging section.
- A new `docs/architecture/run-log.md` — the schema reference: every
  event type, its fields, and what it means. This is the document a
  future agent reads instead of guessing.
- `CLAUDE.md` — one line pointing at the log as the first stop when a
  run misbehaves.
- `docs/manual/` — how to read a run log.

## Architecture decisions

**ADR expected**: `docs/adr/2026-08-05-run-event-log.md` — the choice of
a schema'd, always-on, append-only JSONL event log as the run's system
of record, and the coordinate-frame convention. Lasting consequences for
every future diagnosis, and it establishes that instrumentation is not
optional. Written in P1.

Key decisions, all confirmed with the user (R220):

- JSONL + renderer, not prose (Q1).
- One directory per run under `logs/runs/`, everything kept (Q2).
- Three coordinate frames on every spatial event (Q3).
- Dual timestamps (Q4).
- Names from the existing code-anchored item tables, honest fallback
  (Q5).
- "Accidental" means an unrequested state change (Q7).
- The narrative log survives alongside (Q8).
- Timing instrumentation included (Q9).
- Logging is mandatory, not opt-in (Q11).

## Validation strategy

Per phase: `~/.venvs/pd2bot/Scripts/python.exe -m pytest -q` and
`~/.venvs/pd2bot/Scripts/python.exe -m ruff check .`. The sim
(`python -m tests.simworld countess`) must keep passing and must produce
a well-formed event log — the sim is the cheapest end-to-end check that
instrumentation did not break behavior.

P5 additionally validates live, against the real Forgotten Tower.

## Phases

| Phase | Size | Summary | Files/modules | Review gate |
|---|---|---|---|---|
| P1 ✅ | sm | Event log core: schema, JSONL writer, run directory, null sink, renderer, ADR. Revert `exit_block_radius` (Q10). | `pd2bot/runlog.py`, `docs/adr/`, `steps.py` | None |
| P2 ✅ | sm | Coordinate frames: world / area-local / character-relative + compass. | `pd2bot/mapframe.py` | None |
| P3 ✅ | sm | The action funnel: every executed action becomes an event with all three frames — movement, attack, cast, pickup, interact, potion, merc feed. | `execute.py`, `wiring.py` | None |
| P4 ✅ | sm | Tick and decision records: tick duration, snapshot/ladder/step/send split, every step's decision each tick, refusals. | `engine.py`, `steps.py` | None |
| P5 ✅ | sm | **The empty-room diagnosis.** DONE — the log named the defect on its first run: hostile MISDETECTION, not navigation. | T72/T73/T74 probes | Answered |
| P5b ✅ | sm | **Hostile-detection overhaul.** The critter/NPC filter the diagnosis found, plus the damage/mana write-off backstop. | `units.py`, `snapshot.py`, `necro.py`/`steps.py` | **Yes — live re-run** |
| P6 ✅ | sm | Layer events: stash deposits (items + gold), NPC interaction, waypoint panel/tab/selection, area transitions, cleanse, chicken, potions with HP/mana. | `town.py`, `waypoint.py`, `safety.py`, `reflex.py` | None |
| P7 ✅ | sm | Perception events (drops, collections, accidental flags), docs, manual, cleanup sweep. | `snapshot.py`, `pickit.py`, `docs/` | None |

**Ordering rationale.** P1–P4 are the smallest set that makes the Tower
diagnosable, so P5 arrived as early as it could — and paid for itself on
its first run.

**Re-sequenced 2026-08-06 (user decision).** P5's diagnosis found a
defect in a different layer than expected: the bot was not failing to
navigate, it was failing to tell a monster from a decorative critter.
That became P5b. The user's call on what follows: **finish the logging
(P6, P7) before returning to Countess runs** — "it'll help debug future
issues". Correct on the evidence: P1–P4 turned a three-hypothesis
guessing game into a one-run answer, and the remaining event families
(stash, NPC, waypoint, transitions, chicken, drops, collections) are the
ones a farm run generates constantly.

**Parallelization.** P2 is independent of P1 and could run beside it.
P3 and P4 both depend on P1+P2. P6 and P7 are independent of each other
and of P5.

## Progress

**P1-P4 complete** (2026-08-06, 987 tests, ruff clean). Delivered:
`pd2bot/runlog.py` (JSONL writer, null sink, renderer + CLI),
`pd2bot/mapframe.py` (three frames, screen compass, the single
definition of screen-north), the action funnel via a shared
`ActionLogging` mixin on BOTH executors, and per-tick records with the
snapshot/ladder/step/maintain timing split. Wired mandatory in
`build_bot` (Q11). The `exit_block_radius` rule is reverted (Q10).

Two defects the instrumentation found in itself, both fixed and both
worth remembering: a per-tick clock inside a decision label defeated
the renderer's collapsing (one line per tick instead of one per stall),
and reading the player position AFTER a send reported every `MoveTo`
destination as "0 away" because `walk_to` blocks until arrival.

**Next: P5**, the live diagnosis. `runs/m6-tower-probe.toml` and
`drills/t72_tower_probe.py` are the vehicle — a short town → Black
Marsh → Tower → Cellar 1 run that reproduces the failure cheaply and
prints its full event log. A reproduced failure WITH a log is a pass
for that drill; only never reaching the tower is a real failure.


## Progress, 2026-08-06 (session close)

**P5b DONE.** The critter filter (`combat_rated`, measured in T74) and
the futile-strike write-off (`futile_strikes`, both signatures reported,
neither durable). 996 tests.

**P6 DONE.** `area.transition` (both ends named), `inventory.cleanse`,
`chicken` and `death` with full vitals, `stash.deposit`/`stash.refused`/
`stash.gold`, `npc.interact` and `npc.accidental` (R220 Q7 — the stray
panel recovery has existed since R85; only now does it say so), and the
waypoint sequence `open` -> `tab` -> `select` -> `arrived`.

The town and waypoint layers take the log the way they already take
`narrate`: a holder the wiring repoints per run, because both are
SESSION-scoped and outlive any one run. The waypoint layer reads it
through the town layer rather than holding a second reference.

**P7 DONE except `item.accidental`.** Landed: `item.dropped` (fires on
the transition into the wanted set), `item.collected`, `item.abandoned`,
`combat.write_off`, and the schema reference at
`docs/architecture/run-log.md`.

`item.accidental` is deliberately NOT built. It needs a reliable "this
item entered the inventory and no `PickUpItem` targeted it" comparison
across ticks, and the honest version of that is more bookkeeping than it
looks — the same reason Q6 (enemy deaths) was deferred. The cleanse
already reports what it drops, so the CONSEQUENCE is visible even while
the event is not. Revisit with fresh evidence rather than guessing at
it.

**A design landmine removed:** `RunLog.event(kind, **fields)` meant no
emitter could ever record a field called "kind" — and half of what this
log describes has one. Found when `npc.interact` tried to record the
NPC's kind and collided with the parameter name. `kind` is now
positional-only, so the collision is impossible rather than fixed once.

Verified end to end on the countess sim: 246 events across 85 ticks,
including 6 `area.transition`, 2 `item.dropped`, 3 `item.collected`.
