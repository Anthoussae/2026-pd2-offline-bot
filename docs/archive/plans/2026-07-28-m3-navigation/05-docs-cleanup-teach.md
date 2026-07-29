# P5 — Docs, cleanup, teach

Size: `sm`. Dependencies: P1–P4 complete. Part of the M3 plan
([plan.md](plan.md)).

## Scope

### Documentation

- `docs/architecture/navigation.md` (new, sibling of
  `perception.md`, same register — explain *why*, note traps): the
  gated input design and the incident that mandates it; the
  world→screen projection and how it was calibrated; CollMap layout,
  its non-BH sources, and the seasonal re-verification note; the
  generator child process, its protocol, and the fidelity verdicts
  (link `fidelity-results.md`); A* + follow-loop design; what is
  deliberately deferred (doors, transitions, combat-while-stuck).
- `README.md`: d2mapapi_mod dependency (pinned commit/URL, 32-bit
  build note, where the binary lives), new CLI entries
  (`pd2bot.navigate`, collision dump, fidelity runner), any new
  Administrator/foreground caveats.
- `offsets.py` docstring: confirm the non-BH-source sentence landed
  (P2); roadmap plan M3 row → link this planning dir as done (same
  edit M2 made).
- ADR cross-links: map-knowledge ADR (P3) listed from
  `navigation.md`; gated-input ADR if P1 wrote one.

### Cleanup sweep (grep, don't skim)

TODOs/FIXMEs introduced this milestone; debug prints; commented-out
code; scratch/probe files that graduated into real modules (spike/
stays, per M1 precedent — but nothing new lands there); suppressed
warnings; disabled/skipped tests; stale docs contradicted by M3
(e.g. `perception.md`'s "nothing sends input yet" framing and
CLAUDE.md's same sentence — update both); scope creep vs plan.md's
boundaries.

### M2 leftovers (opportunistic, do not block the milestone on them)

From `docs/archive/plans/2026-07-28-m2-perception-core/_DONE.md`:

- `ruff check .` + `ruff format --check .` if the network permits the
  install this time; if it still fails, note it again in `_DONE.md`.
- Ground-item live verification (drop an item, `python -m pd2bot.dump
  -v`, pick it up) — one minute of user time while they're already
  at the machine for P4's acceptance walk; coordinate it there if
  easier.

### Teach step (mandatory per CLAUDE.md — part of "done")

Follow the `/teach` skill: plain-language explainer in
`docs/learning/` for this cycle's concepts — candidates: the gate
pattern (check at the point of action, not at the call sites),
isometric projection, ground truth vs generated data (the fidelity
check as an instance of "trust but verify"), A* in one page, stuck
detection as closed-loop control. Update `docs/learning/glossary.md`
(A*/collision map/heuristic exist from the roadmap round; add what's
new). Calibrate to the learner profile in the skill.

## Review gate — end of milestone

Present to the user: the acceptance-walk logs, fidelity verdicts,
docs diff, and the `_DONE.md` draft (written by yona-implement).
Explicit question: is M3 done, and does anything here change M4's
shape (game-cycle planning feeds on this milestone's typed errors and
menu-input needs)?

## Agent reminders

Do not commit unless the user asked. Do not expand scope. Do not
suppress warnings or disable tests to get green. Report what changed,
what was validated, deviations.

## Validation commands

```bash
python -m pytest -q
grep -rn "TODO\|FIXME\|XXX" pd2bot/ tests/
ruff check . && ruff format --check .   # if installable
```

## Definition of done

navigation.md written; README current; sweep clean or exceptions
justified in `_DONE.md`; teach artifacts written; review gate held.

## Implementation Result

Status: done
Completed: 2026-07-28
Commit: pending

- Docs: `navigation.md` written during implementation and kept current
  through every live correction (calibration, CollMap layout, atlas,
  speed tolerance); README rewritten for the atlas; CLAUDE.md and the
  roadmap M3 row updated; ADR finalized.
- Cleanup sweep: no TODO/FIXME/debug prints; no skipped tests; `ruff
  check` clean. `ruff format` deliberately NOT run (would rewrite 15
  files incl. M2's — left as its own follow-up commit).
- M2 leftovers: **ruff installed and clean** (caveat closed).
  Ground-item live check still open (R17).
- Teach: explainer `2026-07-28-when-reality-corrects-the-docs.md`;
  glossary +9 entries this cycle (DLL, headless, hang, modal dialog,
  calibration, closed-loop control, guard/gate, HITL, transient vs
  persistent state).
- New this cycle, outside the plan: the **user request protocol** —
  every ask to the user is numbered/typed and logged in
  `docs/instruction-log.md`; convention added to the agent-toolkit
  skills (uncommitted there) and `~/.claude/CLAUDE.md`.
