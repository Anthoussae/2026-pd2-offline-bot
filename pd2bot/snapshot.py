"""One coherent view of the game at a moment in time.

Everything above perception (navigation, behaviour) reads snapshots rather than
poking at memory itself. Snapshots are taken fresh each time; there is no
caching until something measurably needs it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from pd2bot.memory import GameSession
from pd2bot.player import Player, read_player
from pd2bot.uistate import UIState, find_ui_array, is_in_game, read_ui_state
from pd2bot.units import GroundItem, Monster, scan_units
from pd2bot.world import Area, read_area, read_map_seed


@dataclass(frozen=True)
class GameSnapshot:
    """What the game looked like when `read_snapshot` was called.

    `in_game` False means the client is sitting in the menus; the world fields
    are then empty rather than absent, so callers can read them unconditionally.
    """

    in_game: bool
    taken_at: float
    ui: UIState | None = None
    player: Player | None = None
    area: Area | None = None
    map_seed: int | None = None
    monsters: tuple[Monster, ...] = ()
    ground_items: tuple[GroundItem, ...] = ()
    skipped_units: int = 0

    @property
    def live_monsters(self) -> tuple[Monster, ...]:
        return tuple(m for m in self.monsters if m.is_alive)

    @property
    def can_act(self) -> bool:
        """Input would reach the world. Callers sending input must also check
        that the game window is in the foreground."""
        return self.in_game and self.ui is not None and not self.ui.blocks_input


class Perception:
    """Takes snapshots, remembering the things that do not change per tick.

    The UI array's address is found by parsing the client's code, which is
    cheap but pointless to redo every frame, so it is resolved once here.
    """

    def __init__(self, session: GameSession) -> None:
        self.session = session
        self._ui_array = find_ui_array(session)

    def snapshot(self) -> GameSnapshot:
        session = self.session
        taken_at = time.time()

        if not is_in_game(session):
            return GameSnapshot(in_game=False, taken_at=taken_at)

        scan = scan_units(session)
        return GameSnapshot(
            in_game=True,
            taken_at=taken_at,
            ui=read_ui_state(session, self._ui_array),
            player=read_player(session),
            area=read_area(session),
            map_seed=read_map_seed(session),
            monsters=tuple(scan.monsters),
            ground_items=tuple(scan.ground_items),
            skipped_units=scan.skipped,
        )


def read_snapshot(session: GameSession) -> GameSnapshot:
    """Convenience for one-off reads. Use `Perception` when polling."""
    return Perception(session).snapshot()
