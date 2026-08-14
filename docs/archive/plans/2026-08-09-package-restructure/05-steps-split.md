# P5 — behavior/steps.py → behavior/steps/ (class-per-file)

Size: md. Dependencies: P4. Review gate: none.

## Scope

Split `pd2bot/behavior/steps.py` (3,327 lines) into
`pd2bot/behavior/steps/`. Re-derive line ranges with
`grep -n "^class \|^def " pd2bot/behavior/steps.py` before cutting.

| file | contents (current lines, re-verify) |
|---|---|
| util.py | module helpers `_chebyshev` … `_note_unsurveyed` (51–175) |
| services.py | `RunServices` (176–507) |
| basic.py | `TownPreambleStep`, `WaypointStep`, `DoneStep` (508–688) |
| pickup.py | `_PickupMixin` (689–1469) |
| patrol.py | `_PatrolMixin` (1470–1662) |
| clear.py | `ClearRadiusStep`, `PickupStep` (1663–2075) |
| survey.py | `SurveyStep` (2076–2320) |
| traverse.py | `TraverseStep` (2321–2737) |
| countess.py | `_screen_north_point` (2738–2759), `ClearCountessStep` (2760–3219) |
| registry.py | `_checked_posture`, `build_registry` (3220–end) |
| __init__.py | re-export EVERYTHING steps.py's importers use — grep `from pd2bot.behavior.steps import` across all trees first and cover that list (at minimum: RunServices, the six Step classes, build_registry; include the mixins if tests import them) |

The re-exporting `__init__.py` means `from pd2bot.behavior.steps
import …` keeps working EVERYWHERE — external import rewrites should be
near zero; only quoted monkeypatch paths naming steps internals need
retargeting to the specific new module.

Same mechanics as P4: full import header copied per file, ruff-prune;
bodies byte-identical; docstrings name the concern; `git rm` steps.py.
Cross-references between the new files (e.g. clear.py needs
`_PickupMixin`, `_PatrolMixin`, `RunServices`, util helpers) are added
as `from pd2bot.behavior.steps.pickup import _PickupMixin` etc. —
absolute imports, matching repo style.

## Validation

pytest/ruff; `python -c "from pd2bot.behavior.steps import
build_registry, RunServices, TraverseStep"`; `python -m pd2bot.wiring
--dry-run --games 1` assembles and prints wiring without sending
anything (this exercises registry + all step classes end-to-end
offline). Commit
`refactor: split steps.py into behavior/steps/ (one concern per file)`,
push, CI green.

## Reminders

`build_registry` maps run-file step NAMES to classes — those name
strings must not change (runs/*.toml depend on them). No logic edits.
