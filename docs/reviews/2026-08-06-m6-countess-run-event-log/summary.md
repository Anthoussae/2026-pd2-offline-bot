# Review — M6 P4: the run event log and the phantom-hostile fix

- **Target:** `ca54a53` on `m6-countess`
- **Base:** `HEAD~1`
- **Scope:** 57 files, +8089 / -57
- **Validation:** 999 tests pass, ruff clean, verified live (T72 run 2)

## Overall assessment

**Merge-ready.** Three findings, none blocking: one stale success
criterion in a drill (P2) and two small correctness/quality items (P3).

The segment does two things. It builds a structured run log because two
live failures could not be explained from the existing artifacts — and
then it uses that log to find and fix the defect those failures were
actually about. The fix is verified live: the Forgotten Tower crossing
went from 173 s / 184 ticks to **4.3 s / 16 ticks**, both transitions,
clean `[CVRL]`.

What raises confidence in the diagnosis specifically: it was reached by
read-only probes (T73, T74) after four *wrong* hypotheses, three of
which were caught before they reached code and one of which was written
and then reverted. The discriminator that shipped (`combat_rated`) is
backed by measured stat lists from four unit types, not by a plausible
story.

## Findings

| # | Severity | Title | File | Status |
|---|---|---|---|---|
| 001 | P2 | T72 scores a reproduced failure as PASS | `drills/t72_tower_probe.py` | **FIXED** |
| 002 | P3 | A dead critter routes to `corpses`, becoming revive fuel | `pd2bot/units.py` | **FIXED** + test |
| 003 | P3 | `npc.accidental` fires once per retry, not per accident | `pd2bot/town.py` | **FIXED** |

All three resolved in the follow-up commit; 1000 tests green.

## What was checked and found sound

**The log cannot endanger the run.** `RunLog.event` wraps its write,
disables itself once on failure, and never raises; the executor and
engine emits are wrapped again; `SafetyMonitor._record` is wrapped a
third time and has a test asserting a logger that throws still lets
`DeathHalt` through. The safety invariant is untouched — the `death`
event is written by the monitor that already latched, not by a new path.

**The instrument is not observable in what it instruments.** Emitters
check `runlog.enabled` before gathering, because `_here()` and
`_vitals()` are live memory reads.
`test_nothing_is_read_until_we_have_actually_cast` enforces this and
caught the first version.

**Coordinates are honest.** `MapFrame.unknown()` reports `frame:
"world"` and local == world rather than inventing an origin; `describe`
omits `rel`/`dist`/`bearing` when no player position is available.
Bearings are asserted against the screen projection in all eight
directions.

**Names are never guessed.** Items resolve through the existing
code-anchored `ItemTable` with a `kind <n>` fallback; skills through
the class config with `skill <id>`. R144's Wire Fleece lesson holds —
no second naming path was introduced.

**The pacifism guard exists.** `test_a_real_monster_is_still_a_target`
and `test_resistances_alone_qualify_a_unit_as_a_combatant` exist
because the previous candidate fix would have made the bot stop
fighting entirely. The shipped test is an OR of combat markers, which
fails in the safe direction.

**Test fakes were corrected, not accommodated.** Five existing tests
failed when the critter filter landed because their fakes built
monsters with only hp/max-hp — the bat's exact profile. They now carry
a level. The fakes had been modelling scenery as monsters all along.

## Notable non-findings

- `RunLog.event` takes `kind` positional-only. This was a real
  landmine — no emitter could have a field named `kind`, and half the
  domain has one. Fixed at the source rather than per-site.
- `_here()` captures position BEFORE the send, because `walk_to` blocks
  until arrival and a post-send read reported every destination as
  "0 away". Caught by reading the first log the instrumentation
  produced.
- Reverted code (`exit_block_radius`) was removed with its three tests,
  and the source now carries a comment explaining why the hypothesis
  died. The evidence outlived the code, which is the right trade.

## Residual risk

- **`item.accidental` is not implemented** (R220 Q7). Deliberate and
  documented: it needs cross-tick bookkeeping to say "no `PickUpItem`
  targeted this", and the honest version is more than it looks. The
  cleanse still reports what it drops, so the consequence is visible.
- **`stash.*` and `npc.*` are unproven live.** T72 run 2's preamble had
  nothing to deposit and nobody to talk to, so those paths logged
  nothing — correctly. A real Countess run with loot will be their
  first exercise.
- **`clear_countess` has never run live.** Sim-proven only (both the
  kill path and the blinded-read sweep path). The staging derivation
  was reviewed at R219 but the endgame itself is untested against the
  game.
- **Enemy-death events remain deferred** (R220 Q6), so nothing in the
  log claims a kill. Recorded in the schema doc under "deliberately not
  logged" so their absence is not mistaken for a bug.

## ADR candidates

None new. `docs/adr/2026-08-05-run-event-log.md` was written with this
work and covers the durable decision (always-on schema'd JSONL as the
run's system of record, plus the coordinate convention). It is
**proposed**; T72 run 2 is the evidence for moving it to **accepted** —
the log answered on its first run a question that two rounds of
reasoning could not.
