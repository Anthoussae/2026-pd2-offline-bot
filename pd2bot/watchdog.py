"""The chicken watchdog: a second process whose only job is to press ESC.

**Why a whole process.** On 2026-08-07 the bot blocked inside a single
`walk_to` for 24 seconds while a 29-hostile pack killed the character.
The safety monitor ran only between ticks, so it never looked, and the
character died at full logged HP. The in-process fix (`safety.poll`,
called from every waiting loop in `navigate.py`) closes that hole and is
the first line of defence. This is the second, and it exists because the
first can only defend against blocks it is threaded through: a pymem
hang, a deadlock, an unhandled exception in the tick loop, the bot
process dying mid-fight. None of those can be fixed from inside the
process they happen to.

Being a separate process is the whole mechanism. The bot's GIL, its
blocking calls and its garbage collector cannot reach across a process
boundary, so this loop keeps running no matter what the bot is doing —
which is what "independent" has to mean for a safety layer, and what a
thread could never provide.

**It presses ESC and nothing else.** Offline single-player pauses the
instant the key lands (`safety.py`'s module docstring), so the character
is safe from that moment. It deliberately does NOT drive the leave-game
menu: `cycle.leave_game` is live-verified and keeps its monopoly on that
dance, and two processes clicking menus at one client is exactly the
two-writer problem worth not having. The pause simply holds until the
bot — unblocked by the walk budget — or a human resolves it.

**It sends nothing at all when the character is dead.** The same rule
the death latch has always had (R27/Q6): the game is left exactly as the
human needs to see it.

Two files carry the news to the bot, both under the bridge directory
that already hosts the drill cancel file:

- `watchdog-heartbeat` — touched every loop. The bot refuses to run
  unattended when this is stale, because a watchdog that is silently not
  running is a safety layer that silently does not exist.
- `watchdog-latch` — written when it fires, and read by `GatedInput` to
  stop world input.

Both carry a **wall-clock** timestamp, not a monotonic one: two
processes have to compare them, and monotonic clocks are meaningless
across a process boundary. Both are treated as STALE after a while,
which is the lesson the drill cancel file already taught this project
the hard way — a sticky file that nobody clears becomes a bot that
cannot act and cannot say why.

    python -m pd2bot.watchdog --probe          read vitals, arm nothing
    python -m pd2bot.watchdog --threshold 30   guard at 30% life
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pd2bot import offsets
from pd2bot.perception import uistate
from pd2bot.perception.memory import GameSession
from pd2bot.perception.player import Player, read_player
from pd2bot.perception.world import Area, read_area

BRIDGE_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "pd2bot-bridge"
HEARTBEAT_FILE = BRIDGE_DIR / "watchdog-heartbeat"
LATCH_FILE = BRIDGE_DIR / "watchdog-latch"

# How long a heartbeat stays believable. Generous against the 0.2 s
# poll — a memory read that blocks, or a scheduler that does not run us
# for a moment, must not read as "the watchdog is gone".
HEARTBEAT_STALE_AFTER_S = 3.0
# How long a latch stands. A fired watchdog has paused the game and the
# operator has to deal with it, so this is minutes rather than seconds —
# but it is NOT forever, because a latch nobody clears is an outage of
# its own, and this project has already paid for that with the cancel
# file (`drill.py`, and the live protocol's "the cancel file is sticky").
LATCH_STALE_AFTER_S = 300.0

# The gap between the bot's chicken threshold and ours. A backstop that
# fires first is not a backstop: the bot's own leave is graceful, logged
# and live-verified, and it should win every time it is capable of
# winning. We act only when it did not.
THRESHOLD_GAP_PCT = 5.0

DEFAULT_INTERVAL_S = 0.2
# Firing is verified, not assumed: if a blocking panel was open, ESC
# closed THAT instead and the game is not paused at all. So press, look,
# press again — bounded, because a client that will not pause is a
# problem no amount of pressing solves.
MAX_PRESSES = 5
PRESS_SPACING_S = 0.3
# Consecutive death-looking reads before the death latch is believed.
# Three at the 0.2 s poll is ~0.6 s of agreement — long enough to outlast
# a torn read on a loading screen, short enough to be irrelevant to a
# character who is actually dead.
DEATH_CONFIRMATIONS = 3


# -- the file channel, readable by anyone -------------------------------------


def write_heartbeat(path: Path = HEARTBEAT_FILE, now: float | None = None) -> bool:
    """Say we are alive. Returns whether the beat actually landed.

    **Written to a temp file and renamed**, which matters more than it
    looks. This file is written 5x a second and read by two other
    processes (the bot every tick, the launcher while it waits), and a
    plain `write_text` opens the destination for writing — which on
    Windows collides with a concurrent reader and fails. Measured
    2026-08-08: the watchdog beat reliably for ~10 s and then stopped
    while still running, silently, because every one of those failures
    was swallowed. `os.replace` is atomic, so a reader either sees the
    old beat or the new one, never a half-written file and never a lock
    the writer trips over.

    Still never raises — a missed beat must not kill the one process
    whose whole purpose is to still be running — but it now REPORTS the
    miss, so a run of them can be noticed instead of inferred.
    """
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps({"at": now if now is not None else time.time(), "pid": os.getpid()}),
            encoding="utf-8",
        )
        os.replace(tmp, path)
        return True
    except Exception:  # noqa: BLE001 - a missed beat beats a dead watchdog
        return False


def heartbeat_age(
    path: Path = HEARTBEAT_FILE, now: float | None = None
) -> float | None:
    """Seconds since the last beat, or None if there is none to read."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        at = float(data["at"])
    except Exception:  # noqa: BLE001 - unreadable is the same as absent
        return None
    return (now if now is not None else time.time()) - at


def watchdog_is_alive(
    path: Path = HEARTBEAT_FILE,
    now: float | None = None,
    stale_after: float = HEARTBEAT_STALE_AFTER_S,
) -> bool:
    age = heartbeat_age(path, now)
    return age is not None and age <= stale_after


def write_latch(
    reason: str,
    path: Path = LATCH_FILE,
    now: float | None = None,
    **fields: object,
) -> None:
    """Record that the watchdog acted. Written BEFORE the first keypress,
    so a watchdog that dies mid-fire still leaves the bot the news."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "reason": reason,
                    "at": now if now is not None else time.time(),
                    "pid": os.getpid(),
                    **fields,
                }
            ),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        return


def read_latch(path: Path = LATCH_FILE) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def active_latch(
    path: Path = LATCH_FILE,
    now: float | None = None,
    stale_after: float = LATCH_STALE_AFTER_S,
) -> dict | None:
    """The latch, but only while it still means something.

    Staleness is not a detail: without it, one forgotten file disarms
    every future run and the failure looks like a bot that refuses to
    click for no reason.
    """
    latch = read_latch(path)
    if latch is None:
        return None
    try:
        age = (now if now is not None else time.time()) - float(latch["at"])
    except Exception:  # noqa: BLE001 - a latch we cannot date is not one we trust
        return None
    return latch if age <= stale_after else None


def clear_latch(path: Path = LATCH_FILE) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        return


# -- the watchdog itself -------------------------------------------------------


@dataclass(frozen=True)
class WatchdogConfig:
    life_pct: float = 30.0
    mana_pct: float = 0.0  # the zero-risk live-test path, as in safety.py
    in_town: bool = False
    interval_s: float = DEFAULT_INTERVAL_S


def _default_say(text: str) -> None:  # pragma: no cover - live only
    """Routine news: printed, never sounded.

    The distinction is load-bearing rather than tidy. `_default_alert`
    beeps, and `winsound.Beep` blocks the calling thread for the duration
    — so anything reachable from inside the 5 Hz poll loop must come
    through HERE. On 2026-08-08 a 30 s "still watching" line went through
    the alarm instead and the loop stopped dead after the first one.
    """
    try:
        print(f"watchdog: {text}", flush=True)
    except Exception:  # noqa: BLE001 - a closed stdout is not fatal
        pass


def _default_alert(text: str) -> None:  # pragma: no cover - live only
    print("\n" + "!" * 66)
    print(f"!!  WATCHDOG: {text}")
    print("!" * 66 + "\n", flush=True)
    try:
        import winsound

        for _ in range(3):
            winsound.Beep(1200, 250)
    except Exception:  # noqa: BLE001
        pass


class Watchdog:
    """Poll vitals; press ESC when they cross; never do anything else."""

    def __init__(
        self,
        session: GameSession,
        config: WatchdogConfig | None = None,
        *,
        press_escape: Callable[[], None],
        read_player_fn: Callable[[GameSession], Player | None] = read_player,
        read_area_fn: Callable[[GameSession], Area | None] = read_area,
        esc_menu_open: Callable[[], bool] | None = None,
        ensure_focus: Callable[[], bool] | None = None,
        alert: Callable[[str], None] = _default_alert,
        say: Callable[[str], None] = _default_say,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        heartbeat_path: Path = HEARTBEAT_FILE,
        latch_path: Path = LATCH_FILE,
    ) -> None:
        self.session = session
        self.config = config if config is not None else WatchdogConfig()
        self._press = press_escape
        self._read_player = read_player_fn
        self._read_area = read_area_fn
        self._esc_menu_open = esc_menu_open
        self._ensure_focus = ensure_focus
        self._alert = alert
        # Everything reachable from inside the poll loop goes through
        # `say`, never `alert`: the alarm beeps, and a beep blocks.
        self._say = say
        self._clock = clock
        self._wall = wall
        self._sleep = sleep
        self._heartbeat = heartbeat_path
        self._latch = latch_path
        self.fired = False
        self.stopped = False
        self.presses = 0
        # Consecutive failed reads. While this is non-zero we are blind
        # and deliberately not heartbeating — see `_blind`.
        self._read_failures = 0
        # Consecutive heartbeats that did not land — see `_beat`.
        self._beat_failures = 0
        # Consecutive death-looking reads — see `tick`.
        self._deaths_seen = 0
        # How often `run` says it is still here, in ticks (~30 s).
        self._alive_every = max(1, int(30.0 / max(self.config.interval_s, 0.01)))
        # Cleared ONCE, at construction, exactly like `drill.py`'s stale
        # cancel: a latch left over from a previous session must not
        # disarm this one, and clearing it per iteration would wipe the
        # latch we ourselves just wrote.
        clear_latch(self._latch)

    # -- one pass ------------------------------------------------------------

    def tick(self) -> None:
        """One poll. Heartbeat only while we can SEE; act on what we see.

        The heartbeat used to be written first, unconditionally. That was
        a lie in the making: a watchdog whose reads are failing is not
        guarding anything, and a bot told otherwise runs on a promise
        nobody is keeping. It is now earned by a successful read.
        """
        if self.stopped:
            # Still beating: the bot must be able to tell "the watchdog
            # is gone" from "the watchdog saw a death and stood down".
            self._beat()
            return

        try:
            player = self._read_player(self.session)
        except Exception as exc:  # noqa: BLE001 - see _blind
            self._blind(exc)
            return

        # A successful read — INCLUDING "no player", which is exactly what
        # menus and loading screens look like — means we are watching.
        self._read_failures = 0
        write_heartbeat(self._heartbeat, self._wall())

        if player is None:
            return  # menus or loading: nothing to guard yet

        if self._looks_dead(player):
            self._deaths_seen += 1
        else:
            self._deaths_seen = 0

        # Corroborate before latching. This poll runs at 5 Hz straight
        # through the loading screen, where hp reads 0 for a moment while
        # the character is perfectly alive — measured 2026-08-08, a false
        # death latched with `hp 0, max_hp 921, mode 5`, and mode 5 is a
        # LIVING mode. The bot's own monitor has the same test but only
        # asks between ticks, so it never sat in that window.
        #
        # Delay costs nothing that matters: a character who is genuinely
        # dead is still dead 0.6 s later, and the watchdog sends nothing
        # either way. A false death costs the run AND disarms world input
        # through the latch, which is how this one announced itself.
        if self._deaths_seen >= DEATH_CONFIRMATIONS:
            # The death rule, unchanged from the monitor's: send NOTHING.
            # A dead character's game is left exactly as the human needs
            # to see it, and a watchdog pressing keys at a corpse is a
            # watchdog guessing after the guess already went wrong.
            self.stopped = True
            write_latch(
                "death", self._latch, self._wall(),
                hp=player.hp, max_hp=player.max_hp, mode=player.mode,
            )
            self._alert("the character is DEAD — sending nothing, game untouched")
            return

        if self._looks_dead(player):
            # Death-shaped but not yet corroborated, so these numbers are
            # not trustworthy for ANY decision. Without this the same
            # torn read that was rejected as a death two lines up gets
            # believed as a chicken instead — 0/921 is 0%, under every
            # threshold there is — and the watchdog pauses the game on
            # every loading screen.
            #
            # Note what this does NOT delay: a real crossing reads ~30%,
            # not zero, so it is unaffected. Only the exactly-zero case
            # waits, and only for the ~0.6 s it takes to agree with itself.
            return

        if self.fired:
            return  # already paused; do not keep pressing at a paused game

        if not self.config.in_town:
            try:
                area = self._read_area(self.session)
            except Exception:  # noqa: BLE001 - unreadable is NOT "in town"
                # Fail toward guarding. Treating an unreadable area as
                # town would silently disarm the watchdog exactly when
                # perception is struggling, which is not the moment to
                # stop watching.
                area = None
            if area is not None and area.level_no in offsets.TOWN_AREAS:
                return

        verdict = self._crossed(player)
        if verdict is not None:
            self._fire(*verdict, player)

    @staticmethod
    def _looks_dead(player: Player) -> bool:
        """One observation that could be death. Not a verdict — see tick.

        A death MODE is trustworthy on its own: the client sets it, and
        nothing else does. Zero hp is not: it is also what a torn read
        looks like mid-load. Requiring `max_hp > 0` throws out the wholly
        uninitialised reads; the repeat count in `tick` handles the rest.
        """
        if player.mode in (offsets.PLAYER_MODE_DEATH, offsets.PLAYER_MODE_DEAD):
            return True
        return player.hp <= 0 and player.max_hp > 0

    def _crossed(self, player: Player) -> tuple[str, float] | None:
        if self.config.life_pct > 0 and player.max_hp > 0:
            pct = 100.0 * player.hp / player.max_hp
            if pct <= self.config.life_pct:
                return "life", pct
        if self.config.mana_pct > 0 and player.max_mana > 0:
            pct = 100.0 * player.mana / player.max_mana
            if pct <= self.config.mana_pct:
                return "mana", pct
        return None

    def _fire(self, reason: str, pct: float, player: Player) -> None:
        """Press ESC until the game is verifiably paused, or give up loudly.

        The latch goes down FIRST. If this process dies between the write
        and the press, the bot still learns a watchdog chicken happened;
        the other order would lose that entirely.
        """
        write_latch(
            reason, self._latch, self._wall(),
            pct=round(pct, 1), hp=player.hp, max_hp=player.max_hp,
            mana=player.mana, max_mana=player.max_mana,
        )
        # Said, not sounded, and said BEFORE nothing. `_default_alert`
        # beeps three times (~0.75 s of blocking audio), and this used to
        # sit between the verdict and the first keypress — three quarters
        # of a second of siren added to the one path where latency is
        # measured in health. The alarm still fires, after the game is
        # paused, where its cost is zero.
        self._say(
            f"{reason} {pct:.0f}% <= {self.config.life_pct:.0f}% — pressing ESC"
        )
        for attempt in range(MAX_PRESSES):
            if attempt:
                self._sleep(PRESS_SPACING_S)
            self._take_the_window()
            try:
                self._press()
                self.presses += 1
            except Exception as exc:  # noqa: BLE001 - a refused press is not fatal
                self._say(f"ESC refused ({type(exc).__name__}: {exc}) — retrying")
                continue
            if self._paused():
                self.fired = True
                self._alert(f"game PAUSED after {self.presses} press(es)")
                return
            # Not paused: something else ate that ESC — a blocking panel
            # closes before the menu opens. Press again rather than
            # assume, which is the difference between this and hope.
        self.fired = True  # do not spin forever; the operator has been told
        self._alert(
            f"pressed ESC {self.presses}x and the ESC menu never opened — "
            "the game may NOT be paused; take the controls"
        )

    def _take_the_window(self) -> None:
        """Get the game focused before pressing, if something else has it.

        `press_escape` guards on foreground and nothing else — so a
        watchdog that never refocuses cannot save a character while the
        operator is alt-tabbed, which is exactly when nobody is watching
        and the layer matters most. Best effort: a refusal here is not
        fatal, because the press below reports its own refusal and the
        loop retries.

        Cheap when it is already ours (a foreground check, no keystroke),
        which matters: this sits on the fire path, where every 100 ms is
        health. The escalation only runs when the window really is not
        ours, and its inert ALT then lands on whatever stole it — never
        on the game, where ALT toggles item labels.
        """
        if self._ensure_focus is None:
            return
        try:
            if not self._ensure_focus():
                self._say("could not take the game window — pressing anyway")
        except Exception as exc:  # noqa: BLE001 - never block the press
            self._say(f"focus attempt failed ({type(exc).__name__}: {exc})")

    def _paused(self) -> bool:
        """Did the ESC actually pause the game? Verified, never assumed."""
        if self._esc_menu_open is None:
            return True  # nothing to verify with: one press is all we have
        try:
            return self._esc_menu_open()
        except Exception:  # noqa: BLE001 - unreadable: press again, do not claim
            return False

    # -- the loop ------------------------------------------------------------

    def _beat(self) -> None:
        """One heartbeat, and a complaint if beats stop landing.

        The write can fail — a reader holding the file, a full disk — and
        swallowing that silently is how a watchdog comes to look dead
        while running perfectly (2026-08-08). A miss is tolerable; a run
        of them means the bot is about to stand down and the operator
        should be told why by the watchdog, not left to infer it.
        """
        if write_heartbeat(self._heartbeat, self._wall()):
            self._beat_failures = 0
            return
        self._beat_failures += 1
        if self._beat_failures in (3, 15) or self._beat_failures % 100 == 0:
            self._say(
                f"could not write the heartbeat {self._beat_failures}x in a row "
                f"({self._heartbeat}) — the bot will stand down, but this "
                "watchdog is alive and still guarding"
            )

    def _blind(self, exc: BaseException) -> None:
        """A read failed, so we cannot say anything about the character.

        Deliberately does NOT heartbeat. The bot's staleness window is
        the tolerance budget: a torn read during an area change costs a
        few ticks and nobody notices, while a watchdog that has genuinely
        lost the client goes quiet and stands the bot down. Silence is
        the honest signal; a heartbeat here would be a lie.

        Live on 2026-08-08 this was fatal rather than merely dishonest —
        the loop had no handler at all, so the first read error during
        the waypoint transition killed the process outright, ~16 s into
        the run. The bot caught it (the dead-man switch worked and it
        left the game cleanly), but the layer was gone.
        """
        self._read_failures += 1
        if self._read_failures in (1, 5, 25) or self._read_failures % 100 == 0:
            self._say(
                f"cannot read the game ({type(exc).__name__}: {exc}) — "
                f"not heartbeating while blind ({self._read_failures} in a row)"
            )

    def run(self, until: Callable[[], bool] | None = None) -> None:
        """Poll forever (or until `until` says otherwise).

        Nothing that happens in one tick may end this process. It is the
        one program whose entire job is to still be running, and it has
        no supervisor of its own — if it dies, the layer is simply gone.
        `tick()` already declines to heartbeat when it cannot see, so a
        persistent failure still stands the bot down, loudly, without
        this loop ever exiting.
        """
        ticks = 0
        while not (until is not None and until()):
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - see the docstring
                self._blind(exc)
            ticks += 1
            # A periodic "still here" line. Twice now this process has
            # gone quiet mid-run with no error of any kind — no failed
            # read, no failed write, no death — and the only evidence was
            # the BOT noticing a stale heartbeat minutes later. A log that
            # only speaks when something is wrong cannot distinguish
            # "stopped at 30 s" from "stopped at 3 minutes", and that
            # difference is the whole diagnosis.
            if ticks % self._alive_every == 0:
                # A plain line, NOT an alert. `_default_alert` beeps three
                # times through `winsound`, which is a blocking call into
                # the audio stack — fine for the once-per-run alarm it was
                # written for, wrong for a routine 30 s tick, and on
                # 2026-08-08 the loop stopped dead immediately after the
                # first one. Routine news does not get the siren.
                self._say(
                    f"still watching — {ticks} ticks, "
                    f"{ticks * self.config.interval_s:.0f}s"
                )
            if self.stopped:
                return
            self._sleep(self.config.interval_s)


# -- CLI -----------------------------------------------------------------------


def _raise_priority() -> None:  # pragma: no cover - live only
    """Best effort. The independence comes from being a separate process,
    not from priority; this only trims scheduling jitter."""
    try:
        HIGH_PRIORITY_CLASS = 0x00000080
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.kernel32.SetPriorityClass(handle, HIGH_PRIORITY_CLASS)
    except Exception:  # noqa: BLE001
        pass


def default_threshold() -> float:
    """Five points under the bot's own, from the same class config — one
    number, so the two can never drift apart."""
    from pd2bot.behavior.combat import load_class_config
    from pd2bot.wiring import BotPaths

    try:
        configured = load_class_config(BotPaths().class_config).chicken_life_pct
    except Exception:  # noqa: BLE001 - a missing config is not a reason to be unarmed
        return WatchdogConfig().life_pct
    return max(1.0, configured - THRESHOLD_GAP_PCT)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - live only
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--threshold", type=float, default=None,
                        help="life %% to fire at (default: 5 under the bot's)")
    parser.add_argument("--mana", type=float, default=0.0,
                        help="mana %% to fire at — the zero-risk live test")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_S)
    parser.add_argument("--in-town", action="store_true",
                        help="guard in town too (the canary needs this)")
    parser.add_argument("--probe", action="store_true",
                        help="read and print vitals; arm nothing, send nothing")
    args = parser.parse_args(argv)

    from pd2bot.input.menu import MenuInput

    session = GameSession()
    threshold = args.threshold if args.threshold is not None else default_threshold()

    if args.probe:
        player = read_player(session)
        area = read_area(session)
        if player is None:
            print("no player — the client is in the menus")
            return 0
        pct = 100.0 * player.hp / player.max_hp if player.max_hp else 0.0
        print(f"{player.name}: {player.hp}/{player.max_hp} life ({pct:.0f}%), "
              f"{player.mana}/{player.max_mana} mana, "
              f"area {area.level_no if area else '?'}, mode {player.mode}")
        print(f"would fire at life <= {threshold:.0f}% — NOTHING IS ARMED")
        return 0

    # A native crash inside the memory reader would otherwise leave no
    # trace at all — no traceback, no stderr, just a process that stopped.
    # Twice on 2026-08-08 that was the entire symptom.
    try:
        import faulthandler

        faulthandler.enable()
    except Exception:  # noqa: BLE001
        pass

    _raise_priority()
    menu = MenuInput(session)
    ui_array = menu.ui_array
    window = menu.window

    def ensure_focus() -> bool:
        """Ours already? Say so without touching anything. Otherwise take
        it — `bring_to_foreground` escalates on its own when the polite
        request is refused, which it always is for a background process."""
        return window.is_foreground() or window.bring_to_foreground()

    watchdog = Watchdog(
        session,
        WatchdogConfig(
            life_pct=threshold, mana_pct=args.mana,
            in_town=args.in_town, interval_s=args.interval,
        ),
        press_escape=menu.press_escape,
        esc_menu_open=lambda: uistate.read_ui_state(session, ui_array).is_open(
            offsets.UI_ESCMENU_MAIN
        ),
        ensure_focus=ensure_focus,
    )
    print("=" * 66)
    print(f"  WATCHDOG ARMED — life <= {threshold:.0f}%"
          + (f", mana <= {args.mana:.0f}%" if args.mana else "")
          + (" (town included)" if args.in_town else ""))
    print(f"  polling every {args.interval:.2f}s. Ctrl+C to disarm.")
    print("=" * 66, flush=True)
    try:
        watchdog.run()
    except KeyboardInterrupt:
        print("\nwatchdog disarmed by the operator", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


