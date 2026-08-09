# ADR: the package layout — layers as folders, commands at the root

Date: 2026-08-09
Status: accepted
Plan: docs/archive/plans/2026-08-09-package-restructure/ (R239)

## Context

By M6 the flat `pd2bot/` package held ~40 sibling modules, and two files
had grown into monoliths (`behavior/steps.py` 3,327 lines, `town.py`
2,438). The architecture existed — perception, input, navigation,
safety, behavior are real boundaries with real rules — but only the
documentation said so; the folder tree didn't. The project owner is a
non-expert for whom "where is X handled?" should be answerable from the
tree itself.

## Decision

1. **One subpackage per architectural layer, named as the docs name
   them**: `perception/`, `input/`, `nav/`, `safety/`, `runlog/`,
   `behavior/` (with `behavior/town/` and `behavior/steps/` inside).
   The code and the documentation share one vocabulary.
2. **The root holds the commands and the shared vocabulary.** Every
   documented `python -m pd2bot.<name>` invocation keeps working: moved
   CLIs leave a thin root shim (docstring + `main` import + dispatch);
   `offsets.py` stays root because every layer shares it.
3. **Re-exporting `__init__.py` where a spelling is contractual or
   ubiquitous**: `from pd2bot.input import GatedInput`,
   `from pd2bot.safety import SafetyMonitor`, `from pd2bot.runlog
   import RunLog`, `from pd2bot.behavior.steps import build_registry`
   remain valid though the code lives one file deeper.
4. **Oversized single classes split as mixins, not redesigned**:
   `TownLayer` became six one-concern mixin files plus a composing
   `layer.py`, bodies byte-identical — the repo's own `_PickupMixin`
   precedent, chosen over a collaborator-object redesign because it is
   mechanical and behavior-preserving. Independent classes
   (`steps.py`) split one-class-per-file.
5. **Tests mirror the tree** (`tests/perception/test_units.py` …), and
   every package carries a one-screen `README.md`; `pd2bot/README.md`
   is the map.

## Alternatives rejected

- **Flat status quo** — structure legible only through docs; the two
  monoliths keep growing.
- **Deep `src/` layout or install-based packaging** — fights the
  repo's deliberate no-build-system choice (OneDrive crawl).
- **Changing the commands** (`python -m pd2bot.nav.navigate`) — breaks
  tools/*.ps1, drill protocols, and operator muscle memory for zero
  gain over shims.
- **Redesigning TownLayer into collaborator objects** — a real
  refactor with real risk, out of scope; recorded as future work if
  town logic keeps growing.

## Consequences

- "Where is X?" and "where is X tested?" have the same answer; grep
  and the folder tree agree with the architecture docs.
- New modules must pick a layer (or justify root placement as a
  command/shared vocabulary) — drift back to a flat pile now requires
  actively breaking the convention.
- Root shims are permanent residents: cheap, but they must stay thin.
  A shim that grows logic is a smell.
- Monkeypatch targets in tests name concrete modules (e.g.
  `pd2bot.input.gated…`), which is where patches must point anyway for
  correctness.
- Validated by the full suite per phase (1169 tests), CI per push, and
  a live smoke run before merge-back.
