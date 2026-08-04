"""PanelInput: the third gate. A click happens only inside the panel the
caller named, verified open at the moment of sending.

Mirrors test_menuinput.py's fakes; the point under test is the guard truth
table — PanelInput must refuse everywhere the other two gates *allow*, and
allow only the one situation neither of them covers.

The waypoint slot (0x14) was re-calibrated by P2's live drill: it is a real
display flag (M2's always-on note was a misobservation), reported by
`read_ui_state` and blocking like the stash.
"""

from types import SimpleNamespace

import pytest

from pd2bot import offsets
from pd2bot.input import InputRefused
from pd2bot.panelinput import PanelInput
from pd2bot.window import ClientRect
from tests.conftest import CLIENT_BASE, FakeMemory, FakeSession, u32

UI_ARRAY = 0x0F000000
UNIT = 0x0A000000

RECT = ClientRect(left=0, top=0, width=1536, height=864)


class FakeWindow:
    def __init__(self, foreground: bool = True, rect: ClientRect = RECT) -> None:
        self.foreground = foreground
        self.rect = rect

    def client_rect(self) -> ClientRect:
        return self.rect

    def is_foreground(self) -> bool:
        return self.foreground


def make_session(
    in_game: bool = True, open_panels: tuple[int, ...] = ()
) -> FakeSession:
    memory = FakeMemory()
    memory.write(CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(UNIT if in_game else 0))
    panels = bytearray(0x26 * 4)
    for panel in open_panels:
        panels[panel * 4 : panel * 4 + 4] = u32(1)
    memory.write(UI_ARRAY, bytes(panels))
    return FakeSession(memory)


@pytest.fixture
def sent(monkeypatch):
    record = []
    monkeypatch.setattr(
        "pd2bot.panelinput._send_mouse_flag", lambda f: record.append(("mouse", f))
    )
    monkeypatch.setattr(
        "pd2bot.panelinput._send_key", lambda vk, f: record.append(("key", vk, f))
    )
    monkeypatch.setattr(
        "pd2bot.panelinput.time",
        SimpleNamespace(sleep=lambda s: record.append(("sleep", s))),
    )
    monkeypatch.setattr(
        "pd2bot.panelinput.user32",
        SimpleNamespace(SetCursorPos=lambda x, y: record.append(("cursor", x, y))),
    )
    return record


def panel(session, foreground=True, rect=RECT) -> PanelInput:
    return PanelInput(session, window=FakeWindow(foreground, rect), ui_array=UI_ARRAY)


# -- the guard truth table ----------------------------------------------------


def test_click_allowed_when_the_named_panel_is_open(sent):
    session = make_session(open_panels=(offsets.UI_NPCMENU,))
    panel(session).click(offsets.UI_NPCMENU, 400, 300)
    assert ("cursor", 400, 300) in sent
    assert ("mouse", 0x0002) in sent and ("mouse", 0x0004) in sent


def test_shift_settles_a_frame_clear_of_the_click_on_both_sides(sent):
    """R113: shift and click sent in the same frame is a race the game can
    resolve as an UNMODIFIED click — which used a Tome of Identify instead
    of stashing it. Shift must be provably down a frame before the press
    and provably still down a frame after the release."""
    from pd2bot.input import _MODIFIER_SETTLE_S, VK_SHIFT

    session = make_session(open_panels=(offsets.UI_STASH,))
    panel(session).click(offsets.UI_STASH, 400, 300, button="right", shift=True)

    def index(event):
        return sent.index(event)

    shift_down = index(("key", VK_SHIFT, 0))
    mouse_down = index(("mouse", 0x0008))
    mouse_up = index(("mouse", 0x0010))
    shift_up = index(("key", VK_SHIFT, 0x0002))
    assert shift_down < mouse_down < mouse_up < shift_up
    # A settle sleep sits between shift-down and the press, and between the
    # release and shift-up — the two sides of the race.
    assert ("sleep", _MODIFIER_SETTLE_S) in sent[shift_down:mouse_down]
    assert ("sleep", _MODIFIER_SETTLE_S) in sent[mouse_up:shift_up]


def test_key_allowed_when_the_named_panel_is_open(sent):
    """R104: NPC dialogs are keyboard-navigable, and neither other gate may
    send those keys — GatedInput refuses with a blocking panel open, and
    MenuInput refuses in a game without the ESC menu."""
    from pd2bot.input import VK_RETURN

    session = make_session(open_panels=(offsets.UI_NPCMENU,))
    panel(session).press_key(offsets.UI_NPCMENU, VK_RETURN)
    assert ("key", VK_RETURN, 0) in sent  # pressed
    assert ("key", VK_RETURN, 0x0002) in sent  # and released


def test_key_refused_when_the_named_panel_is_not_open(sent):
    """The key this exists to send is Enter, and an Enter that misses its
    panel is exactly the R89 defect — it chooses something elsewhere."""
    from pd2bot.input import VK_RETURN

    session = make_session(open_panels=(offsets.UI_INVENTORY,))
    with pytest.raises(InputRefused, match="npc_menu panel is not open"):
        panel(session).press_key(offsets.UI_NPCMENU, VK_RETURN)
    assert sent == []


def test_key_refused_without_foreground(sent):
    from pd2bot.input import VK_DOWN

    session = make_session(open_panels=(offsets.UI_NPCMENU,))
    with pytest.raises(InputRefused, match="foreground"):
        panel(session, foreground=False).press_key(offsets.UI_NPCMENU, VK_DOWN)
    assert sent == []


def test_refused_out_of_a_game(sent):
    with pytest.raises(InputRefused, match="MenuInput's job"):
        panel(make_session(in_game=False)).click(offsets.UI_NPCMENU, 400, 300)
    assert sent == []


def test_refused_when_the_named_panel_is_not_open(sent):
    """The caller's belief is stale — the click would land on the world or
    on some other panel. The refusal names both sides."""
    session = make_session(open_panels=(offsets.UI_INVENTORY,))
    with pytest.raises(InputRefused, match="npc_menu panel is not open"):
        panel(session).click(offsets.UI_NPCMENU, 400, 300)
    assert sent == []


def test_refused_when_a_different_belief_would_be_true(sent):
    """Naming the wrong panel refuses even though *a* panel is open — the
    guard verifies the caller's specific belief, not 'something is open'."""
    session = make_session(open_panels=(offsets.UI_NPCMENU,))
    with pytest.raises(InputRefused, match="inventory panel is not open"):
        panel(session).click(offsets.UI_INVENTORY, 400, 300)


def test_refused_without_foreground(sent):
    session = make_session(open_panels=(offsets.UI_NPCMENU,))
    with pytest.raises(InputRefused, match="foreground"):
        panel(session, foreground=False).click(offsets.UI_NPCMENU, 400, 300)
    assert sent == []


def test_refused_outside_the_client_area(sent):
    session = make_session(open_panels=(offsets.UI_NPCMENU,))
    with pytest.raises(InputRefused, match="outside the game's client area"):
        panel(session).click(offsets.UI_NPCMENU, 5000, 300)
    assert sent == []


def test_right_button_and_shift_wrap_the_click(sent):
    """Shift goes down before the mouse and up after — the stash transfer
    gesture (shift+right-click, R47.8)."""
    session = make_session(open_panels=(offsets.UI_STASH,))
    panel(session).click(offsets.UI_STASH, 400, 300, button="right", shift=True)
    assert sent.index(("key", 0x10, 0)) < sent.index(("mouse", 0x0008))
    assert sent.index(("mouse", 0x0010)) < sent.index(("key", 0x10, 0x0002))


def test_shift_is_released_even_when_the_click_fails(sent, monkeypatch):
    """A stuck shift would corrupt every later keystroke; the release must
    survive a mid-click failure."""
    session = make_session(open_panels=(offsets.UI_STASH,))

    def explode(flag):
        sent.append(("mouse", flag))
        raise OSError("SendInput failed")

    monkeypatch.setattr("pd2bot.panelinput._send_mouse_flag", explode)
    with pytest.raises(OSError):
        panel(session).click(offsets.UI_STASH, 400, 300, shift=True)
    assert ("key", 0x10, 0x0002) in sent  # shift up happened anyway
