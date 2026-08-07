# Done — the run event log (2026-08-06)

## Outcome

The always-on, schema'd, append-only run event log is built, live, and
load-bearing. Every diagnosis of the M6 cycle started with it, and the
"reason from silence" failures it was created to end have not recurred.
The ADR (`docs/adr/2026-08-05-run-event-log.md`) is **accepted** — its
acceptance condition (the log answers a question the old instrumentation
could not) was met repeatedly.

## Completed

- **The writer/reader** (`pd2bot/runlog.py`): one directory per run under
  `logs/runs/<stamp>-<runname>/events.jsonl`; the monotonic `seq` + wall
  clock + seconds-since-start envelope; the renderer with `--kind`,
  `--since`/`--until`, `--raw`, `--no-collapse`, and `--pickup` (the
  wanted-vs-collected census, added by the pickup-reliability plan).
- **Coordinate frames** (P2): every spatial field carries world,
  area-local, and character-relative frames.
- **The action funnel** (P3): `action.*` events from the one executor —
  move, cast, attack, pickup_attempt, drink, interact, park_skill.
- **Tick + decision records** (P4): `tick` (with the snapshot/ladder/
  step/maintain timing split and hostile/ally/critter counts) and
  `step.decision` for **every** decision, not just noted ones. This is
  the line that closed the Forgotten Tower mystery.
- **Layer + perception events** (P6/P7): `area.transition`, `waypoint.*`,
  `stash.*`, `npc.*`, `combat.write_off`, `chicken`, `death`, `refusal`,
  `reflex`, and the item lifecycle `item.dropped` / `item.collected` /
  `item.abandoned` (the last two extended by the pickup-reliability plan
  with the click-budget write-off, `nav.failed`, and `attributed_to`).
- **The schema reference** (`docs/architecture/run-log.md`): every event
  kind and field, the four rules, worked reading examples. Current.
- **The four rules**, enforced: never raises, never blocks, never
  interprets, honest absence.

## Validation

- Full suite green (1035 tests at closeout), ruff clean.
- Live-proven repeatedly: T72 (Tower crossing 4.3 s vs 173 s — the fix
  rode the decision records), the phantom-hostile diagnosis, and the
  pickup census across the T71 Countess run.

## Deviations / deferred (named so their absence is not a silent bug)

- **`item.vanished`** and **`item.accidental`** (P7's §1/§2 refinements)
  were **not implemented**. The core drop/collect/abandon lifecycle
  covers the diagnostic need; these two were refinements and are left as
  future work. `item.dropped` already gives the "was that rune ever
  seen?" signal the T70 Thul lesson wanted.
- **Enemy-death events** (R220 Q6) — deferred at design time; the design
  is recorded in `notes.md` for a later revival.
- **The `print()` cleanup sweep** (P7 §5) was **not run**: the ~80
  `print()` calls in the package are overwhelmingly drill/operator-tool
  output (house-style, exempt) and removing them wholesale during a
  closeout carries more regression risk than value. Left as a deliberate
  non-goal; revisit only if a specific debug print is found in a hot
  library path.

## Docs

`docs/architecture/run-log.md` (schema, complete); `CLAUDE.md` (the
"read the log first, don't reason from silence" pointer added);
`docs/learning/2026-08-06-instrumenting-for-questions-you-cannot-predict.md`
(teach) + glossary (honest absence, JSONL, observability, reasoning from
silence).

## Follow-ups

The two deferred item events and enemy-death events, if a future cycle
wants finer item/kill telemetry. None blocks anything.
