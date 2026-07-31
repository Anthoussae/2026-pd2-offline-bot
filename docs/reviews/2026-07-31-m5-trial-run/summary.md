# Review — M5 P4 + P5 + P5b (behaviour engine, necro combat, pickit, hygiene)

- **Target**: `m5-trial-run` @ `110514f` plus the uncommitted stage-A
  changes (input/panelinput/T43/T44, instruction log).
- **Base**: `084ba70` (the P3 gate close).
- **Scope**: 59 files, ~11,100 insertions. Focus as requested:
  `pd2bot/behavior/`, `pd2bot/pickit.py`, `pd2bot/town.py`.
- **Validation at review time**: 584 tests pass, `ruff check .` clean.

## Overall assessment

The architecture holds up. The engine's central promise — that a firing
survival rung consumes the tick, so offense cannot run while survival
has something to say — is structural rather than conventional, and the
tests pin it. The pickit's fail-safe posture (an unresolved name matches
nothing; the cleanse disables itself while any keeper is unrecognised)
is the right default in both directions, and it demonstrably worked:
the T39 abort caught ~49 wrong ids before any of them reached the game.

The findings below are concentrated in one place, and it is the same
place in every case: **the seams P6 has not wired yet**. The code is
correct when assembled correctly; what is missing is the refusal to be
assembled incorrectly. Issue 001 is the sharpest example and the reason
this review is not a clean pass.

Three of the five findings were confirmed by direct probe rather than by
reading, and the probes are reproducible from the issue files.

## Findings

| # | Sev | Title | File |
|---|---|---|---|
| [001](issues/001-cleanse-unprotected-by-default.md) | **P1** | The cleanse drops everything by default; protection is opt-in | `town.py` |
| [002](issues/002-refused-send-kills-the-loop.md) | **P2** | A refused send ends the run loop, and the ladder thinks it acted | `engine.py`, `reflex.py`, `cycle.py` |
| [003](issues/003-idle-watchdog-vs-legitimate-waits.md) | **P2** | The idle watchdog can fire during waits the design asks for | `engine.py`, `steps.py`, `necro.py` |
| [004](issues/004-potion-reserve-two-sources.md) | P3 | The potion reserve is configured twice, in two files | `town.py`, `config/pickit.toml` |
| [005](issues/005-minor-cleanups.md) | P3 | Dead parameter, unbounded session state, P6 wiring checklist | several |

None of these block P6 **stage A**, which is complete and passed. 001
must be fixed before the cleanse is wired into a real run; 002 and 003
should be fixed before any unattended session.

## What was checked and found sound

- **Rung ordering and short-circuiting** — the ladder's priority order,
  the rejuv→warp escalation, town suppression of rungs 3–7, and the
  monitor's exceptions passing through untouched.
- **The blood-warp self-trigger fix** — clearing the damage window when
  a warp is issued. The sim asserts exactly one warp for one escape.
- **Multi-id names** — the `s`-variant binding, with the two live ids
  (`r15s` 713, `gpbs` 690) asserted at generation time so the R126 class
  of error cannot silently return.
- **Strict vs permissive evaluation** — both mistake directions point at
  "keep", verified for unknown sockets and unresolved names.
- **Pickup bookkeeping sharing** — one memory across both collecting
  steps, after the sim caught the six-clicks-instead-of-three bug.
- **Modifier discipline** — shift and ctrl both settled on each side of
  the click, releases in `finally`.

## Test-coverage notes

Coverage is genuinely good (584 tests) and the end-to-end sim is the
strongest asset: it was built to be able to refuse, and it found two
real bugs on its first run. Gaps worth naming:

- No test exercises `InputRefused` through the engine (issue 002).
- No test constructs the *production* wiring, which is why 001 and 004
  are invisible to the suite — every test passes the parameters that a
  real caller might omit.
- `simworld` fakes the town preamble at its seam. Correct (P3 proved
  that layer live), but it means the potion protocol v2 and the cleanse
  are only covered by `test_town.py` unit tests, not end-to-end.

## ADR candidates

None new. The behaviour-architecture ADR
(`docs/adr/2026-07-29-behavior-architecture.md`, status *proposed*)
still describes what was built; P6 finalises it. Issue 001's resolution
— whether safety defaults are opt-in or opt-out — is worth a sentence in
that ADR when it is finalised, since it is a policy the project will
apply again.

## Residual risk

The bot has never fought anything live. Everything in `necro.py`,
`reflex.py` rungs 3–7, and the clearance step is sim-proven only, and
the sim is my model of the game rather than the game. That is stage B's
job and it is correctly gated. Gold's kind (`gld`) also remains the last
inherited constant never confirmed on a live drop.
