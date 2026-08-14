# P7 — Perception events, docs, closeout

Part of [plan.md](plan.md). Size: `sm`. Dependencies: P1–P4 (P6
recommended). Review gate: none.

## Scope

The events derived from watching the world rather than from acting on
it, plus the schema reference and the cleanup sweep that closes the
plan.

Out of scope: enemy deaths (deferred, Q6 — the future-work entry in
`notes.md` records the design if it is revived).

## Implementation

### 1. Drop detection

| Kind | When | Fields |
|---|---|---|
| `item.dropped` | a **wanted** ground item is seen for the first time this run | `unit_id`, `item_kind`, `item_name`, `quality`, `sockets`, `position` (describe), `rule` (the pickit rule that wants it) |
| `item.vanished` | a tracked item leaves the ground with no pickup of ours | `unit_id`, `item_name`, `last_seen` |

Whitelisted only, as asked: the pickit already decides wantedness
(`Pickit.decide` → `keep`/`belt`), and `_PickupMixin.wanted_items`
already computes it every tick. The event fires on the transition into
the wanted set, keyed by `unit_id`, so a rune lying on the floor for
thirty ticks produces one event, not thirty.

`item.vanished` exists because the T70 Thul was invisible to behavior
while perception listed it: an item that appears and disappears without
the bot ever attempting it is the exact signature of that class of bug,
and now it is one grep away.

### 2. Collection outcomes

| Kind | When | Fields |
|---|---|---|
| `item.collected` | a clicked item provably left the ground **and** the inventory/belt gained it | `unit_id`, `item_kind`, `item_name`, `attempts`, `aim_offset`, `dur_s`, `accidental: false` |
| `item.accidental` | an item appears in the inventory that no `PickUpItem` targeted (Q7) | `item_kind`, `item_name`, `cell`, `suspected_cause` |
| `item.abandoned` | an item is written off (`stuck`) | `unit_id`, `item_name`, `attempts`, `reason` |

The accidental case is the R117 concept named: a travel click landing on
a ground item. The bot already detects the *consequence* (the cleanse
drops junk it never meant to hold); this records the *event*.
`suspected_cause` is the last action sent before the item appeared —
recorded as an observation, never as a conclusion (P1's no-interpretation
rule).

`item.collected` pairs with P3's `action.pickup_attempt`: attempts are
the effort, collection is the progress, and the pair makes pickup
accuracy measurable per run without a drill.

### 3. `docs/architecture/run-log.md` — the schema reference

The document a future agent reads instead of guessing. Contents:

- Where logs live, one directory per run, nothing pruned.
- The envelope: `seq`, `at`, `t`, `kind`, `area`, `area_name`.
- The coordinate payload (P2) with a worked example.
- **Every event kind**, its fields, and what it means — grouped by
  prefix (`action.*`, `item.*`, `stash.*`, `npc.*`, `waypoint.*`,
  `area.*`, `reflex.*`, `tick`, `step.decision`, `refusal`, `chicken`,
  `death`, `run.*`).
- The rules the log obeys: never raises, never blocks, never
  interprets, honest absence.
- How to read one: the renderer, its filters, and worked examples of
  answering real questions ("where did the time go in area 20?", "was
  that rune ever seen?").
- What is deliberately **not** logged and why — enemy deaths (Q6,
  deferred) heading the list, so nobody assumes a silent bug.

### 4. Manual and pointers

- `docs/manual/` — a short "reading a run log" section for the operator.
- `CLAUDE.md` — one line: when a run misbehaves, the run log is the
  first stop, and `docs/architecture/run-log.md` explains it.
- `docs/architecture/behavior.md` — point at the schema doc.

### 5. Cleanup sweep

Grep the diff for TODOs, debug prints, commented-out code, scratch
files, suppressed warnings, disabled tests, stale docs and scope creep.
Specifically check:

- No `print()` left in library code (the log replaces ad-hoc printing).
- `RunServices.log` / `narrate` call sites that are now redundant with
  events — remove duplicates, keep the narrative's editorial lines.
- The T71 decision-trace wrapper in `TraverseStep` is superseded by P4's
  `step.decision` events; remove it if so, or say why it stays.
- `docs/plans/2026-08-03-m6-countess/performance-notes.md` and
  `navigation-diagnosis.md` reflect the final state.

## Testing

- A wanted item appearing emits exactly one `item.dropped`, however many
  ticks it lies there.
- An unwanted item emits nothing.
- A successful pickup emits `item.collected` with `accidental: false`;
  an item appearing with no matching attempt emits `item.accidental`.
- A written-off item emits `item.abandoned` with its reason.
- The sim's countess run produces a log containing the corridor rune's
  `item.dropped` and `item.collected` — the T70 Thul lesson, now
  visible in the record.

## Style and conventions

- Transitions, not states: every event fires on a change, never per tick.
- Names via the existing tables, honest `kind <n>` fallback.
- Observations, not conclusions.

## ADR expectation

**None** — P1's ADR covers the format.

## Agent reminders

- Do not commit unless asked.
- Do not add enemy-death events; they are deferred (Q6). If they seem
  easy, that is the trap the deferral names — say so and leave them.
- Do not suppress warnings or disable tests.
- Report what changed, what was validated, and any deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

Plus: render a full sim run's log and read it end to end. The test is
whether a person who was not in this conversation can follow what the
bot did.

## Definition of done

Drop, collection and accidental events emitted and tested; the schema
reference written and complete; manual and pointers updated; cleanup
sweep done; suite green and ruff clean.
