"""The input gate: nothing sends unless can_act AND foreground.

These tests fake the session, window, and the Win32 send primitives; what
they exercise is the gate's refusal logic and the world->pixel plumbing —
the parts whose failure caused the M1 "Save and Exit Game" incident.
"""

from types import SimpleNamespace

import pytest

from pd2bot import offsets
from pd2bot.input import screen
from pd2bot.input.gated import GatedInput, InputRefused
from pd2bot.input.window import ClientRect
from tests.conftest import CLIENT_BASE, FakeMemory, FakeSession, u16, u32

UI_ARRAY = 0x0F000000
UNIT = 0x0A000000
PATH = 0x0B000000

RECT = ClientRect(left=0, top=0, width=800, height=600)


class FakeWindow:
    def __init__(self, foreground: bool = True) -> None:
        self.foreground = foreground

    def client_rect(self) -> ClientRect:
        return RECT

    def is_foreground(self) -> bool:
        return self.foreground

    def bring_to_foreground(self) -> bool:
        return self.foreground


def make_session(
    in_game: bool = True,
    open_panels: tuple[int, ...] = (),
    player_pos: tuple[int, int] = (5000, 5000),
) -> FakeSession:
    memory = FakeMemory()
    memory.write(
        CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(UNIT if in_game else 0)
    )
    panels = bytearray(0x26 * 4)
    for panel in open_panels:
        panels[panel * 4 : panel * 4 + 4] = u32(1)
    memory.write(UI_ARRAY, bytes(panels))
    memory.write_fields(UNIT, {offsets.UNIT_PATH: u32(PATH)})
    memory.write_fields(
        PATH,
        {offsets.PATH_X: u16(player_pos[0]), offsets.PATH_Y: u16(player_pos[1])},
    )
    return FakeSession(memory)


@pytest.fixture
def sent(monkeypatch):
    """Capture every OS-level send; neutralize sleeps and the cursor move."""
    record = []
    monkeypatch.setattr(
        "pd2bot.input.gated._send_mouse_flag", lambda f: record.append(("mouse", f))
    )
    monkeypatch.setattr("pd2bot.input.gated._send_key", lambda vk, f: record.append(("key", vk, f)))
    monkeypatch.setattr("pd2bot.input.gated.time", SimpleNamespace(sleep=lambda s: None))
    # The cursor move is a real SendInput event since T60; tests record it
    # under the same ("cursor", x, y) shape the SetCursorPos era used.
    monkeypatch.setattr(
        "pd2bot.input.gated._send_mouse_move", lambda x, y: record.append(("cursor", x, y))
    )
    monkeypatch.setattr(
        "pd2bot.input.gated.user32",
        SimpleNamespace(SetCursorPos=lambda x, y: record.append(("cursor", x, y))),
    )
    return record


def gated(session, foreground=True) -> GatedInput:
    return GatedInput(session, window=FakeWindow(foreground), ui_array=UI_ARRAY)


def test_click_allowed_in_clean_state(sent):
    gated(make_session()).click_screen(400, 300)
    assert ("cursor", 400, 300) in sent
    assert ("mouse", 0x0002) in sent and ("mouse", 0x0004) in sent


def test_esc_menu_refuses_click(sent):
    """The M1 incident, at the gate: ESC menu open -> no input, ever."""
    with pytest.raises(InputRefused, match="panel"):
        gated(make_session(open_panels=(offsets.UI_ESCMENU_MAIN,))).click_screen(400, 300)
    assert sent == []


def test_not_in_game_refuses(sent):
    with pytest.raises(InputRefused, match="not in a game"):
        gated(make_session(in_game=False)).click_screen(400, 300)
    assert sent == []


def test_background_window_refuses(sent):
    with pytest.raises(InputRefused, match="foreground"):
        gated(make_session(), foreground=False).click_screen(400, 300)
    assert sent == []


def test_hud_strip_refuses(sent):
    # y=520 is inside the 120px HUD band of a 600px-tall window.
    with pytest.raises(InputRefused, match="HUD|safe click"):
        gated(make_session()).click_screen(400, 520)
    assert sent == []


def test_key_press_is_gated_too(sent):
    with pytest.raises(InputRefused):
        gated(make_session(), foreground=False).press_key(0x31)
    assert sent == []
    gated(make_session()).press_key(0x31)
    assert ("key", 0x31, 0) in sent


def test_click_world_projects_from_live_player_position(sent):
    # Player at (5000, 5000), target 10 subtiles +x, from the client-area
    # centre (400, 300). Derived from the calibrated constants rather than
    # repeating them, so a re-calibration does not fail this test.
    expected = (
        400 + 10 * screen.PX_PER_SUBTILE_X,
        300 + 10 * screen.PX_PER_SUBTILE_Y,
    )
    pixel = gated(make_session()).click_world(5010, 5000)
    assert pixel == expected
    assert ("cursor", *expected) in sent


def test_automap_does_not_block(sent):
    """The automap overlays the world but the world stays clickable."""
    gated(make_session(open_panels=(offsets.UI_AUTOMAP,))).click_screen(400, 300)
    assert ("mouse", 0x0002) in sent


def test_stand_still_wraps_the_click_in_shift(sent):
    """The attack-in-place modifier: shift down before the mouse, up after."""
    gated(make_session()).click_screen(400, 300, stand_still=True)
    assert sent.index(("key", 0x10, 0)) < sent.index(("mouse", 0x0002))
    assert sent.index(("mouse", 0x0004)) < sent.index(("key", 0x10, 0x0002))


def test_stand_still_shift_released_when_the_click_fails(sent, monkeypatch):
    """A stuck shift would corrupt all later input; release must survive
    a mid-click failure."""

    def explode(flag):
        sent.append(("mouse", flag))
        raise OSError("SendInput failed")

    monkeypatch.setattr("pd2bot.input.gated._send_mouse_flag", explode)
    with pytest.raises(OSError):
        gated(make_session()).click_screen(400, 300, stand_still=True)
    assert ("key", 0x10, 0x0002) in sent


def test_stand_still_click_world_passes_the_modifier_through(sent):
    gated(make_session()).click_world(5010, 5000, stand_still=True)
    assert ("key", 0x10, 0) in sent and ("key", 0x10, 0x0002) in sent


def test_refused_stand_still_click_sends_no_shift(sent):
    """A refusal before the click must not leave any key event behind."""
    with pytest.raises(InputRefused):
        gated(make_session(in_game=False)).click_screen(400, 300, stand_still=True)
    assert sent == []


def test_shift_chord_holds_the_modifier_around_the_key(sent):
    """The merc-feed chord (R179, corrected to Shift at R183): Shift
    provably down before the belt key, provably still down when the key
    releases — the R113 same-frame race, applied to a keyboard chord."""
    gated(make_session()).press_key_with_shift(0x33)
    assert sent.index(("key", 0x10, 0)) < sent.index(("key", 0x33, 0))
    assert sent.index(("key", 0x33, 0x0002)) < sent.index(("key", 0x10, 0x0002))


def test_shift_chord_is_gated(sent):
    with pytest.raises(InputRefused):
        gated(make_session(), foreground=False).press_key_with_shift(0x33)
    assert sent == []


def test_shift_released_when_the_key_send_fails(sent, monkeypatch):
    """A stuck Shift would silently reinterpret every later click and
    belt key; the release must survive a mid-chord failure."""

    def explode(vk, flags):
        sent.append(("key", vk, flags))
        if vk == 0x33 and flags == 0:
            raise OSError("SendInput failed")

    monkeypatch.setattr("pd2bot.input.gated._send_key", explode)
    with pytest.raises(OSError):
        gated(make_session()).press_key_with_shift(0x33)
    assert ("key", 0x10, 0x0002) in sent


# -- the watchdog latch: world input stops, the exit stays open ----------------
#
# The chicken watchdog (pd2bot/watchdog.py) is a separate process that
# presses ESC when vitals cross. Once it has, the bot must stop clicking
# at the world -- but it must STILL be able to complete the clean
# Save-and-Exit, which goes through MenuInput, not here. That asymmetry
# is the design.


def test_a_fresh_watchdog_latch_refuses_world_input(tmp_path):
    from pd2bot.safety.watchdog import write_latch

    latch = tmp_path / "watchdog-latch"
    write_latch("life", latch, pct=28.0)
    guarded = GatedInput(
        make_session(), window=FakeWindow(), ui_array=UI_ARRAY, latch_path=latch
    )
    with pytest.raises(InputRefused, match="watchdog"):
        guarded.check()


def test_a_stale_latch_does_not_disarm_the_bot_for_ever(tmp_path):
    """A sticky file that nobody clears is an outage of its own -- the
    lesson the drill cancel file already taught this project."""
    import time as _time

    from pd2bot.safety.watchdog import LATCH_STALE_AFTER_S, write_latch

    latch = tmp_path / "watchdog-latch"
    write_latch("life", latch, now=_time.time() - LATCH_STALE_AFTER_S - 60)
    guarded = GatedInput(
        make_session(), window=FakeWindow(), ui_array=UI_ARRAY, latch_path=latch
    )
    guarded.check()  # no raise


def test_no_latch_is_business_as_usual(tmp_path):
    guarded = GatedInput(
        make_session(), window=FakeWindow(), ui_array=UI_ARRAY,
        latch_path=tmp_path / "nothing-here",
    )
    guarded.check()


def test_the_latch_check_is_cached_rather_than_stat_per_click(tmp_path):
    """`check()` runs on every send; a syscall per click buys nothing at
    this timescale."""
    latch = tmp_path / "watchdog-latch"
    guarded = GatedInput(
        make_session(), window=FakeWindow(), ui_array=UI_ARRAY, latch_path=latch
    )
    guarded.check()  # primes the cache: no latch

    from pd2bot.safety.watchdog import write_latch

    write_latch("life", latch)
    guarded.check()  # still cached, so still allowed -- documented behaviour
    guarded._latch_checked_at = None  # expire it by hand
    with pytest.raises(InputRefused, match="watchdog"):
        guarded.check()


def test_menu_input_ignores_the_latch(tmp_path):
    """The asymmetry, pinned: the latch must not block `leave_game`, or
    a watchdog pause would leave the bot unable to finish the exit that
    should follow it."""
    from pd2bot.input.menu import MenuInput
    from pd2bot.safety.watchdog import write_latch

    write_latch("life", tmp_path / "watchdog-latch")
    menu = MenuInput(
        make_session(in_game=True, open_panels=(offsets.UI_ESCMENU_MAIN,)),
        window=FakeWindow(),
        ui_array=UI_ARRAY,
    )
    menu.check()  # no raise: the exit stays available
