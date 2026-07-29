"""The safety monitor: chicken out while alive, stop dead when not.

Two reflexes, both user decisions (R27), both evaluated every tick, death
always first:

**The death latch.** If the player's unit mode reads Death/Dead or hp reads
zero, the monitor latches permanently: it fires a loud local alert and from
that moment refuses to evaluate anything ever again — and the cycle, on
seeing DeathHalt, sends no input of any kind, not even leave-game. The game
is left exactly as the human needs to see it. There is deliberately no
recovery path: corpse retrieval and death recovery are deferred work, and a
bot that guesses after its character died has already guessed wrong once.

**Chicken.** Kolbot's percentage thresholds (mined from ToolsThread.js):
life at/below the threshold outside town -> leave the game immediately.
Offline SP makes this stronger than it sounds: ESC *pauses* the game
instantly, so the exit is effectively complete the moment the keypress
lands — the subsequent menu clicks happen in a paused world. Mana chicken
exists mostly as the zero-risk live test path (cast something in town with
`chicken_in_town` on and a 99% threshold), but the code path is identical
to life chicken, which is the point: testing one tests both.

The monitor observes and *signals*; the cycle owns all input. ChickenExit
is routine (the cycle leaves and continues); DeathHalt is terminal.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pd2bot import offsets
from pd2bot.memory import GameSession
from pd2bot.player import Player, read_player
from pd2bot.world import Area, read_area


class DeathHalt(RuntimeError):
    """The character is dead. Permanent: no input may follow, ever."""


class ChickenExit(RuntimeError):
    """A vitals threshold tripped: leave the game now. Routine, not fatal."""


@dataclass(frozen=True)
class SafetyConfig:
    life_chicken_pct: float = 50.0  # 0 disables
    mana_chicken_pct: float = 0.0  # off by default; the live-test path
    chicken_in_town: bool = False  # True only for the zero-risk live test


def _default_alert() -> None:  # pragma: no cover - exercised live, not in tests
    """Loud and local: the operator is at this machine by definition."""
    print("\n" + "!" * 66)
    print("!!  THE CHARACTER IS DEAD — bot halted, no further input will be sent.")
    print("!!  The game is untouched. A human takes it from here.")
    print("!" * 66 + "\n", flush=True)
    try:
        import winsound

        for _ in range(4):
            winsound.Beep(880, 350)
            winsound.Beep(440, 350)
    except Exception:
        pass  # no sound device is no reason to fail the halt


class SafetyMonitor:
    """Per-tick vitals watchdog. Raises; never sends input itself."""

    def __init__(
        self,
        session: GameSession,
        config: SafetyConfig | None = None,
        *,
        read_player_fn: Callable[[GameSession], Player | None] = read_player,
        read_area_fn: Callable[[GameSession], Area | None] = read_area,
        alert: Callable[[], None] = _default_alert,
    ) -> None:
        self.session = session
        self.config = config if config is not None else SafetyConfig()
        self._read_player = read_player_fn
        self._read_area = read_area_fn
        self._alert = alert
        self.halted = False

    def tick(self) -> None:
        """Check vitals once. Raises DeathHalt (latched) or ChickenExit."""
        if self.halted:
            # The latch: once dead, always dead, no matter what memory says
            # now — a re-created game must not resurrect the bot's confidence.
            raise DeathHalt("halted earlier; a human must restart the bot")

        player = self._read_player(self.session)
        if player is None:
            return  # menus or loading: nothing to guard yet

        if (
            player.mode in (offsets.PLAYER_MODE_DEATH, offsets.PLAYER_MODE_DEAD)
            or player.hp <= 0
        ):
            self.halted = True
            self._alert()
            raise DeathHalt(
                f"{player.name} is dead (mode {player.mode}, hp {player.hp}) — "
                "halting permanently; the game is untouched"
            )

        if not self.config.chicken_in_town:
            area = self._read_area(self.session)
            if area is not None and area.level_no in offsets.TOWN_AREAS:
                return

        if self.config.life_chicken_pct > 0 and player.max_hp > 0:
            pct = 100.0 * player.hp / player.max_hp
            if pct <= self.config.life_chicken_pct:
                raise ChickenExit(
                    f"life {player.hp}/{player.max_hp} ({pct:.0f}%) <= "
                    f"{self.config.life_chicken_pct:.0f}% threshold"
                )

        if self.config.mana_chicken_pct > 0 and player.max_mana > 0:
            pct = 100.0 * player.mana / player.max_mana
            if pct <= self.config.mana_chicken_pct:
                raise ChickenExit(
                    f"mana {player.mana}/{player.max_mana} ({pct:.0f}%) <= "
                    f"{self.config.mana_chicken_pct:.0f}% threshold"
                )
