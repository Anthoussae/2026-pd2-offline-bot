"""The game cycle: create a game, verify it, run something, leave, repeat.

This is the machine that turns "the bot can walk" (M3) into "the bot can be
left alone": it drives the client between the menus and the game world using
P1's screen perception (oog.py) and P2's menu-scoped input (menuinput.py),
and it is the intended consumer of everything the earlier milestones built.

The flow, as live verification (not folklore) established it:

    leave:  ESC -> esc menu -> click "Save and Exit Game" -> MAIN MENU
            (offline SP exits all the way out — kolbot's multiplayer lore
            says char select, and the live client said otherwise, R34)
    create: main menu -> SINGLE PLAYER -> char select (character is
            pre-selected) -> OK -> difficulty popup -> Hell -> loading ->
            in game -> player readable -> DIFFICULTY GUARD

The difficulty guard is unconditional (user decision, R29): after every game
entry, the difficulty byte is read from memory and must match the configured
target before any run logic executes. A misclicked popup therefore costs one
aborted cycle, never a poisoned atlas — difficulty is the one part of the
atlas key a misclick could silently get wrong.

"Save and Exit Game" is the one click without a control behind it (the
in-game ESC menu is not in the D2Win control list — live probe, R35), so it
uses a hover-calibrated position stored as *fractions of the client rect*
(R37), following the M3 precedent for the HUD strip.

Error taxonomy (decided at R27, notes.md):

    focus lost           -> refocus once, then pause for the human;
                            never fight a human for the mouse
    screen timeout       -> bounded click retries, then CycleError naming
                            the screen it was stuck on
    UNKNOWN screen       -> immediate CycleError with the control dump —
                            never click into a screen we cannot name
    wrong difficulty     -> leave the game, WrongDifficulty, loop halts
    NavigationError      -> the cycle fails, the loop continues (a fresh
                            game in town is the cheapest recovery there is)
    death (P4 wires in)  -> permanent halt, no input of any kind after

All timing is injected so the whole ladder runs against a scripted fake
client in tests; the game is only needed for the acceptance cycles.

    python -m pd2bot.cycle --games 3 --dwell 10
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pd2bot import offsets
from pd2bot.input.gated import InputRefused
from pd2bot.input.menu import MenuInput
from pd2bot.nav.navigate import NavigationError
from pd2bot.perception import oog, uistate, world
from pd2bot.perception.memory import GameSession
from pd2bot.safety import ChickenExit, DeathHalt


@dataclass(frozen=True)
class CycleConfig:
    difficulty: int = offsets.DIFFICULTY_HELL
    # "Save and Exit Game" center as client-rect fractions. Measured by a
    # steady hover on the real button (R37, 1536x864 window). Re-run that
    # calibration after any resolution or window-size change.
    save_exit_fraction: tuple[float, float] = (0.4889, 0.4236)
    poll_interval_s: float = 0.4
    menu_timeout_s: float = 15.0  # menu screen -> menu screen
    load_timeout_s: float = 45.0  # difficulty click -> playable game
    click_retries: int = 2  # re-clicks after the first try
    refocus_delay_s: float = 2.0
    focus_wait_s: float = 600.0  # how long to wait for a human, once paused
    # PD2 carries HP/mana between games (no heal on re-entry), so a
    # character below the chicken threshold would chicken out of every
    # game it enters, forever. Until the town-heal preamble exists (M5),
    # this backstop turns that infinite loop into a loud halt.
    max_consecutive_chickens: int = 2


class CycleError(RuntimeError):
    """The cycle could not continue; the message says where it stopped."""


class WrongDifficulty(CycleError):
    """The entered game is not the configured difficulty. Loop-halting."""


class FocusLost(CycleError):
    """Focus could not be regained and the human never returned."""


@dataclass
class CycleOutcome:
    index: int
    created: bool = False
    verified: bool = False
    ran: bool = False
    left: bool = False
    chickened: bool = False  # left early rather than completing: routine
    # Whether that early exit was actually about VITALS (R115). An idle
    # bail, a failed town step and an unexpected run error all arrive as
    # `ChickenExit` so they get the cycle's leave-and-continue handling,
    # and calling all four "CHICKEN" in the report made three of them
    # unreadable.
    vitals: bool = True
    error: str | None = None


@dataclass
class CycleReport:
    outcomes: list[CycleOutcome] = field(default_factory=list)

    @property
    def completed(self) -> int:
        """Cycles that ran to plan. A chickened cycle left safely but did
        not complete its run — it is counted separately, not as clean."""
        return sum(
            1
            for o in self.outcomes
            if o.left and o.error is None and not o.chickened
        )

    def summary(self) -> str:
        lines = [f"cycles: {len(self.outcomes)}, clean: {self.completed}"]
        for o in self.outcomes:
            steps = "".join(
                flag if ok else "-"
                for flag, ok in zip(
                    "CVRL", (o.created, o.verified, o.ran, o.left), strict=True
                )
            )
            notes = ("  CHICKEN" if o.vitals else "  LEFT EARLY") if o.chickened else ""
            notes += f"  {o.error}" if o.error else ""
            lines.append(f"  #{o.index}: [{steps}]{notes}")
        return "\n".join(lines)


class GameCycle:
    """Drives the client through create -> verify -> run -> leave cycles."""

    def __init__(
        self,
        session: GameSession,
        menu_input: MenuInput | None = None,
        config: CycleConfig | None = None,
        *,
        observe: Callable[
            [GameSession], tuple[oog.Screen, list[oog.MenuControl]]
        ] = oog.read_screen,
        read_difficulty: Callable[[GameSession], int | None] = world.read_difficulty,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.session = session
        self.menu = menu_input if menu_input is not None else MenuInput(session)
        self.config = config if config is not None else CycleConfig()
        self._observe = observe
        self._read_difficulty = read_difficulty
        self._clock = clock
        self._sleep = sleep

    # -- observation helpers ---------------------------------------------------

    def _screen(self) -> tuple[oog.Screen, list[oog.MenuControl]]:
        return self._observe(self.session)

    def _wait_for_screen(
        self,
        wanted: frozenset[oog.Screen],
        timeout_s: float,
        *,
        while_waiting: Callable[[], None] | None = None,
    ) -> tuple[oog.Screen, list[oog.MenuControl]]:
        """Poll until one of `wanted` shows up; re-trigger via `while_waiting`.

        `while_waiting` is called after each timeout slice expires without a
        match (the kolbot locationTimeout pattern: a click that did not take
        gets retried a bounded number of times before we give up).
        """
        retries = 0
        deadline = self._clock() + timeout_s
        while True:
            screen, controls = self._screen()
            if screen in wanted:
                return screen, controls
            if screen is oog.Screen.UNKNOWN:
                raise CycleError(
                    "unrecognized menu screen — refusing to click into it:\n"
                    + oog.format_dump(screen, controls)
                )
            if self._clock() >= deadline:
                if while_waiting is not None and retries < self.config.click_retries:
                    retries += 1
                    self._with_focus(while_waiting)
                    deadline = self._clock() + timeout_s
                    continue
                raise CycleError(
                    f"waited {timeout_s:.0f}s for {'/'.join(s.value for s in wanted)}, "
                    f"still seeing {screen.value}"
                )
            self._sleep(self.config.poll_interval_s)

    # -- focus policy (R27/Q8) ---------------------------------------------------

    def _with_focus(self, action: Callable[[], None]) -> None:
        """Run an input action under the focus policy: refocus once, retry
        once, else pause for the human rather than fight them for the mouse.

        The retry is deliberately unconditional on the refusal's flavor: a
        focus refusal is fixed by the refocus, and a genuine state refusal
        simply refuses again on the retry and propagates — one wasted
        attempt, no misclassification."""
        try:
            action()
            return
        except InputRefused:
            pass
        self._sleep(self.config.refocus_delay_s)
        if not self.menu.window.bring_to_foreground():
            self._pause_for_human()
        action()

    def _pause_for_human(self) -> None:
        print(
            "! game window focus lost and could not be regained — "
            "pausing; click into the game window to resume"
        )
        deadline = self._clock() + self.config.focus_wait_s
        while self._clock() < deadline:
            if self.menu.window.is_foreground():
                print("focus is back — resuming")
                return
            self._sleep(1.0)
        raise FocusLost(
            f"waited {self.config.focus_wait_s:.0f}s for the game window "
            "to be focused again"
        )

    # -- the two sequences -------------------------------------------------------

    def _save_exit_pixel(self) -> tuple[int, int]:
        rect = self.menu.window.client_rect()
        fx, fy = self.config.save_exit_fraction
        return (round(rect.left + fx * rect.width), round(rect.top + fy * rect.height))

    def _esc_menu_open(self) -> bool:
        return uistate.is_in_game(self.session) and uistate.read_ui_state(
            self.session, self.menu.ui_array
        ).is_open(offsets.UI_ESCMENU_MAIN)

    def _click_save_exit(self) -> None:
        """(Re)do the save-and-exit click, reopening the ESC menu if needed."""
        if not uistate.is_in_game(self.session):
            return  # already out; nothing to click
        if not self._esc_menu_open():
            self.menu.press_escape()
            self._sleep(self.config.poll_interval_s)
        if self._esc_menu_open():
            self.menu.click(*self._save_exit_pixel())

    def leave_game(self) -> None:
        """From in-game to the main menu, via ESC -> Save and Exit."""
        if not uistate.is_in_game(self.session):
            return

        # Open the ESC menu (bounded retries — a lag spike can eat a press).
        presses = 0
        self._with_focus(self.menu.press_escape)
        deadline = self._clock() + self.config.menu_timeout_s
        while not self._esc_menu_open():
            if not uistate.is_in_game(self.session):
                break  # already out somehow; the wait below sorts it out
            if self._clock() >= deadline:
                if presses < self.config.click_retries:
                    presses += 1
                    self._with_focus(self.menu.press_escape)
                    deadline = self._clock() + self.config.menu_timeout_s
                    continue
                raise CycleError("ESC menu never opened")
            self._sleep(self.config.poll_interval_s)

        # The M1 incident click, on purpose, through the gate that means it.
        self._with_focus(self._click_save_exit)
        self._wait_for_screen(
            frozenset({oog.Screen.MAIN_MENU, oog.Screen.CHAR_SELECT}),
            self.config.menu_timeout_s,
            while_waiting=self._click_save_exit,
        )

    def ensure_at_char_select(self) -> list[oog.MenuControl]:
        """From any recognizable state, get to char select. Returns its controls."""
        for _ in range(6):  # each pass crosses at most one screen
            screen, controls = self._screen()
            if screen is oog.Screen.CHAR_SELECT:
                return controls
            if screen is oog.Screen.IN_GAME:
                self.leave_game()
            elif screen is oog.Screen.MAIN_MENU:
                single = oog.find_control(controls, oog.SINGLE_PLAYER_BUTTON)
                if single is None:
                    raise CycleError("main menu without a SINGLE PLAYER button")
                self._with_focus(lambda c=single: self.menu.click_control(c))
                self._wait_for_screen(
                    frozenset({oog.Screen.CHAR_SELECT}), self.config.menu_timeout_s
                )
            elif screen is oog.Screen.DIFFICULTY:
                self._with_focus(self.menu.press_escape)
                self._wait_for_screen(
                    frozenset({oog.Screen.CHAR_SELECT}), self.config.menu_timeout_s
                )
            elif screen is oog.Screen.LOADING:
                self._sleep(self.config.poll_interval_s)
            elif screen is oog.Screen.ERROR_POPUP:
                raise CycleError(
                    "an error popup is up — a human should read it:\n"
                    + oog.format_dump(screen, controls)
                )
            else:
                raise CycleError(
                    "unrecognized menu screen:\n" + oog.format_dump(screen, controls)
                )
        raise CycleError("could not reach char select (state kept changing)")

    def create_game(self) -> None:
        """From wherever we are into a verified game of the right difficulty."""
        controls = self.ensure_at_char_select()

        ok = oog.find_control(controls, oog.CHAR_SELECT_OK)
        if ok is None:
            raise CycleError("char select without an OK button")
        self._with_focus(lambda: self.menu.click_control(ok))
        _, controls = self._wait_for_screen(
            frozenset({oog.Screen.DIFFICULTY}),
            self.config.menu_timeout_s,
            while_waiting=lambda: self.menu.click_control(ok),
        )

        wanted = oog.DIFFICULTY_FINGERPRINTS[self.config.difficulty]
        button = oog.find_control(controls, wanted)
        if button is None:
            wanted_name = offsets.DIFFICULTY_NAMES[self.config.difficulty]
            raise CycleError(f"difficulty popup without a {wanted_name} button")
        self._with_focus(lambda: self.menu.click_control(button))

        # Loading screens leave nulls mid-chain; poll until the world reads
        # fully (M2's established pattern), then run the guard.
        deadline = self._clock() + self.config.load_timeout_s
        while True:
            if uistate.is_in_game(self.session) and world.read_area(self.session) is not None:
                break
            if self._clock() >= deadline:
                raise CycleError("game never became readable after the difficulty click")
            self._sleep(self.config.poll_interval_s)

        actual = self._read_difficulty(self.session)
        if actual != self.config.difficulty:
            name = offsets.DIFFICULTY_NAMES.get(actual, str(actual))
            wanted_name = offsets.DIFFICULTY_NAMES[self.config.difficulty]
            self.leave_game()
            raise WrongDifficulty(
                f"entered a {name} game instead of {wanted_name} — left it; "
                "halting so the atlas cannot be poisoned"
            )

    # -- the loop -----------------------------------------------------------------

    def run_games(
        self,
        run_callback: Callable[[GameSession], None],
        max_games: int,
    ) -> CycleReport:
        """The M4 skeleton: cycle games, run the callback inside each.

        WrongDifficulty and FocusLost halt the loop (they need a human or
        threaten the atlas); NavigationError fails the cycle and continues;
        anything else propagates after being recorded.
        """
        report = CycleReport()
        consecutive_chickens = 0
        for index in range(1, max_games + 1):
            outcome = CycleOutcome(index)
            report.outcomes.append(outcome)
            try:
                self.create_game()
                outcome.created = True
                outcome.verified = True
                try:
                    run_callback(self.session)
                    outcome.ran = True
                    consecutive_chickens = 0
                except NavigationError as exc:
                    outcome.error = f"navigation: {exc}"
                except ChickenExit as exc:
                    # Routine: the whole point of the threshold is that
                    # leaving is cheap. Log it, leave, keep cycling.
                    outcome.chickened = True
                    # Only a REAL vitals chicken feeds the vitals backstop
                    # below (R115). The others each have their own counter
                    # in runner.py, kept by the layer that can describe
                    # them honestly; counting them here as well meant a
                    # hang could halt the loop with "heal the character".
                    outcome.vitals = getattr(exc, "is_vitals", True)
                    print(f"  {'chicken' if outcome.vitals else 'left early'}: {exc}")
                    if outcome.vitals:
                        consecutive_chickens += 1
                self.leave_game()
                outcome.left = True
                if (
                    outcome.chickened
                    and outcome.vitals
                    and consecutive_chickens >= self.config.max_consecutive_chickens
                ):
                    # Vitals persist between games in PD2: a character that
                    # enters below the threshold chickens out of every game.
                    # Stop the merry-go-round and say why.
                    outcome.error = (
                        f"chickened {consecutive_chickens} games in a row — "
                        "vitals likely below the threshold at game entry "
                        "(PD2 carries HP/mana between games). Heal the "
                        "character; the town-heal preamble arrives in M5."
                    )
                    break
            except DeathHalt as exc:
                # Permanent. The alert already fired inside the monitor.
                # Deliberately NO leave_game and no input of any kind: the
                # game stays exactly as it is for the human (R27/Q6).
                outcome.error = f"DEAD: {exc}"
                break
            except (WrongDifficulty, FocusLost) as exc:
                outcome.error = str(exc)
                break
            except CycleError as exc:
                outcome.error = str(exc)
                break
        return report


# --- CLI ------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse

    from pd2bot.perception.memory import GameNotRunning, NeedsAdministrator
    from pd2bot.perception.player import read_player
    from pd2bot.safety import SafetyConfig, SafetyMonitor

    parser = argparse.ArgumentParser(
        description="Run unattended game cycles (create -> verify Hell -> dwell -> leave)."
    )
    parser.add_argument("--games", type=int, default=3, help="cycles to run")
    parser.add_argument(
        "--dwell", type=float, default=10.0, help="seconds to sit in each game"
    )
    parser.add_argument(
        "--life-chicken", type=float, default=50.0,
        help="leave the game at/below this life %% (0 disables)",
    )
    parser.add_argument(
        "--mana-chicken", type=float, default=0.0,
        help="leave the game at/below this mana %% (0 disables)",
    )
    parser.add_argument(
        "--chicken-in-town", action="store_true",
        help="evaluate chicken thresholds in town too (live-test aid)",
    )
    args = parser.parse_args(argv)

    try:
        session = GameSession()
    except (GameNotRunning, NeedsAdministrator) as exc:
        print(exc)
        return 1

    cycle = GameCycle(session)
    monitor = SafetyMonitor(
        session,
        SafetyConfig(
            life_chicken_pct=args.life_chicken,
            mana_chicken_pct=args.mana_chicken,
            chicken_in_town=args.chicken_in_town,
        ),
    )

    def dwell(session: GameSession) -> None:
        player = read_player(session)
        who = f"{player.name} " if player is not None else ""
        print(f"  in game: {who}dwelling {args.dwell:.0f}s...")
        end = time.monotonic() + args.dwell
        while time.monotonic() < end:
            monitor.tick()  # raises ChickenExit / DeathHalt; cycle handles
            time.sleep(0.4)

    print(f"running {args.games} cycle(s), {args.dwell:.0f}s dwell each")
    report = cycle.run_games(dwell, args.games)
    print(report.summary())
    return 0 if report.completed == args.games else 1


if __name__ == "__main__":
    raise SystemExit(main())
