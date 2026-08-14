# perception/ — seeing the game

Reads the running client's memory (out-of-process, never injecting) and
decodes bytes into game state. Nothing here sends input.

| file | one job |
|---|---|
| memory.py | attach to the process; read/scan primitives (GameSession) |
| units.py | decode unit structures: monsters, NPCs, objects, missiles |
| player.py | the character: vitals, position, mode |
| items.py | ground and carried items, durability, sockets |
| world.py | area/level identity and the room the player is in |
| uistate.py | which panels are open (the UI array) |
| oog.py | out-of-game menu screens via the D2Win control list |
| chatread.py | read the in-game chat console |
| exits.py | staircase/exit tiles from the RoomTile chain |
| snapshot.py | the capstone: one consistent GameSnapshot per tick |

Other layers import: `GameSession`, `GameSnapshot`, the read_* functions.
Doc: docs/architecture/perception.md
