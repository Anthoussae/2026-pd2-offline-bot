# P4 — town.py → behavior/town/ (mixin split)

Size: md. Dependencies: P1–P3 (town's imports already rewritten).
Review gate: none.

## Scope

Split `pd2bot/town.py` (2,438 lines) into `pd2bot/behavior/town/` by
concern, using the repo's existing mixin pattern. **Line ranges below
are from the CURRENT file — re-derive them with
`grep -n "    def \|^class \|^def " pd2bot/town.py` immediately before
cutting; do not trust these numbers after any edit.**

| file | contents (current lines, re-verify) |
|---|---|
| config.py | header/docstring, error classes (75–95), module helpers (95–144), `TownConfig` (145–356), `PreambleReport` (357–365) |
| walk.py | `_WalkMixin`: `_check_stop` … `_grid_pixel` (470–873) |
| panels.py | `_PanelMixin`: `send_until` … `open_npc_dialog` (874–1255), plus `_begin_step`/`point`/`point_pixel`/`click_point`/`select_dialog_row`/`click_in_panel_until` (they are in this range) |
| services.py | `_ServiceMixin`: `heal_at_akara`, `repair_at_charsi` (1256–1386), `resurrect_merc_if_dead` (2323–2382) |
| stash.py | `_StashMixin`: `deposit_to_stash` … `deposit_all` (1387–1653), `deposit_gold` (1766–1823), `_stash_held`/`warn_on_stash_pressure` (2151–2202) |
| belt.py | `_BeltMixin`: `fill_belt`/`assert_belt_minimums`/`_belt_accepts` (1654–1765), `_dismiss_chat_console`/`_excess_potions`/`drink_excess_potions`/`_belt_shortfall`/`refill_belt` (1824–1956) |
| inventory.py | `_InventoryMixin`: `drop_item`/`_protected`/`cleanse_inventory` (1957–2150), `manage_inventory`/`press_inventory_open` (2203–2322) |
| layer.py | `class TownLayer(_WalkMixin, _PanelMixin, _ServiceMixin, _StashMixin, _BeltMixin, _InventoryMixin):` — `__init__` (369–469) and `run_preamble` (2383–end), unchanged bodies |
| __init__.py | re-export `TownLayer`, `TownConfig`, `PreambleReport`, `TownError`, `TownStopped`, `StashFull`, `BeltBelowMinimum`, `Uncalibrated` (grep town.py for other public names first) |

Method BODIES are moved byte-identical; the only authored code is the
mixin class lines, imports, and docstrings ("Town: <concern>. Split
from town.py 2026-08-09; behavior unchanged.").

Import headers: copy town.py's full header into each new file, run
ruff, delete exactly the F401s it names. Nested helper functions inside
methods move with their method (there are several `def _gone(...)`
closures — they are INSIDE methods; line-range cuts on method
boundaries keep them intact).

Then delete `pd2bot/town.py` (git rm) and rewrite importers:
`pd2bot.town\b → pd2bot.behavior.town` (waypoint → nav/waypoint.py,
wiring.py, tests incl. quoted monkeypatch paths
`"pd2bot.town.…"` — those quoted internals must point at the mixin's
new module, e.g. `"pd2bot.behavior.town.panels.…"`; resolve each by
which file now holds the referenced name).

## Validation

pytest/ruff (test_town.py passes unmodified except its import/patch
paths); `python -c "from pd2bot.behavior.town import TownLayer"`.
MRO sanity: `python -c "from pd2bot.behavior.town import TownLayer;
print(len(TownLayer.__mro__))"`. Commit
`refactor: split town.py into behavior/town/ (mixins, bodies unchanged)`,
push, CI green.

## Reminders

If a method range is ambiguous or a body resists a clean cut, STOP and
re-derive from grep — never paraphrase code. No logic edits, no
renames of methods.
