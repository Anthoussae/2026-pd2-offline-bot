# P2 — input/: the acting layer

Size: sm. Dependencies: P1. Review gate: none.

## Scope

Create `pd2bot/input/` — note `input.py` itself becomes
`input/gated.py`:

| old | new |
|---|---|
| input.py | input/gated.py |
| menuinput.py | input/menu.py |
| panelinput.py | input/panel.py |
| chat.py | input/chat.py |
| skills.py | input/skills.py |
| window.py | input/window.py |
| screen.py | input/screen.py |

`input/__init__.py` RE-EXPORTS gated.py's public names
(`GatedInput`, `InputRefused`, and whatever else `from pd2bot.input
import …` is spelled with today — grep first): this keeps the current
spelling `from pd2bot.input import GatedInput` valid everywhere,
including CLAUDE.md's contract language. Docstring: "Acting on the
game: every send path and its guard. See docs/architecture/*.md."

Root shim: `chat.py` (documented CLI `python -m pd2bot.chat`).

**The guards move UNEDITED** — `GatedInput.…can_act` logic,
`MenuInput`'s complement guard, `Chat`'s open-console guard,
`PanelInput`'s named-panel guard: byte-identical bodies.

## Import rewrite

`pd2bot.menuinput → pd2bot.input.menu`; panelinput→input.panel;
`pd2bot.chat\b → pd2bot.input.chat` (word-bound: chatread already moved
P1); skills→input.skills; window→input.window; screen→input.screen.
`pd2bot.input\b` needs care: existing `pd2bot.input._send_mouse_flag`
(quoted in tests) → `pd2bot.input.gated._send_mouse_flag`; plain
`from pd2bot.input import X` survives via the re-export — but rewrite
private-name imports (`_…`) to `pd2bot.input.gated` explicitly.
Hand-fix `from pd2bot import offsets, screen` (1 file).

## Validation

pytest/ruff; `python -m pd2bot.chat --help`; grep proves no
`menuinput|panelinput` references remain outside docs (docs are P7).
Commit `refactor: input/ subpackage (guards moved, not edited)`, push,
CI green. Extra check honoring the contract: `git diff --stat` for the
phase must show only moves + import lines — no guard-body hunks.
