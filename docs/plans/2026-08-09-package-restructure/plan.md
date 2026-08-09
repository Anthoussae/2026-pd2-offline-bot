---
kind: plan
size: md
depth: implementation
status: active
repo: 2026-pd2-offline-bot
created: 2026-08-09
adr: expected
---

# Plan — package restructure: split the giants, group the layers

## Size and why

`md` — seven phases, one agent end-to-end, but each phase must end
tests-green and committed so any failure is localized to one move. Not
`lg`: every phase is mechanical against a mapped codebase; nothing
needs its own planning pass.

## Goal

The folder tree becomes the architecture map: subpackages named after
the architecture docs (`perception/`, `input/`, `nav/`, `safety/`,
`runlog/`, `behavior/` with `town/` and `steps/` inside), no module
over ~1,000 lines, every command the operator types unchanged, and a
README in every package answering "what lives here". Explicit design
goal: legibility and queriability for a non-expert owner.

## Acceptance criteria

1. `behavior/steps.py` and `town.py` no longer exist as monoliths;
   their replacements are one-concern files, none over ~1,000 lines.
2. All 13 documented `python -m pd2bot.X` commands work verbatim
   (README, tools/*.ps1, drill protocols unchanged in what they type).
3. Full suite green (1169 tests) and ruff clean after EVERY phase; CI
   green on the `restructure` branch after every push.
4. No behavior change anywhere: moves and mechanical splits only. The
   guards (`GatedInput`, death latch, safety poll) move without edits.
5. `pd2bot/README.md` (map) + per-subpackage READMEs exist; module
   first-line docstrings state each file's one job.
6. Docs reference the new paths (CLAUDE.md, README, architecture docs).
7. One live smoke run (Cold Plains, 1 game, via the bridge) passes
   before the branch merges back to `m6-countess`.

## Constraints and conventions (binding)

- Branch: `restructure` off `m6-countess`; M6 code work pauses until
  merge-back (user decision R239: "now").
- Commit per phase (conventional message), push, watch CI.
- `git mv` for moves (history preserved).
- Import rewrites are RAW-TEXT global replaces over `pd2bot/ tests/
  drills/ sims/` — tests monkeypatch quoted paths like
  `"pd2bot.input._send_mouse_flag"`, so import-only rewriting is wrong.
  Patterns must be word-bounded (`pd2bot\.navigate\b` must not touch
  `pd2bot.navdemo`).
- Root shims for CLI modules: docstring + `from pd2bot.<new>.<mod>
  import main` + `if __name__ == "__main__": raise SystemExit(main())`
  (every CLI module already defines `main()`; verify per module, and if
  one lacks it, wrap via `runpy.run_module` instead — do not edit the
  moved module).
- Re-exporting `__init__.py` in `input/`, `runlog/`, `behavior/steps/`,
  `behavior/town/` keeps current import spellings valid where noted in
  the phase files.
- `offsets.py`, `drill.py`, `uipoints.py`, `cycle.py` stay at root
  (hub vocabulary / operator tooling / small single-purpose).
- New split files take the ORIGINAL file's full import header, then
  prune exactly what ruff F401 flags — mechanical, provably minimal.
- Do not fix, improve, or reformat moved code. A pre-existing wart
  moves as-is; note it in `notes.md` future work instead.

## Phases

| Phase | File | Summary |
|---|---|---|
| P1 | 01-perception.md | `perception/`: memory, units, player, items, world, uistate, oog, chatread, exits, snapshot (+ dump/oog shims) |
| P2 | 02-input.md | `input/`: gated, menu, panel, chat, skills, window, screen (+ chat shim, re-exporting `__init__`) |
| P3 | 03-nav-safety-runlog.md | `nav/` (pathing, navigate, collision, mapstore, mapframe, survey, waypoint, mapdata), `safety/` (safety, watchdog), `runlog/` (events, narrate) + shims |
| P4 | 04-town-split.md | `town.py` → `behavior/town/` via mixins |
| P5 | 05-steps-split.md | `behavior/steps.py` → `behavior/steps/` class-per-file |
| P6 | 06-tests-mirror.md | `tests/` reorganized to mirror the tree |
| P7 | 07-docs-adr-closeout.md | READMEs, docs sweep, ADR, cleanup grep, full validation, live smoke gate |

P1–P3 are order-independent in principle but run in order; P4 depends
on P1–P3 (town's imports); P5 on P4 (steps imports town); P6–P7 last.

## Validation strategy

Per phase: `pytest -q` (1169 passed), `ruff check .` clean, then a
shim spot-check (`python -m pd2bot.dump --help` etc. for the phase's
moved CLIs — they must print usage, not traceback), commit, push, CI
green. P7 adds: full grep for stale `pd2bot.<oldname>` references, all
13 commands spot-checked, and the live smoke run (R-request to the
user if the client is not already up; the bridge runs it).

## Documentation

P7 owns it: pd2bot/README.md + 8 subpackage READMEs; CLAUDE.md, root
README, docs/architecture/*.md path references; the agent's memory
files that name old paths. ADR: `docs/adr/2026-08-09-package-layout.md`
(expected) — records the layer/subpackage convention, the root-shim
rule, and the re-export convention as durable precedent.

## Discovery summary

See [notes.md](notes.md): the two giants' anatomies (steps splits by
class; town is one 60-method class → mixin split), 760 imports across
tests/drills/sims, 13 protected CLI invocations, the offsets-at-root
and re-export tricks that contain the churn, R239 answers (now; all
yes).
