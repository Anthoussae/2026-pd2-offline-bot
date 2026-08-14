# P5 — live canary, ADR, docs, closeout

**Size:** `sm`. **Depends on:** P1–P4. **Review gate: YES — a live
canary, and the operator must be at the machine.** **ADR: expected.**

## Scope

Prove both layers against the real client at zero risk, write the
architectural record, update every doc that states the safety story, and
sweep the plan closed.

## 1. The canary — zero risk by construction

`safety.py` already documents the zero-risk live test path, and it is
the right one here: **mana chicken in town** with `chicken_in_town` on
and a 99 % threshold. The code path is identical to life chicken, so
testing one tests both — that reuse is stated in the module docstring
and is the reason it exists.

Two drills, both in town, neither able to hurt the character:

- **T80 — the in-process interrupt (Track A).** Walk a long town leg
  with a mana threshold that will trip mid-walk. PASS = a `ChickenExit`
  raised *during* the walk, a `safety.interrupt` event in the run log
  with `where=walk`, and the elapsed time from crossing to raise inside
  the number P2's review gate stated. This is the assertion the death
  bought: the old code could only have raised it at a tick boundary.
- **T81 — the watchdog (Track B).** Watchdog armed on mana at 99 % while
  the bot walks in town. PASS = the game pauses, `UI_ESCMENU_MAIN` opens,
  the latch is written, `GatedInput` refuses world input afterwards, and
  the bot's own leave completes cleanly. Then the deliberate second
  half: **kill the bot process mid-walk** and confirm the watchdog still
  fires — that is the whole claim of Track B, and it is only true if
  demonstrated.

Both need the operator at the machine, tabbed in, per the live protocol.
Issue them as `verify` requests with the counters from
`docs/project-state.md`, and log them in `docs/drill-log.md` as usual.

**Status 2026-08-07: both are ready to run.**

- **T80** is written: `drills/t80_safety_interrupt.py`, verdict logic
  unit-tested in `tests/test_t80_safety_interrupt.py`. It runs two
  rounds — the cap with nothing watching, then the interrupt with a real
  `SafetyMonitor` armed 1 s into a walk. Life chicken is explicitly set
  to 0 so nothing can fire on HP; the interrupt is caught by the drill,
  so the game is never even left. Its criteria **cannot pass on a walk
  that never moved**, which is the T72 lesson applied here: an instant
  interrupt against a stationary character proves the poll is wired and
  nothing about whether a walk in flight can be interrupted.
- **T81 needs no new code** — the watchdog's own CLI is the instrument.
  `--probe` reads vitals and arms nothing; then armed on mana in town,
  with the operator watching the game pause. The second half (kill the
  bot process mid-walk, confirm the watchdog still fires) is inherently
  observational and stays a by-eye check.

Do **not** re-run the Countess as the canary. A 15-minute run is a poor
instrument for a 2-second question, and live time is the scarce
resource.

## 2. The ADR — `docs/adr/2026-08-07-unstarvable-safety.md`

Status `proposed` on write; the operator accepts it. It should record:

- **Context**: the death, the starved monitor, and the measured 24 s.
- **Decision**: safety is defended twice — an in-process interrupt that
  no `except Exception` can swallow, and an out-of-process watchdog that
  no in-process block can starve.
- **Alternatives** and why they lost: in-process only (cannot survive a
  wedged process); watchdog only (leaves the reflex ladder and the abort
  channel starved); re-basing `ChickenExit` on `BaseException` (makes
  four non-vitals subclasses uncatchable for no extra safety).
- **Consequences**: a second elevated process in every real run; a
  lifecycle to keep honest; two new file channels with staleness rules;
  the standing rule that **any new blocking call must take the poll** —
  that is the part future work will trip over, so state it as a rule,
  not a note.
- Its relationship to the accepted behaviour-architecture ADR
  (`docs/adr/2026-07-29-behavior-architecture.md`), whose "capped legs"
  contract this restores.

## 3. Docs

- `docs/architecture/behavior.md` — the tick contract now includes
  in-walk polling and the cap.
- `docs/architecture/game-cycle.md` — the safety section gains the
  watchdog and the latch asymmetry (world input stops, the menu path
  stays open).
- `docs/architecture/run-log.md` — `safety.interrupt`, `nav.capped`,
  `watchdog.fired` documented with their fields.
- `CLAUDE.md` — the safety-invariant paragraph gains one sentence: the
  monitor cannot be starved, and how.
- `docs/project-state.md` — **remove the ⛔ HALT banner** once T80/T81
  pass, and extend the live protocol with starting the watchdog and
  clearing its latch.
- `docs/learning/` — the `/teach` step is part of "done" in this repo,
  not optional polish. The concepts worth explaining plainly here are
  genuinely interesting: why a blocking call starves a watchdog, why
  `BaseException` exists, and why two independent layers beat one good
  one. Update `docs/learning/glossary.md` too.

## 4. Cleanup sweep

Grep the branch's diff for: TODOs, debug prints, commented-out code,
scratch files, suppressed warnings, disabled or skipped tests, stale
docstrings that still say the monitor runs only at tick top, and scope
creep. Check that no new `except Exception` landed on a safety path.

Confirm the pickup-reliability plan's P6 and the M6 P5 battery are
correctly described as the next work in `docs/project-state.md`, with
the counters (`Next request ID`, `Next test ID`) updated.

## 5. Closeout

Write `_DONE.md` (the `yona-implement` convention) covering outcome,
completed work, validation results, deviations, docs updated, the ADR,
and remaining follow-ups. Then archive:
`docs/archive/plans/2026-08-07-safety-starvation/`.

## Agent reminders

- Do not commit unless asked.
- Do not launch either drill without the operator's explicit go — the
  live protocol governs, and this plan exists because of a death.
- Do not remove the HALT banner until the canary has actually passed.
- Report what changed, what was validated, and any deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

## Definition of done

Both layers demonstrated against the live client at zero risk, the ADR
accepted, every doc that describes the safety story updated, the HALT
banner lifted, and the plan archived.

---

## Implementation Result (2026-08-07) — canary DONE, both layers PROVEN

The operator asked for the canaries to run **unattended**, with the
agent taking the client itself from character select. It was possible,
and it is what happened: `drills/safety_canary.py` brings the game
window to the foreground, creates its own game via the M4 cycle, runs
five rounds, tears down in a `finally`, and leaves the game. Driven
through the elevated bridge.

**T80 run 2 + T81: PASS, 5/5 rounds.**

| round | result |
|---|---|
| 1. the wall-clock cap | returned in **2.08 s** against a 2.0 s budget, `capped=True` |
| 2. the in-process interrupt | `SafetyInterrupt` raised from inside a walk that had **already moved 12 subtiles** |
| 3. the watchdog fires | a separate process, **no bot running at all**, pressed ESC and paused the game; latch `reason=mana` |
| 4. the latch disarms world input | `GatedInput` refused for the latch, allowed once cleared; `MenuInput` never blocked |
| 5. the dead-man switch | heartbeat stale in 1.5 s; an engine with `require_watchdog` refused to step |

Client left at `main_menu`, no latch file, no stray process.

### Run 1 failed, and it was worth the run

Three defects, found by running rather than by review:

1. **A production bug blocking every unattended run.**
   `bring_to_foreground` could not take the window at all:
   `SetForegroundWindow` only obeys a process that already owns the
   foreground or the most recent input — true of every interactive run
   and none launched from the bridge. Fixed in `pd2bot/window.py` with
   `force_foreground()` (one inert ALT to qualify, attach to the
   foreground thread's input queue, ask again, detach in a `finally`),
   which `bring_to_foreground` escalates to once. Still verified, still
   allowed to fail.
2. **A threshold that could not fail.** The canary armed mana at 99 %
   against a character at 356/356 — and `pct <= threshold` is false at
   exactly 100 %, so rounds 2 and 3 proved nothing while appearing to
   run. Now 100, with the reasoning in the code. Same shape as the
   `ClearRadiusStep` and T72 lessons, caught this time by the run.
3. **A stub snapshot crashed round 5** before reaching the check it
   existed to make, and took four passing rounds' results with it. The
   round now uses a real `Perception` snapshot, and every round is
   wrapped so a crash becomes a FAIL, never a lost report.

### Closeout status

- ADR `docs/adr/2026-08-07-unstarvable-safety.md` — **accepted**.
- `docs/project-state.md` — HALT **lifted**; the M6 P5 battery is
  unblocked.
- `docs/architecture/run-log.md`, `CLAUDE.md` — updated.
- Drill log: T80 runs 1–2, T81 run 1.
- **Still owed:** the `/teach` explainer in `docs/learning/`, the
  cleanup sweep, and archiving this plan.
