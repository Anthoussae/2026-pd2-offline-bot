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
| keys.py | THE keybinding registry: VK codes, fixed UI keys, the character's resolved bindings (R247) | refuses on unbound required functions / toml drift |
| keyfile.py | parse the client's per-character `.key` file (self-validating; format pinned empirically) | refuses anything that does not prove itself |
| window.py | find/foreground the game window | — |
| screen.py | world→pixel isometric projection (measured) | — |

`from pd2bot.input import GatedInput, InputRefused` is the contract
spelling (re-exported here). Docs: docs/architecture/navigation.md and
game-cycle.md; the no-bypass rule is contractual (CLAUDE.md).
