# P6 — Staged live acceptance and milestone closeout

Part of [plan.md](plan.md) (M5). Size: `md` (staged live work +
docs; no further planning pass needed — the stages are defined
here). Dependencies: P1–P5 complete, P5's go/no-go answered **go**.
The user must be at the machine for every live stage; game-side asks
go through 🔶 numbered requests. This is the final phase: it ends
with the cleanup sweep and the teach step.

## Scope

Take the sim-proven run live in escalating stages, tune thresholds
from observed behavior, then close the milestone: architecture doc,
ADR finalized, README/CLAUDE.md/roadmap updates, teach artifacts,
cleanup sweep, and the acceptance record.

Out of scope: new features of any kind. A live failure that needs
more than a threshold/calibration tweak or a small, obvious fix goes
back as a stop-and-report, not an improvisation — the robustness
constraint (M4 notes) holds to the end.

## The stages (strictly in order; abort criteria agreed before each)

Danger context (R47.9): idle characters die; groups stun-lock. The
user supervises with hands near the controls in every stage until E;
the bot's focus guard yields the moment they take the mouse, and ESC
pauses the game instantly (offline SP) — both are standing abort
paths. Chicken thresholds start conservative and only come down to
R49 defaults as stages pass.

- **Stage A — town-only integration.** The full preamble as one
  sequence (heal → stash → refill → merc check) inside a real cycled
  game, conservative settings. Confirms P3's steps compose. (P3
  drilled them individually; this is the composition check.)
- **Stage B — supervised combat drill, small radius.** One game:
  preamble → waypoint → `clear_radius` with radius ~50 and
  `life_chicken_pct` raised to 50%; user hovering. Watch: the
  wait-for-revives beat, dash/strike/retreat shape, bone-armor
  recasts, desecrate→revive maintenance, first potion drinks.
  Collect the decision log; compare against the sim trace.
- **Stage C — supervised full run.** Radius 150, R49 thresholds,
  full pickit + pickup + next-game stash deposit verified. One to
  two games, user watching but hands off unless abort.
- **Stage D — threshold review.** With B/C logs in hand, agree final
  numbers with the user (🔶 decision): chicken back to 35%?, warp
  triggers observed sane?, drink cadence? Update `config/necro.toml`.
- **Stage E — unattended acceptance.** `--games 3` (real CLI, the
  M4 pattern): **3 clean unattended Cold Plains runs** — created,
  Hell-verified, preamble, waypoint, radius-150 clearance, pickit
  honored, left; zero human input; monitor silent (no chicken, no
  idle-bail) or the run doesn't count as clean. Capture the report
  into this planning dir (M4's acceptance-record precedent).

Any death at any stage: the latch does its job, and the milestone
*stops* for a user conversation — no same-day retry without an
explicit decision.

## Closeout work items

1. **`docs/architecture/behavior.md`** (new): the engine, the three
   layers (runs / class modules / reflex ladder), the ladder table
   with rationale, the never-idle invariant, panel-scoped input's
   place in the guard family, config/data file map, re-verification
   drill after patches (skill ids, calibrated panel fractions), and
   the future notes (TP tome, bone wall, vendor UI, corpse
   retrieval).
2. **ADR finalized**: `docs/adr/2026-07-29-behavior-architecture.md`
   status → accepted, amended with anything the live stages taught.
3. **Pointer updates**: `perception.md` (items/objects/skills
   sections), `game-cycle.md` (the run callback is now real; the
   town-heal preamble closes R45's loop — update the safety-monitor
   paragraph), `navigation.md` (waypoint travel exists; cross-area
   walking is M6).
4. **`README.md`**: new CLIs (dump extensions, any drill entry
   points, the run CLI), the `config/` and `runs/` files and how to
   edit them (pickit especially — the user-facing knob).
5. **`CLAUDE.md`**: M5 done-line (keep the style of M1–M4 lines);
   input-path paragraph gains `PanelInput`; M6 pointer (Countess,
   multi-area travel, doors, corpse retrieval still deferred).
6. **Roadmap** `docs/plans/2026-07-28-bot-from-scratch/plan.md`: M5
   row → done + archive link; ADR expectation (c) marked delivered.
7. **Teach step** (per CLAUDE.md, part of "done"): follow the
   `/teach` skill — explainer for the cycle's key concepts (behavior
   layers, reflex ladder, verified-switch pattern, pickit-as-data,
   panel-scoped input) in `docs/learning/`, glossary updates,
   calibrated to the learner profile in the skill.
8. **Cleanup sweep** (final-phase duty): grep for TODOs, debug
   prints (house-style operator output is fine — judge by M4's
   standard), commented-out code, scratch files, suppressed
   warnings, disabled tests, stale docs, scope creep. Check
   `config/`/`runs/` files carry their explanatory comments and
   calibration dates.
9. **Instruction log**: all M5 requests resolved with outcomes; add
   to the reduction-analysis observations if patterns emerged.
10. **Archive**: move this planning dir to
    `docs/archive/plans/2026-07-29-m5-trial-run/`; `yona-implement`
    writes `_DONE.md` (outcome, validation incl. the stage record,
    deviations, docs, ADRs, follow-ups — M6 planning inputs
    especially: what Cold Plains taught about combat robustness,
    multi-area needs for Countess, anything deferred).

## Conventions and reminders

- Nothing in the safety stack changes in this phase. Threshold
  changes go through the Stage D decision, not ad-hoc edits.
- Every live stage's ask is a numbered request with the outcome
  logged; acceptance evidence (reports, decision logs) is captured
  into this planning dir before archiving.
- Do not commit unless the user asks (M4 precedent: one milestone
  commit offered at the end via a 🔶 decision).
- Text transforms on repo files go through Python, not PowerShell
  string ops (R44 lesson).
- Report faithfully: a stage that needed a retry is reported as
  such; "clean" means clean.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

Plus Stage E's 3/3 report captured in this dir and summarized in
`_DONE.md`.

## Definition of done

Stages A–E passed in order with logged outcomes (E: 3/3 clean
unattended); thresholds finalized via Stage D; behavior.md + ADR
accepted; README/CLAUDE.md/roadmap/pointers updated; teach step
done; sweep clean; instruction log current; planning dir archived
with `_DONE.md`.
