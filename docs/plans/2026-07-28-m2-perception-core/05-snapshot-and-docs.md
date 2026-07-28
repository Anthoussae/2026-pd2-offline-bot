# P5 — Snapshot API, dump tool, docs and cleanup

**Work item:** P5 · **Size:** sm · **Depends on:** P1–P4 ·
**Review gate:** none (this phase closes M2)

## Scope

Tie the pieces into one coherent surface, prove it live, document it,
and clean up.

1. **`pd2bot/snapshot.py`** — a `GameSnapshot` dataclass (player, area,
   map seed, monsters, ground items, ui state, timestamp) and
   `read_snapshot(session) -> GameSnapshot`. One call, one consistent
   view. Not in a game → a snapshot that says so, not an exception.
2. **`pd2bot/dump.py`** — `python -m pd2bot.dump` prints a readable
   snapshot; `--watch` repeats at ~5 Hz. This is the tool used for live
   verification in every later milestone, so make its output easy to
   eyeball.
3. **`docs/architecture/perception.md`** — the first component doc: how
   perception works (out-of-process reads, module base resolution, the
   structure chains), where offsets come from and how to re-verify them
   after a season patch, the base-vs-full stat trap, and the room
   traversal approach. Link to the ADRs.
4. **`README.md`** — setup: venv, install, Administrator requirement,
   how to run the dump tool.
5. **Cleanup sweep** — grep for TODOs, debug prints, commented-out code,
   scratch files, suppressed warnings, disabled tests, stale docs and
   scope creep across everything M2 added. `spike/` is exempt: it is a
   deliberate historical record, not live code.
6. **Teach step** (`/teach` per CLAUDE.md) — write
   `docs/learning/<date>-<topic>.md` for the M2 cycle and update
   `docs/learning/glossary.md`. Concepts worth covering: what a package
   and a virtual environment are and why they exist, linting and
   formatting, why pure logic is unit-testable but a live game is not
   (and what to do about it), dataclasses as a state model.
   **The user explicitly asked for this step; it is part of done.**

## Out of scope

- Any input, movement, decision-making or pathfinding (M3+).
- Performance work: measure in M3 under a real loop before optimising.
- The instruction manual (`docs/manual/`) — that is M7.

## Files

- New: `pd2bot/snapshot.py`, `pd2bot/dump.py`,
  `docs/architecture/perception.md`, `docs/learning/<date>-*.md`,
  `tests/test_snapshot.py`.
- Updated: `README.md`, `docs/learning/glossary.md`.

## Validation

- `ruff check .`, `ruff format --check .`, `pytest` — all pass.
- `python -m pd2bot.dump` against the live client produces a correct
  snapshot; `--watch` tracks movement and area changes in real time.
- Run it while **not** in a game and confirm it degrades gracefully.
- Final semantic pass: one comparison of the full dump against the
  game's own display, recorded in the Implementation Result.

## ADR expectation

None here; P2 may already have produced one.

## Agent reminders

- Do not commit unless the user asked.
- Do not expand scope into M3 territory (no input, no pathfinding).
- Do not suppress warnings or disable tests to get a clean run.
- The teach step is a deliverable, not optional polish.
- Stop and report if blocked by ambiguity or an unexpected design issue.
- Report what changed, what was validated, and any deviations.

## Definition of done

`python -m pd2bot.dump` shows a verified live snapshot, lint and tests
pass, `docs/architecture/perception.md` and the README are written, the
cleanup sweep is done, the teach explainer and glossary are updated, and
`_DONE.md` records the milestone per the yona-implement convention.
