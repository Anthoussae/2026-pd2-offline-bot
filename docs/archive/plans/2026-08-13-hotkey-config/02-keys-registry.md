# P2 — the registry (`pd2bot/input/keys.py`) and fixed-key dedupe

Size sm. Depends on P1. ADR: none here.

## Scope

One module that owns every key the bot knows: VK codes, the fixed
(non-bindable) UI keys, and `KeyBindings` — the resolved per-character
bindings with a required-functions manifest. Duplicated constants in
chat/menu/window collapse into imports.

Out of scope: consumers switching their LOGIC to the registry (P3).

## Contents

- Move gated.py's VK block here verbatim (comments included — they
  carry live-test provenance). gated.py re-imports and re-exports
  (`from pd2bot.input.keys import VK_SHIFT, ...`) so no caller breaks.
- Fixed UI keys, declared once with the reason: `VK_ESCAPE`,
  `VK_RETURN`, `VK_UP/DOWN` — D2 does not let the player rebind menu
  navigation, ESC or chat; these are constants of the CLIENT, not
  bindings. chat.py / menu.py / window.py import from here (delete the
  local re-declarations; `window._VK_MENU` becomes `keys.VK_MENU`).
- `KeyBindings` dataclass: `skill_keys: tuple[int|None, ...]` (slots
  1..8, primary-or-secondary resolved: primary wins, secondary fills an
  unbound primary), `belt: tuple[int, ...]`, `inventory: int`,
  `show_items: int`, `source: str` ("keyfile:<path>" | "defaults").
- `default_bindings()` — the current hardcoded values (F1..F6 per
  DEFAULT_HOTKEYS' keys, 1..4, I, ALT) as the honest fallback.
- `load_bindings(path) -> KeyBindings` — keyfile.read + labels →
  KeyBindings; `KeyfileError` on a required function unbound, listing
  the missing function NAMES and the file path (the loud-refusal text
  the operator sees).
- Required manifest: inventory, belt 1..4, show_items, >= 1 skill slot.

## Tests

- default_bindings matches today's constants exactly (no silent drift).
- load_bindings over the P1 live-shape fixture → the operator's real
  layout; unbound inventory → KeyfileError naming "inventory".
- chat/menu/window still import (compile) — the dedupe is re-export
  based, so their tests keep passing untouched.

## Reminders

Follow session commit practice; no scope creep; report deviations.
Validation: full `pytest` + `ruff check` (the dedupe touches imports in
input modules — the whole suite is the regression net).

Done when: registry exists, dupes gone, suite green.
