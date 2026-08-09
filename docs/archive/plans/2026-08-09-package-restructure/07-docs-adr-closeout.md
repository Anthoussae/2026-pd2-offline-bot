# P7 — READMEs, docs sweep, ADR, cleanup, live smoke gate

Size: md. Dependencies: P1–P6. Review gate: LIVE SMOKE before
merge-back (see below).

## Scope

1. **`pd2bot/README.md`** (new): the package map — the tree with one
   line per entry, the "commands live at the root, machinery in the
   layers" rule, and pointers to docs/architecture. Written for the
   project owner (plain language).
2. **Per-subpackage `README.md`** (perception, input, nav, safety,
   runlog, behavior, behavior/town, behavior/steps): one screen each —
   what this layer is, the files and their one-line jobs, the public
   names other layers import, the architecture doc it corresponds to.
3. **First-line docstring audit**: every module in pd2bot/ has a
   docstring whose first line states its one job (most do; fix gaps —
   docstring-only edits, no code).
4. **Docs sweep** — update module paths in: CLAUDE.md (the guard
   contract names `pd2bot.input.GatedInput` — still valid spelling via
   re-export, verify rather than change; `pd2bot.menuinput.MenuInput`
   etc. DO need updating), README.md (navigation/cycle sections name
   `pd2bot/cycle.py`, `menuinput.py`, `mapdata.py`), docs/architecture/
   *.md path references, docs/adr where paths appear in accepted ADRs
   (add a dated addendum line rather than rewriting accepted decisions:
   "2026-08-09: paths updated by the package restructure, see ADR
   package-layout"). Agent memory files naming old paths
   (partyline-deferred-plan → pd2bot/partyline.py still root — verify,
   likely unchanged).
5. **ADR** `docs/adr/2026-08-09-package-layout.md` (accepted): the
   layer-subpackage convention (folders mirror architecture docs), the
   root rule (commands + shared vocabulary at root, machinery in
   layers), the shim pattern, the re-export convention, the mixin-split
   precedent for oversized classes, alternatives rejected (flat status
   quo; deep src/ layout; collaborator-object redesign of TownLayer).
6. **Cleanup grep**: no `pd2bot\.(memory|units|player|items|world|
   uistate|chatread|exits|snapshot|menuinput|panelinput|skills|window|
   screen|pathing|mapstore|mapframe|survey|waypoint|narrate|town|
   behavior\.steps\b[^.])` stale references outside docs/archive/ and
   the shims themselves; no TODO/debug prints introduced; `git status`
   clean of scratch files.
7. **Full validation**: pytest (1169), ruff, all 13 commands
   spot-checked (`--help` or equivalent, usage not traceback), CI
   green.

## The live smoke gate (review gate — do not merge back without it)

One real run through the bridge: probe first (client up? character
in?); if the client is not running, issue an `execute` request (next R
number) for the user to launch PD2 and load the character, then run
the standard guarded launch (`tools/guarded-run.ps1` path — unchanged
by this refactor, which is part of what the smoke proves) with
`--run runs/cold-plains.toml --games 1`. PASS = clean clearance, no
tracebacks, run log's events.jsonl written, monitor silent. Read the
event log after (`python -m pd2bot.runlog`), per repo method.

After PASS: merge `restructure` → `m6-countess` (ff or merge commit),
push, confirm CI, then `_DONE.md` + archive + teach step (explainer:
packages/refactoring/mixins/shims for the learner; glossary entries:
refactor, mixin, shim/facade, re-export) per convention.

## Reminders

The ADR and READMEs are for the OWNER's legibility — plain language,
no jargon without a gloss. Do not rename anything further during the
sweep. If the smoke run fails: read the run log first, fix forward
only if the cause is unambiguously the refactor's mechanics; otherwise
stop and report.
