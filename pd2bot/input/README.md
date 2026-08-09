# input/ — acting on the game

Every send path, each with its own guard re-verified at the moment of
sending. There is deliberately no bypass on any of them.

| file | one job | guard |
|---|---|---|
| gated.py | world clicks/keys (GatedInput) | can_act() AND foreground |
| menu.py | out-of-game menu clicks (MenuInput) | the complement: not in a game, or ESC menu open |
| panel.py | in-game panel clicks (PanelInput) | the named panel is verified open |
| chat.py | chat messages (Chat) | chat console verified open |
| skills.py | skill hotkey switching, effect-verified | via gated.py |
| window.py | find/foreground the game window | — |
| screen.py | world→pixel isometric projection (measured) | — |

`from pd2bot.input import GatedInput, InputRefused` is the contract
spelling (re-exported here). Docs: docs/architecture/navigation.md and
game-cycle.md; the no-bypass rule is contractual (CLAUDE.md).
