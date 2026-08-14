# behavior/town/ — town errands, one concern per file

TownLayer (layer.py) composes six mixins; every step verifies its
effect through perception (a click is never trusted to have worked).
Split from the old 2,438-line town.py on 2026-08-09, bodies unchanged.

| file | one job |
|---|---|
| config.py | TownConfig, PreambleReport, the error family, helpers |
| walk.py | guarded town walking, approaching allies/objects, stray-UI clearing |
| panels.py | driving panels and dialogs: points, clicks, rows, NPC menus |
| services.py | heal at Akara, repair at Charsi, merc resurrect |
| stash.py | item and gold deposit, capacity pressure |
| belt.py | fill, minimums, excess potions, refill |
| inventory.py | drop, protect, cleanse, manage |
| layer.py | TownLayer itself: construction + the preamble order |

Import `TownLayer`, `TownConfig`, the errors from `pd2bot.behavior.town`.
