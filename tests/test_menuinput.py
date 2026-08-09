"""MenuInput: the complement guard. Nothing sends into the world's territory.

Mirrors test_input.py's fakes: the point under test is the refusal logic —
MenuInput must refuse exactly where GatedInput allows, and vice versa.
"""

from types import SimpleNamespace

import pytest

from pd2bot import offsets
from pd2bot.input import InputRefused
from pd2bot.menuinput import MenuInput, menu_to_screen
from pd2bot.perception import oog
from pd2bot.window import ClientRect
from tests.conftest import CLIENT_BASE, FakeMemory, FakeSession, u32

UI_ARRAY = 0x0F000000
UNIT = 0x0A000000

RECT = ClientRect(left=0, top=0, width=800, height=600)
WIDE_RECT = ClientRect(left=100, top=50, width=1600, height=1200)


class FakeWindow:
    def __init__(self, foreground: bool = True, rect: ClientRect = RECT) -> None:
        self.foreground = foreground
        self.rect = rect

    def client_rect(self) -> ClientRect:
        return self.rect

    def is_foreground(self) -> bool:
        return self.foreground


def make_session(
    in_game: bool = False, open_panels: tuple[int, ...] = ()
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
        "pd2bot.menuinput._send_mouse_flag", lambda f: record.append(("mouse", f))
    )
    monkeypatch.setattr(
        "pd2bot.menuinput._send_key", lambda vk, f: record.append(("key", vk, f))
    )
    monkeypatch.setattr("pd2bot.menuinput.time", SimpleNamespace(sleep=lambda s: None))
    monkeypatch.setattr(
        "pd2bot.menuinput.user32",
        SimpleNamespace(SetCursorPos=lambda x, y: record.append(("cursor", x, y))),
    )
    return record


def menu(session, foreground=True, rect=RECT) -> MenuInput:
    return MenuInput(
        session, window=FakeWindow(foreground, rect), ui_array=UI_ARRAY
    )


# -- the complement guard -----------------------------------------------------


def test_click_allowed_out_of_game(sent):
    menu(make_session(in_game=False)).click(400, 300)
    assert ("cursor", 400, 300) in sent
    assert ("mouse", 0x0002) in sent and ("mouse", 0x0004) in sent


def test_click_allowed_when_esc_menu_open(sent):
    """The M1 click — 'Save and Exit Game' — now allowed on purpose, here only."""
    session = make_session(in_game=True, open_panels=(offsets.UI_ESCMENU_MAIN,))
    menu(session).click(400, 300)
    assert ("mouse", 0x0002) in sent


def test_click_refused_in_game_without_esc_menu(sent):
    """The complement of GatedInput: a clean in-game state is NOT ours."""
    with pytest.raises(InputRefused, match="GatedInput's job"):
        menu(make_session(in_game=True)).click(400, 300)
    assert sent == []


def test_click_refused_when_backgrounded(sent):
    with pytest.raises(InputRefused, match="foreground"):
        menu(make_session(), foreground=False).click(400, 300)
    assert sent == []


def test_click_refused_outside_client_area(sent):
    with pytest.raises(InputRefused, match="outside"):
        menu(make_session()).click(801, 300)
    assert sent == []


def test_other_panel_open_still_refuses_in_game(sent):
    """Inventory open is a world state (GatedInput refuses it too):
    neither gate fires, which is correct — a human is mid-something."""
    session = make_session(in_game=True, open_panels=(offsets.UI_INVENTORY,))
    with pytest.raises(InputRefused):
        menu(session).click(400, 300)
    assert sent == []


# -- ESC ----------------------------------------------------------------------


def test_escape_allowed_in_game_and_out(sent):
    menu(make_session(in_game=True)).press_escape()
    menu(make_session(in_game=False)).press_escape()
    assert sent.count(("key", 0x1B, 0)) == 2


def test_escape_refused_when_backgrounded(sent):
    with pytest.raises(InputRefused, match="foreground"):
        menu(make_session(), foreground=False).press_escape()
    assert sent == []


# -- menu-space projection ----------------------------------------------------


def test_menu_projection_identity_at_800x600():
    assert menu_to_screen(RECT, 400, 300) == (400, 300)


def test_menu_projection_scales_and_offsets():
    # 2x window at (100, 50): menu (264, 383) -> (100 + 528, 50 + 766)
    assert menu_to_screen(WIDE_RECT, 264, 383) == (628, 816)


def test_menu_projection_pillarboxes_widescreen():
    """The live 1536x864 case: 4:3 menu in a 16:9 window -> height-fit 1.44x,
    192px bars. The OK button (menu center 691,555) must land at (1187, 799),
    not the naive stretch's (1327, 799) that missed by an inch."""
    rect = ClientRect(left=0, top=0, width=1536, height=864)
    assert menu_to_screen(rect, 691, 555) == (1187, 799)


def test_menu_projection_letterboxes_tall_windows():
    # Width-limited: 800x900 window -> scale 1, 150px top/bottom bars.
    rect = ClientRect(left=0, top=0, width=800, height=900)
    assert menu_to_screen(rect, 400, 300) == (400, 450)


def test_click_menu_projects_then_clicks(sent):
    pixel = menu(make_session(), rect=WIDE_RECT).click_menu(400, 300)
    assert pixel == (100 + 800, 50 + 600)
    assert ("cursor", 900, 650) in sent


def test_click_control_uses_center(sent):
    hell = oog.MenuControl(
        address=0x1000, ctype=6, state=5, x=264, y=383, width=272, height=35,
        text="HELL",
    )
    pixel = menu(make_session()).click_control(hell)
    assert pixel == hell.center  # identity rect: menu space == screen space
    assert ("cursor", *hell.center) in sent
