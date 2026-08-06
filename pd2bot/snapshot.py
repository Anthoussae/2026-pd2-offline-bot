"""One coherent view of the game at a moment in time.

Everything above perception (navigation, behaviour) reads snapshots rather than
poking at memory itself. Snapshots are taken fresh each time; there is no
caching until something measurably needs it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from pd2bot import offsets
from pd2bot.memory import GameSession
from pd2bot.player import ActiveSkills, Player, read_active_skills, read_player
from pd2bot.uistate import UIState, find_ui_array, is_in_game, read_ui_state
from pd2bot.units import GameObject, GroundItem, Monster, scan_units
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
    monsters: tuple[Monster, ...] = ()  # hostiles only
    allies: tuple[Monster, ...] = ()  # mercenary, summons, friendly NPCs
    ground_items: tuple[GroundItem, ...] = ()
    corpses: tuple[Monster, ...] = ()  # dead type-1 units: revive fuel (M5)
    # Decorative units — bats, chickens, cows (T74, 2026-08-06). NOT in
    # `monsters`, so combat never sees them; reported so the run log can
    # show what was really in the room. The bot spent 173 s attacking two
    # of these before anything could tell them from a Fallen.
    critters: tuple[Monster, ...] = ()
    objects: tuple[GameObject, ...] = ()  # waypoints, stash, doors (M5)
    skills: ActiveSkills | None = None  # active left/right skill ids (M5)
    skipped_units: int = 0

    @property
    def live_monsters(self) -> tuple[Monster, ...]:
        return tuple(m for m in self.monsters if m.is_alive)

    @property
    def can_act(self) -> bool:
        """Input would reach the world. Callers sending input must also check
        that the game window is in the foreground."""
        return self.in_game and self.ui is not None and not self.ui.blocks_input

    @property
    def in_town(self) -> bool:
        return self.area is not None and self.area.level_no in offsets.TOWN_AREAS

    @property
    def merc(self) -> Monster | None:
        """The hireling, alive, or None. A dead merc has left the ally list
        (its corpse routes to `corpses`), so absence means dead-or-none."""
        for ally in self.allies:
            if ally.merc_kind is not None and ally.is_alive:
                return ally
        return None

    @property
    def revives(self) -> tuple[Monster, ...]:
        """Revived monsters currently following the player.

        Only meaningful outside town: in town the friendly-NPC population
        shares the ally list and would pollute the count, so town reports
        none rather than a lie. (Caveat, noted for the day F4 gets used:
        a cast bone wall may also appear as allied units.)
        """
        if self.in_town:
            return ()
        return tuple(
            a for a in self.allies if a.merc_kind is None and a.is_alive
        )


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
            allies=tuple(scan.allies),
            ground_items=tuple(scan.ground_items),
            corpses=tuple(scan.corpses),
            critters=tuple(scan.critters),
            objects=tuple(scan.objects),
            skills=read_active_skills(session),
            skipped_units=scan.skipped,
        )


def read_snapshot(session: GameSession) -> GameSnapshot:
    """Convenience for one-off reads. Use `Perception` when polling."""
    return Perception(session).snapshot()
