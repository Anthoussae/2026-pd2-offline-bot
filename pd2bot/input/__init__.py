"""Acting on the game: every send path and its guard.

World input (gated.py), menus (menu.py), panels (panel.py), chat
(chat.py), skill hotkeys (skills.py), plus the window/projection
plumbing they share. Every path re-verifies its own guard at send time;
none has a bypass. See docs/architecture/*.md.
"""

from pd2bot.input.gated import GatedInput, InputRefused

__all__ = ["GatedInput", "InputRefused"]
