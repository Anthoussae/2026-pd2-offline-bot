# P3 — nav/, safety/, runlog/: moving, not dying, remembering

Size: sm. Dependencies: P1–P2. Review gate: none.

## Scope

`pd2bot/nav/`: pathing.py, navigate.py, collision.py, mapstore.py,
mapframe.py, survey.py, waypoint.py, mapdata.py (dormant generator).
Root shims: navigate.py, collision.py (documented CLIs). mapdata: no
shim (undocumented as a command; docs path updated in P7).

`pd2bot/safety/`: safety.py, watchdog.py. Root shim: watchdog.py
(`tools/guarded-run.ps1` invokes `-m pd2bot.watchdog` — the shim keeps
that script untouched; verify by running the script's syntax-check path
if cheap, else grep).

`pd2bot/runlog/`: runlog.py → runlog/events.py, narrate.py →
runlog/narrate.py. `runlog/__init__.py` re-exports events' public
names (`from pd2bot.runlog import NullRunLog` etc. stay valid);
`runlog/__main__.py` = shim body (`python -m pd2bot.runlog` now hits
the package, so the entry lives in `__main__.py`, not a root shim).

## Import rewrite

pathing/mapstore/mapframe/survey/waypoint/collision/mapdata →
`pd2bot.nav.X`; `pd2bot.navigate\b → pd2bot.nav.navigate` (must not
touch pd2bot.navdemo); safety → `pd2bot.safety.safety`? NO — keep it
simple: safety.py keeps its name inside the package
(`pd2bot.safety.safety` is ugly BUT `safety/__init__.py` re-exports its
public names so callers write `from pd2bot.safety import SafetyMonitor,
SafetyInterrupt`; rewrite `pd2bot.safety\b` imports to that spelling,
quoted paths to `pd2bot.safety.safety.…` — wait, cleaner: safety.py →
safety/monitor.py, watchdog.py → safety/watchdog.py, re-export from
`__init__`). Decision: **monitor.py**. `pd2bot.watchdog →
pd2bot.safety.watchdog`; `pd2bot.narrate → pd2bot.runlog.narrate`;
`pd2bot.runlog\b` quoted/private references → `pd2bot.runlog.events`
where they name internals, else leave (re-export covers public).
Hand-fix remaining multi-name root imports (mapframe, survey, watchdog
combinations — grep `^from pd2bot import` again).

navdemo.py stays a root module (real CLI, small): rewrite its imports.

## Validation

pytest/ruff; `python -m pd2bot.navigate --help`,
`python -m pd2bot.collision --help`, `python -m pd2bot.runlog --help`,
`python -m pd2bot.watchdog --probe --help 2>&1 | head -1` (usage, not
traceback). Commit `refactor: nav/, safety/, runlog/ subpackages`,
push, CI green.
