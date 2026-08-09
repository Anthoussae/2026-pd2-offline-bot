"""GameCycle against a scripted fake client: sequences, guard, taxonomy.

The fake models the client as a small state machine that reacts to the same
calls the real one receives (press_escape, clicks) — so the tests exercise
the cycle's real decision logic end to end, with no OS and no game.
"""

from __future__ import annotations

import pytest

from pd2bot import offsets
from pd2bot.cycle import (
    CycleConfig,
    CycleError,
    FocusLost,
    GameCycle,
    WrongDifficulty,
)
from pd2bot.input.gated import InputRefused
from pd2bot.input.window import ClientRect
from pd2bot.nav.navigate import NavigationError
from pd2bot.perception import oog, uistate

RECT = ClientRect(left=0, top=0, width=1536, height=864)


def control(rect: tuple[int, int, int, int], text: str = "") -> oog.MenuControl:
    x, y, w, h = rect
    return oog.MenuControl(
        address=0, ctype=offsets.CONTROL_TYPE_BUTTON, state=5,
        x=x, y=y, width=w, height=h, text=text,
    )


SCREEN_CONTROLS = {
    oog.Screen.MAIN_MENU: [
        control(oog.SINGLE_PLAYER_BUTTON, "SINGLE PLAYER"),
        control((264, 568, 272, 35), "EXIT DIABLO II"),
    ],
    oog.Screen.CHAR_SELECT: [
        control((33, 528, 168, 60), "CREATE NEW"),
        control(oog.CHAR_SELECT_OK, "OK"),
    ],
    oog.Screen.DIFFICULTY: [
        control(oog.DIFFICULTY_FINGERPRINTS[offsets.DIFFICULTY_NORMAL], "NORMAL"),
        control(oog.DIFFICULTY_FINGERPRINTS[offsets.DIFFICULTY_NIGHTMARE], "NIGHTMARE"),
        control(oog.DIFFICULTY_FINGERPRINTS[offsets.DIFFICULTY_HELL], "HELL"),
    ],
    oog.Screen.IN_GAME: [],
    oog.Screen.LOADING: [],
    oog.Screen.ERROR_POPUP: [control((351, 337, 96, 32), "OK")],
}


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class ScriptedClient:
    """The client as a state machine; also plays the roles of MenuInput
    (duck-typed), the observe() function, and the difficulty reader."""

    def __init__(self, state: oog.Screen = oog.Screen.CHAR_SELECT) -> None:
        self.state = state
        self.esc_menu = False
        self.difficulty_entered = offsets.DIFFICULTY_HELL
        self.current_difficulty: int | None = None
        self.foreground = True
        self.log: list[str] = []
        # Failure injection knobs
        self.eat_next_clicks = 0  # clicks that silently do nothing
        self.eat_next_escapes = 0

    # -- window duck-type ------------------------------------------------------

    @property
    def window(self):
        return self

    def client_rect(self) -> ClientRect:
        return RECT

    def is_foreground(self) -> bool:
        return self.foreground

    def bring_to_foreground(self) -> bool:
        self.log.append("refocus")
        return self.foreground

    @property
    def ui_array(self) -> int:
        return 0

    # -- MenuInput duck-type -----------------------------------------------------

    def _check_focus(self) -> None:
        if not self.foreground:
            raise InputRefused("the game window is not in the foreground")

    def press_escape(self) -> None:
        self._check_focus()
        self.log.append("esc")
        if self.eat_next_escapes:
            self.eat_next_escapes -= 1
            return
        if self.state is oog.Screen.IN_GAME:
            self.esc_menu = not self.esc_menu
        elif self.state is oog.Screen.DIFFICULTY:
            self.state = oog.Screen.CHAR_SELECT

    def click(self, sx: int, sy: int) -> None:
        self._check_focus()
        self.log.append(f"click({sx},{sy})")
        if self.eat_next_clicks:
            self.eat_next_clicks -= 1
            return
        if self.state is oog.Screen.IN_GAME and self.esc_menu:
            # any click through this path is the save-exit click in tests
            self.esc_menu = False
            self.state = oog.Screen.MAIN_MENU
            self.current_difficulty = None

    def click_control(self, ctl: oog.MenuControl) -> tuple[int, int]:
        self._check_focus()
        self.log.append(f"click_control({ctl.text})")
        if self.eat_next_clicks:
            self.eat_next_clicks -= 1
            return ctl.center
        if self.state is oog.Screen.MAIN_MENU and ctl.matches(*oog.SINGLE_PLAYER_BUTTON):
            self.state = oog.Screen.CHAR_SELECT
        elif self.state is oog.Screen.CHAR_SELECT and ctl.matches(*oog.CHAR_SELECT_OK):
            self.state = oog.Screen.DIFFICULTY
        elif self.state is oog.Screen.DIFFICULTY:
            for fp in oog.DIFFICULTY_FINGERPRINTS.values():
                if ctl.matches(*fp):
                    self.state = oog.Screen.IN_GAME
                    self.current_difficulty = self.difficulty_entered
        return ctl.center

    # -- perception duck-types ------------------------------------------------------

    def observe(self, session) -> tuple[oog.Screen, list[oog.MenuControl]]:
        if self.state is oog.Screen.IN_GAME:
            return oog.Screen.IN_GAME, []
        return self.state, SCREEN_CONTROLS[self.state]

    def read_difficulty(self, session) -> int | None:
        return self.current_difficulty

    def is_in_game(self, session=None) -> bool:
        return self.state is oog.Screen.IN_GAME


@pytest.fixture
def rig(monkeypatch):
    """A GameCycle wired entirely to the scripted client and a fake clock."""

    def build(state: oog.Screen = oog.Screen.CHAR_SELECT, **config_kwargs):
        client = ScriptedClient(state)
        clock = FakeClock()
        monkeypatch.setattr(uistate, "is_in_game", lambda s: client.is_in_game())
        monkeypatch.setattr(
            uistate,
            "read_ui_state",
            lambda s, ui=None: uistate.UIState(
                frozenset({offsets.UI_ESCMENU_MAIN}) if client.esc_menu else frozenset()
            ),
        )
        from pd2bot.perception import world

        monkeypatch.setattr(world, "read_area", lambda s: object() if client.is_in_game() else None)
        cycle = GameCycle(
            session=None,
            menu_input=client,
            config=CycleConfig(**config_kwargs),
            observe=client.observe,
            read_difficulty=client.read_difficulty,
            clock=clock,
            sleep=clock.sleep,
        )
        return cycle, client, clock

    return build


# -- happy path ----------------------------------------------------------------


def test_full_cycle_from_char_select(rig):
    cycle, client, _ = rig()
    ran = []

    report = cycle.run_games(lambda s: ran.append(True), max_games=2)

    assert report.completed == 2
    assert ran == [True, True]
    assert client.state is oog.Screen.MAIN_MENU  # left the last game


def test_create_from_main_menu_clicks_single_player(rig):
    cycle, client, _ = rig(state=oog.Screen.MAIN_MENU)
    cycle.create_game()
    assert client.state is oog.Screen.IN_GAME
    assert "click_control(SINGLE PLAYER)" in client.log


def test_create_from_in_game_leaves_first(rig):
    cycle, client, _ = rig(state=oog.Screen.CHAR_SELECT)
    cycle.create_game()
    assert client.is_in_game()
    cycle.create_game()  # starts inside a game: must leave, then re-create
    assert client.is_in_game()
    assert client.log.count("esc") >= 1


def test_leave_game_noop_when_already_out(rig):
    cycle, client, _ = rig(state=oog.Screen.CHAR_SELECT)
    cycle.leave_game()
    assert client.log == []


# -- the difficulty guard ---------------------------------------------------------


def test_wrong_difficulty_leaves_and_halts(rig):
    cycle, client, _ = rig()
    client.difficulty_entered = offsets.DIFFICULTY_NORMAL

    report = cycle.run_games(lambda s: pytest.fail("run must never execute"), 3)

    assert len(report.outcomes) == 1
    assert "normal game instead of hell" in report.outcomes[0].error
    assert not client.is_in_game()  # it left the wrong game before halting


def test_wrong_difficulty_raises_from_create(rig):
    cycle, client, _ = rig()
    client.difficulty_entered = offsets.DIFFICULTY_NIGHTMARE
    with pytest.raises(WrongDifficulty):
        cycle.create_game()
    assert not client.is_in_game()


# -- retries and timeouts -----------------------------------------------------------


def test_eaten_click_is_retried(rig):
    cycle, client, _ = rig()
    client.eat_next_clicks = 1  # the OK click does nothing the first time
    cycle.create_game()
    assert client.is_in_game()
    assert client.log.count("click_control(OK)") == 2


def test_eaten_escape_is_retried(rig):
    cycle, client, _ = rig()
    cycle.create_game()
    client.eat_next_escapes = 1
    cycle.leave_game()
    assert client.state is oog.Screen.MAIN_MENU
    assert client.log.count("esc") >= 2


def test_retries_exhausted_raises(rig):
    cycle, client, _ = rig()
    client.eat_next_clicks = 99
    with pytest.raises(CycleError, match="still seeing"):
        cycle.create_game()


# -- unknown / error screens -----------------------------------------------------


def test_unknown_screen_stops_immediately(rig):
    cycle, client, _ = rig()
    client.observe = lambda s: (oog.Screen.UNKNOWN, [control((1, 2, 3, 4), "?")])
    cycle._observe = client.observe
    with pytest.raises(CycleError, match="unrecognized"):
        cycle.create_game()


def test_error_popup_stops_with_dump(rig):
    cycle, client, _ = rig(state=oog.Screen.ERROR_POPUP)
    with pytest.raises(CycleError, match="error popup"):
        cycle.create_game()


# -- focus policy ------------------------------------------------------------------


def test_focus_lost_refocuses_once_and_retries(rig):
    cycle, client, _ = rig()

    real_click = client.click_control
    calls = {"n": 0}

    def flaky(ctl):
        calls["n"] += 1
        if calls["n"] == 1:
            client.foreground = False
            try:
                raise InputRefused("the game window is not in the foreground")
            finally:
                # the user "clicks back in" before the retry
                client.foreground = True
        return real_click(ctl)

    client.click_control = flaky
    cycle.create_game()
    assert client.is_in_game()
    assert "refocus" in client.log


def test_focus_never_returns_raises_focuslost(rig):
    cycle, client, clock = rig(focus_wait_s=5.0)
    client.foreground = False
    with pytest.raises((FocusLost, CycleError)):
        cycle.create_game()


# -- navigation errors fail the cycle, not the loop -----------------------------------


def test_navigation_error_fails_cycle_continues_loop(rig):
    cycle, client, _ = rig()
    attempts = []

    def run(session):
        attempts.append(True)
        if len(attempts) == 1:
            raise NavigationError("stuck")

    report = cycle.run_games(run, max_games=2)

    assert len(report.outcomes) == 2
    assert report.outcomes[0].error == "navigation: stuck"
    assert report.outcomes[0].left  # still left the failed game cleanly
    assert report.outcomes[1].error is None
    assert report.completed == 1
