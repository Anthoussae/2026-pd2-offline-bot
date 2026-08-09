# P1 — perception/: the seeing layer

Size: sm. Dependencies: none (first phase). Review gate: none.

## Scope

Create `pd2bot/perception/` and move, with `git mv`:
`memory.py units.py player.py items.py world.py uistate.py oog.py
chatread.py exits.py snapshot.py`.

`__init__.py`: module docstring ("Seeing the game: …, see
docs/architecture/perception.md") only — no re-exports (importers are
rewritten instead; the two spellings below are the exception).

Root shims (CLI preserved): `dump.py` does NOT move (it is already a
thin CLI over snapshot/memory — keep it at root, rewrite its imports).
`oog.py` moves; leave root shim `oog.py` (main() pattern; verify
`main()` exists first).

## Import rewrite (raw text, word-bounded, over pd2bot/ tests/ drills/ sims/)

`pd2bot.memory → pd2bot.perception.memory`, same for units, player,
items, world, uistate, oog, chatread, exits, snapshot. Apply to quoted
monkeypatch strings too (raw-text replace does this).

Then fix the ~14 multi-name root imports by hand (grep
`^from pd2bot import` across all four trees): e.g.
`from pd2bot import offsets, uistate` →
`from pd2bot import offsets` + `from pd2bot.perception import uistate`.
`from pd2bot import offsets` alone stays untouched (offsets stays root).

## Out of scope

No content edits to moved files beyond their own import lines. dump.py
stays root. No README yet (P7).

## Validation

`pytest -q` 1169 passed; `ruff check .` clean;
`python -m pd2bot.dump --help` and `python -m pd2bot.oog --help` print
usage. Commit `refactor: perception/ subpackage (mechanical move)`,
push, CI green.

## Reminders

Do not expand scope; do not fix code smells encountered; stop and
report if a move produces a circular import (expected clean: perception
modules import only memory/offsets/each other).
