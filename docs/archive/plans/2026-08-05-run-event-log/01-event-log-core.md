# P1 — The event log core

Part of [plan.md](plan.md). Size: `sm`. Dependencies: none.
Review gate: none.

## Scope

The module every later phase emits into: the event schema, the JSONL
writer, the per-run directory, the null sink, and the renderer. Plus the
ADR, and the Q10 revert.

Out of scope: emitting any events from the bot (P3 onward) and the
coordinate frames (P2 — this phase accepts coordinates as passed).

## Implementation

### 1. `pd2bot/runlog.py`

**`RunLog`** — opens `logs/runs/<YYYYMMDD-HHMMSS>-<runname>/` on
construction and writes two files:

- `run.json` — the header, written once at open: run name, run file
  path, wall-clock start, map seed, difficulty, character name/level,
  class config, chicken threshold, engine config, git sha if available,
  and the schema version.
- `events.jsonl` — one JSON object per line, appended and flushed per
  event so the file is readable while the bot is running and survives a
  crash (the `Narrator` discipline, R179).

**`event(kind, **fields)`** is the only write path. Every event gets,
automatically:

```json
{
  "seq": 412,
  "at": "2026-08-05T21:30:22.417",
  "t": 59.194,
  "kind": "action.move",
  "area": 20,
  "area_name": "Forgotten Tower",
  ...
}
```

- `seq` — monotonic counter, so ordering survives equal timestamps.
- `at` — ISO wall clock, local time (Q4): what the operator saw.
- `t` — seconds since run start, monotonic (Q4): what arithmetic uses.
- `area` / `area_name` — stamped from the last known area so no event is
  orphaned; the emitter does not have to remember.

Kinds are **namespaced dotted strings** — `action.move`, `action.attack`,
`item.dropped`, `stash.deposit`, `tick`, `step.decision`,
`area.transition` — so a reader can filter by prefix. The full list is
owned by `docs/architecture/run-log.md` (P7) and grows per phase.

**`NullRunLog`** — the same interface, discards everything. The ONLY
silent path (Q11), for unit tests and the sim's default. `build_bot`
never uses it.

Design rules, in the module docstring:

- **Never raise.** A logging failure must not end a run. Wrap the write;
  on error, disable further writes and print once. The log is
  instrumentation, not a dependency.
- **Never block.** Append-and-flush only; no rotation, no compaction, no
  network.
- **No interpretation.** The log records what happened, never what it
  means. "clicked at X, player at Y" — never "the click failed".
  Conclusions are the reader's job; this is the lesson T71 taught.
- **Honest absence.** A field the bot could not read is `null` with a
  sibling `*_unread` reason where useful — never a plausible-looking
  default. A guessed value in a diagnostic log is worse than no log.

### 2. The renderer

`python -m pd2bot.runlog <run-dir>` prints a readable timeline; with no
argument it renders the most recent run. Behavior:

- One line per event: `[t+59.19] 21:30:22  action.move  ...`
- Consecutive identical-kind events collapse with a count and a span
  (the T71 lesson — a per-tick clock in the label defeats collapsing, so
  volatile fields are excluded from the collapse key).
- `--kind action.*` filters by prefix; `--since/--until` by `t`;
  `--raw` passes JSON through.
- A `SUMMARY` footer: run duration, tick count, mean/max tick duration,
  events by kind, areas visited with time in each.

### 3. Revert `exit_block_radius` (Q10)

Remove the contested-staircase rule from `TraverseStep`: the fields
(`exit_block_radius`, `exit_block_hold_s`, `contested_click_budget`,
`_contested_clicks`, `_contested_since`, `_contest_logged`), the branch,
the second `NavigationError`, and the three tests
(`test_traverse_does_not_spend_its_budget_on_a_contested_staircase`,
`..._waits_for_the_fight_to_clear_the_stairs...`,
`..._gives_up_loudly_on_a_permanently_contested_staircase`).

Keep the decision-trace wrapper (`_decide` + `_record_decision` +
`_flush_decision`) — P4 supersedes it with real events, but it must not
regress in the meantime.

Record in the M6 plan's `navigation-diagnosis.md` addendum that the rule
was reverted, and why: the user confirmed the Forgotten Tower never
contains monsters, so the hypothesis it was built on is dead.

### 4. The ADR

`docs/adr/2026-08-05-run-event-log.md`, status **proposed**. Content:
the decision (an always-on, append-only, schema'd JSONL event log as the
run's system of record), the context (T71: five recorded decisions out of
~150, and an analysis that turned into speculation), the alternatives
(prose narrative — already tried, insufficient; opt-in structured
logging — rejected under Q11 because the run you most need is the one
without the flag; a database — rejected, no query need that grep and a
renderer do not serve), and the consequences (every run costs tens of KB;
instrumentation is now a non-negotiable part of any new decision path).

## Style and conventions

- Comments explain **why**, with the evidence — the house style. Cite
  T71 where a rule exists because of it.
- Strict validation on load, loud errors, no silent defaults
  (`combat.py`'s loader is the model) — but the WRITE path never raises.
- Type hints throughout; `from __future__ import annotations`.
- No new dependencies: `json`, `pathlib`, `time`, `dataclasses` only.

## Docs

Module docstring carries the schema contract. The full reference lands
in P7; this phase only needs `runlog.py` to be self-explanatory.

## ADR expectation

**Expected** — written in this phase, as above.

## Agent reminders

- Do not commit unless asked.
- Do not expand scope: no emitters in this phase beyond what the tests
  need.
- Do not suppress warnings or disable tests.
- Stop and report if the revert in step 3 turns out to be load-bearing
  for something unexpected.
- Report what changed, what was validated, and any deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

## Definition of done

`RunLog` writes a well-formed run directory; `NullRunLog` is silent; the
renderer prints a timeline and a summary from a real file; the
contested-staircase rule is gone with its tests; the ADR is written;
suite green and ruff clean.
