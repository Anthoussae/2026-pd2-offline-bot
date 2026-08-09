---
kind: implementation-log
status: done
repo: 2026-pd2-offline-bot
plan: plan.md
completed: 2026-08-09
commit: 410b7b1
adrs:
  - docs/adr/2026-08-09-package-layout.md
---

# Done — package restructure

## Outcome

**Complete, live-proven, merged.** The flat 40-module package is now six
layer subpackages named after the architecture docs; the two monoliths
are gone (`steps.py` 3,327 → ten files, largest 813; `town.py` 2,438 →
eight files, largest 424); tests mirror the tree; every documented
command works verbatim; and a full unattended Cold Plains run on the
restructured code passed with the safety monitor silent.

## Completed work (one commit per phase on branch `restructure`)

- P1 `92673f1` perception/ · P2 `954a745` input/ (guards byte-identical)
  · P3 `16bfea2` nav/, safety/, runlog/ · P4 `a9b9aae` town split
  (mixins) · P5 `35582a4` steps split (class-per-file) · P6 `af68917`
  tests mirrored · P7 `728a4e0` READMEs/docs/ADR · merge `410b7b1`.
- Root shims preserve all 13 `python -m pd2bot.X` commands;
  re-exporting `__init__`s preserve the contractual spellings
  (`from pd2bot.input import GatedInput`, `pd2bot.safety`,
  `pd2bot.runlog`, `pd2bot.behavior.steps`); `offsets.py` stays root.

## Validation

- Full suite (exactly 1169) + ruff green after EVERY phase; CI green on
  every push to `restructure` and on the merge.
- All 13 commands spot-checked (`--help` → usage, no tracebacks).
- Live bridge probe: refactored perception attached and decoded the
  running client correctly.
- **Live smoke (the merge gate): PASSED** — guarded launch via the
  bridge, one Cold Plains game: 515 ticks, waypoint open/tab/select/
  arrived, clearance fought (attacks/casts/reflexes), stash deposit,
  clean leave (exit 0). No chicken, no death latch, no safety
  interrupts; watchdog heartbeat clean. Pickup 5/11 with the KNOWN
  pre-refactor miss signatures — behavior reproduced, not regressed.

## Deviations from the plan

- P5's cut initially stranded boundary decorators (`@dataclass` lines
  sit before the class the next range owned) and one module constant's
  importers — both caught immediately by lint/tests, fixed, and noted
  in the commit message. No other deviations; bodies byte-identical.
- The smoke's first queue entry was corrupted by a printf octal-escape
  collision (`\2026` in the path) — caught at launch, before any game
  contact; requeued via heredoc.

## Documentation

pd2bot/README.md (the map) + eight subpackage READMEs; path sweep in
README/CLAUDE.md/architecture docs; dated addenda in four accepted
ADRs; teach explainer `docs/learning/2026-08-09-package-restructure.md`
+ glossary entries (refactoring, mixin, shim).

## ADRs

`docs/adr/2026-08-09-package-layout.md` (accepted): layers as folders,
commands at the root, the shim and re-export conventions, mixin splits
for oversized classes, alternatives rejected.

## Follow-up (outside scope)

- Decomposing TownLayer into collaborator objects if town logic keeps
  growing (recorded in the ADR as future work).
- The M6 work resumes on `m6-countess`; drill scripts were only
  import-adjusted, unverified live individually — run any drill's
  read-only path before trusting it in a live session.
- Root shims must stay thin (ADR consequence); a shim growing logic is
  a smell to catch in review.
