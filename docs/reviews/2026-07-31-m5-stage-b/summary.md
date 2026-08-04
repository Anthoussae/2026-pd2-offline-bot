# Review — M5 P6 stage B: the live-driven session

- **Target**: `m5-trial-run` @ `89d9fa1`
- **Base**: `f88afcb` (the last commit before this session)
- **Scope**: 43 files, +4356 / -519 across 25 commits.
- **Validation at review time**: 666 tests pass, `ruff check .` clean.

## What this session was

Nine live stage-B attempts, each stopped by a different defect, each fix
made between runs. That produced a lot of genuinely good work — every fix
was diagnosed from live evidence rather than guessed, and several closed
whole classes of bug rather than instances (the runner's inverted default,
the code-anchored vocabulary, per-type unit dedup).

It also produced a rate of self-inflicted regressions high enough to be
the reason this review was called. Three landed in the branch and were
caught by the next run rather than by review:

- ground items as travel-click hazards broke deliberate item approach;
- the review-002 commit-on-success fix removed the armor rung's only
  retry pacing, turning a crash into a livelock;
- and the combat repositioning added at the end has not been run at all.

**The last of those is the theme of this review.** The changes made after
the final live run — repositioning, the wall gate, the cast settle — have
no live evidence behind them, and two of the findings below are in exactly
that unverified band.

## Findings

| # | Sev | Title | File | State |
|---|---|---|---|---|
| [001](issues/001-reposition-can-strand-the-clearance.md) | **P1** | Repositioning can drift out of engagement and stall the run forever | `necro.py`, `steps.py` | **fixed** 2026-08-01 |
| [002](issues/002-cast-settle-blocks-the-ladder.md) | **P2** | The cast settle blocks the tick the survival ladder needs | `execute.py` | **fixed** 2026-08-01 |
| [003](issues/003-town-polling-reads-every-socket.md) | **P2** | Town waits re-read every inventory socket, 10x a second | `town.py`, `items.py` | **fixed** 2026-08-01 |
| [004](issues/004-catch-all-masks-programming-errors.md) | P3 | The runner's catch-all cannot tell a bug from a bad moment | `runner.py` | open |
| [005](issues/005-wiring-reaches-into-engine-privates.md) | P3 | The trace printer reaches into `engine._executor` | `wiring.py` | open |

001 must be fixed before any unattended run: it is a permanent hang, and
the mechanism that would normally catch a hang was explicitly disabled on
that path earlier in the same session.

## Follow-up, 2026-08-01

001, 002 and 003 are fixed; 685 tests pass and ruff is clean. Two of the
three are also the review being wrong about something, which is worth
recording as plainly as the fixes:

- **The sim runtime was not 001.** This summary offered ~4.4 s per
  scenario as circumstantial evidence that the bot was spending far more
  ticks. It was not: `SimExecutor` inherits the real `time.sleep`, so the
  runtime is 11 casts x `cast_settle_s` (0.4) = 4.4 s, every scenario
  within 0.01 s of every other, and tick count is unchanged at 65 across
  001's fix. It belonged to 002 — fixing it took the whole suite from
  93.9 s to 2.4 s.
- **The cast does not eat following input.** 002 was written on the
  premise that a following command interrupts the cast, and T48 measured
  a hotkey press sent 110 ms INTO an animation registering within 62 ms.
  Only clicks are worth holding, so the ladder's potion rungs — keypresses
  — are now explicitly exempt and never queue behind an animation.

T48 also measured what nobody had: a cast is **610-640 ms**, which the
0.4 s guess never covered.

**The skill-switch failure is still open, and both its theories are now
dead.** T47 pressed all six hotkeys and every one selected exactly what
`config/necro.toml` claims; T48 killed the cast-eats-input explanation. A
blocking panel (chat console included) and a lost foreground both raise
`InputRefused` rather than `SkillSwitchFailed`, so they are excluded by
construction. `ensure_right_skill` now attaches the state at the moment of
failure — waited, player mode, UI panels, left-skill read — so the next
occurrence is evidence rather than another supervised run.

## What was checked and found sound

- **The vocabulary redesign** (R144). Code-anchored names, loud failure on
  an unknown code, both directions tested. The seven corrected elite
  armours are pinned against the live code table rather than against a
  transcription of it.
- **Per-type unit dedup**. The fix is minimal, the regression test
  reproduces the exact live collision (object 11 vs monster 11), and the
  duplicate-listing case the dedup exists for is still covered.
- **The exception boundary**. `DeathHalt` and `CycleError` propagate;
  everything else is counted and survivable. The death latch's permanence
  is explicitly tested, which is the property that matters most.
- **Armor down as a trigger.** T46's three live readings are quoted in the
  code, the empty-stat-list guard is what makes it safe, and a full pool
  is tested to be left alone — the failure mode that would have consumed
  every tick.
- **Toggle-on-refusal deposits.** Verified live end to end (T27), and the
  design needs no tab signal at all, which is what made the whole class of
  stash-tab failure go away.

## Test-coverage notes

666 tests, and the new ones are mostly good: they cite the live run that
motivated them, and several assert the *absence* of a previous behaviour
rather than just the presence of the new one.

Two gaps worth naming:

- **The combat changes are untested against the sim's end-to-end
  scenario.** They pass unit tests, but `test_behavior_sim` runtimes went
  from negligible to ~4.4 s each after them — the bot is spending far more
  ticks to reach the same outcome. That is unexplained, and finding 001 is
  the most likely explanation.
- **No test covers a step that reports `waiting=True` indefinitely.** That
  is precisely the hole 001 falls through.

## ADR candidates

One, and it is worth writing when 001 is resolved: **when may a wait
suppress the never-idle watchdog?** `StepOutcome.waiting` was added for a
good reason (review 003 — the watchdog fired during deliberate settles)
and it has now become the reason a genuine hang is invisible. The policy
needs stating: a declared wait should be bounded, and an unbounded one is
a hang wearing a wait's clothes.

## Residual risk

The bot has completed the Cold Plains run twice, but only one of those
involved meaningful combat, and the combat behaviour has changed since.
The skill-switch failure recurred in three separate runs on three
different skill pairs and is still unexplained — T47 is written and
unrun, and the bone-armor cast-animation theory (user, from manual play)
is plausible but unverified. Gold's kind was corrected from data rather
than from a live drop, so the first real gold pickup is still an
unvalidated path.
