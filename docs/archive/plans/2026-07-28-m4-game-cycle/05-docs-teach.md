# P5 — Docs, cleanup sweep, teach

Part of [M4 game cycle](plan.md). Size: `sm`. Depends on: P1–P4.
Final phase per toolkit convention.

## Scope

Documentation, repo hygiene, and the teaching step for the M4 cycle.
No functional changes except what the sweep itself uncovers (report
those; fix only the trivial ones, log the rest as follow-ups).

## Documentation

- **`docs/architecture/game-cycle.md`** (new), in the narrative style
  of `perception.md`/`navigation.md`: the OOG control list and how
  screens are classified (or the blind fallback, if that landed); the
  two-gate input story completed (`GatedInput` vs `MenuInput` — the
  complement guards, why the M1 incident click is now possible only on
  purpose); the cycle FSM and its error taxonomy; the difficulty
  guard and the map-poisoning rationale; chicken; the death latch and
  the human-takes-over policy; re-verification-after-patch section
  (control-list offsets join the seasonal re-derivation drill).
- **`docs/architecture/perception.md`**: short pointer to the OOG
  section (menus are perception too now).
- **`docs/architecture/navigation.md`**: update the two
  forward-references to M4 ("closed doors count as walls until M4" →
  doors deferred to M5/M6 per R27/Q5; "when M4 needs menu clicks…" →
  now exists, pointer to game-cycle.md).
- **`README.md`**: new CLIs (`pd2bot.oog`, `pd2bot.cycle`), one-line
  feature row for the game cycle.
- **`CLAUDE.md`**: M4 done-line (mirroring the M1–M3 pattern: what
  landed, where the docs are, archived plan link); update the
  menu-clicking sentence from future-tense mandate to done-fact with
  the invariant intact.
- **Roadmap** `docs/plans/2026-07-28-bot-from-scratch/plan.md`: M4 row
  → done + archive link (the archive move itself happens at
  `yona-implement` completion, per convention).

## Cleanup sweep

Grep and eyeball, fixing or logging:

- `TODO|FIXME|XXX|HACK` in `pd2bot/` and `tests/`.
- Debug prints / leftover diagnostic output not behind a CLI flag.
- Commented-out code, scratch files, dead imports.
- Suppressed warnings, disabled/skipped tests.
- Stale docs: statements M4 made false anywhere in `docs/`,
  `README.md`, `CLAUDE.md`.
- Scope creep: anything that landed outside the phase files' scope —
  report it honestly in `_DONE.md`.

`python -m pytest -q` and `python -m ruff check .` as the final gate.

## Teach step (per CLAUDE.md, part of "done")

Follow the `/teach` skill (it contains the learner profile — calibrate
to it): a short plain-language explainer of the cycle's key concepts
in `docs/learning/`, and glossary updates in
`docs/learning/glossary.md`. Candidate concepts (trim to what the
skill's profile wants): the control list (a UI you can *read* like
data), state machines / the game-cycle FSM, chicken logic, the death
latch (fail-stop vs fail-recover), watchdog/monitor patterns, guard
clauses and complement guards (two gates that partition the world).

## ADR check

Expectation was `possible`, leaning none (see plan.md). Decide now
with hindsight: if the control-list-vs-fallback outcome or the
fail-stop death policy feels like a direction chosen among real
alternatives with lasting consequences, write the ADR; otherwise
record in `_DONE.md` why none was warranted (the M3 precedent:
incident-forced designs are architecture-doc material, not ADRs).

## Completion convention (for the implementing agent)

`_DONE.md` in this planning directory (outcome, completed work,
validation results, deviations, docs updated, ADR decision, follow-up
work — see `yona-implement`); flip `plan.md` frontmatter to
`status: done` + `completed:` + `commit:`; do not rename any files.
Archive move to `docs/archive/plans/` per the toolkit flow.

## Agent reminders

- Do not commit unless the user asked.
- Do not expand scope; sweep findings that need real work become
  logged follow-ups, not surprise refactors.
- Report what changed, what was validated, and any deviations.

## Definition of done

All listed docs updated and mutually consistent; sweep clean or
findings logged; full test + lint pass; teach explainer + glossary
entries written; `_DONE.md` written per convention.
