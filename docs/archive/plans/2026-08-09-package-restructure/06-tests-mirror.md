# P6 — tests/ mirrors the tree

Size: sm. Dependencies: P5. Review gate: none.

## Scope

`git mv` test files into subdirectories mirroring pd2bot/:

- tests/perception/: test_memory… wait — map by module under test:
  test_units, test_player, test_items, test_world (if exists),
  test_uistate, test_oog, test_chatread, test_exits, test_snapshot,
  test_offsets (offsets is root — keep test_offsets at tests/ root),
  test_mapdata? (mapdata is nav) — derive the mapping by listing
  tests/ and matching each `test_X.py` to where X now lives; anything
  testing a root module (offsets, drill, cycle, uipoints, dump,
  wiring, navdemo, pickit→behavior) follows its module.
- tests/input/, tests/nav/, tests/safety/, tests/runlog/,
  tests/behavior/ (existing test_behavior_*.py move here; also
  test_town.py → tests/behavior/), tests/drills/ for test_drill*,
  test_t76/t77/t80 stay at root or a tests/drills/ folder — group them
  as tests/drills/.
- `conftest.py` and `simworld.py` STAY at tests/ root (shared fixtures;
  pytest finds root conftest for all subdirs). Check for
  `from tests.conftest import` / `from conftest import` spellings in
  moved files — repo uses `from tests.conftest import …`, which keeps
  working from subdirs unchanged.
- Do NOT add `__init__.py` files unless pytest collection fails on
  basename collision (all basenames are unique today — expect none
  needed).
- pyproject `testpaths = ["tests"]` already covers subdirs — no config
  change.

## Validation

`pytest -q` — SAME count (1169 passed, 0 new skips; a dropped test
would show as a lower count — compare exactly). ruff clean. Commit
`refactor: tests mirror the package tree`, push, CI green.
