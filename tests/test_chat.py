"""Chat: nothing is ever typed unless the console is proven open."""

from types import SimpleNamespace

import pytest

from pd2bot import offsets
from pd2bot.chat import Chat, ChatError, _split
from pd2bot.input import InputRefused
from pd2bot.perception import uistate
from tests.conftest import CLIENT_BASE, FakeMemory, FakeSession, u32

UI_ARRAY = 0x0F000000
UNIT = 0x0A000000


class FakeWindow:
    def __init__(self, foreground: bool = True) -> None:
        self.foreground = foreground

    def is_foreground(self) -> bool:
        return self.foreground


class Rig:
    """A fake client whose chat console can be scripted to (not) open."""

    def __init__(self, in_game: bool = True, console_opens: bool = True) -> None:
        self.memory = FakeMemory()
        self.memory.write(
            CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(UNIT if in_game else 0)
        )
        self._panels = bytearray(0x26 * 4)
        self.memory.write(UI_ARRAY, bytes(self._panels))
        self.session = FakeSession(self.memory)
        self.console_opens = console_opens
        self.typed: list[str] = []
        self.keys: list[int] = []

    def set_console(self, open_: bool) -> None:
        self._panels[offsets.UI_CHAT_CONSOLE * 4] = 1 if open_ else 0
        self.memory.write(UI_ARRAY, bytes(self._panels))

    def set_panel(self, panel_id: int, open_: bool = True) -> None:
        self._panels[panel_id * 4] = 1 if open_ else 0
        self.memory.write(UI_ARRAY, bytes(self._panels))

    def send_key(self, vk: int, flags: int) -> None:
        if flags == 0:
            self.keys.append(vk)
            if vk == 0x0D and self.console_opens:
                self.set_console(not self._panels[offsets.UI_CHAT_CONSOLE * 4])

    def send_char(self, char: str) -> None:
        self.typed.append(char)


@pytest.fixture
def rig(monkeypatch):
    def build(**kwargs) -> tuple[Chat, Rig]:
        r = Rig(**kwargs)
        monkeypatch.setattr("pd2bot.chat._send_key", r.send_key)
        monkeypatch.setattr("pd2bot.chat._send_char", r.send_char)
        monkeypatch.setattr(
            "pd2bot.chat.time",
            SimpleNamespace(sleep=lambda s: None, monotonic=__import__("time").monotonic),
        )
        chat = Chat(r.session, window=FakeWindow(), ui_array=UI_ARRAY)
        return chat, r

    return build


def test_say_types_and_posts(rig):
    chat, r = rig()
    chat.say("hi")
    assert r.typed == ["h", "i"]
    assert r.keys == [0x0D, 0x0D]  # open, post
    # posting toggled the console shut again in the fake
    assert not r._panels[offsets.UI_CHAT_CONSOLE * 4]


def test_console_never_opens_means_zero_typed(rig):
    chat, r = rig(console_opens=False)
    import pd2bot.chat as chat_module

    # collapse the open-timeout for the test
    orig = chat_module._CONSOLE_OPEN_TIMEOUT_S
    chat_module._CONSOLE_OPEN_TIMEOUT_S = 0.01
    try:
        with pytest.raises(ChatError, match="did not open"):
            chat.say("hi")
    finally:
        chat_module._CONSOLE_OPEN_TIMEOUT_S = orig
    assert r.typed == []  # the hazard this module exists to prevent


def test_console_closing_mid_message_stops_instantly(rig):
    chat, r = rig()

    original = r.send_char

    def closing_send(char: str) -> None:
        original(char)
        if len(r.typed) == 2:
            r.set_console(False)  # death screen / load mid-message

    r.send_char = closing_send
    import pd2bot.chat  # re-patch with the wrapper

    pd2bot.chat._send_char = closing_send
    with pytest.raises(ChatError, match="mid-message"):
        chat.say("hello")
    assert r.typed == ["h", "e"]  # stopped at the close, not sprayed


def test_refused_out_of_game(rig):
    chat, r = rig(in_game=False)
    with pytest.raises(InputRefused, match="not in a game"):
        chat.say("hi")
    assert r.typed == []


def test_refused_when_backgrounded(rig):
    chat, r = rig()
    chat.window = FakeWindow(foreground=False)
    with pytest.raises(InputRefused, match="foreground"):
        chat.say("hi")
    assert r.typed == []


def test_refused_while_an_npc_dialog_is_open(rig):
    """R89, the user's diagnosis of three confusing live runs: the opening
    Enter is a keystroke into whatever is on screen, and an NPC dialog takes
    it as CHOOSING AN OPTION. The console then never opens, so the caller
    retries — clicking through the dialog once a second. Not one key may be
    sent while a panel is up."""
    chat, r = rig()
    r.set_panel(offsets.UI_NPCMENU)
    with pytest.raises(InputRefused, match="npc_menu"):
        chat.say("hi")
    assert r.typed == [] and r.keys == []  # the Enter itself never happened


def test_refused_for_every_blocking_panel(rig):
    """Whatever swallows a world click can swallow an Enter — so the list is
    the same list, read from uistate rather than copied here."""
    for panel_id in uistate.blocking_panels():
        if panel_id == offsets.UI_CHAT_CONSOLE:
            continue  # that one IS the chat, and means we may type
        chat, r = rig()
        r.set_panel(panel_id)
        with pytest.raises(InputRefused):
            chat.say("hi")
        assert r.keys == []


def test_the_console_being_open_is_not_treated_as_a_blocking_panel(rig):
    """The chat console blocks world input, but it is precisely the state
    chat needs — refusing on it would make the module unable to ever type."""
    chat, r = rig()
    r.set_console(True)
    chat.say("hi")
    assert r.typed == ["h", "i"]


def test_split_respects_word_boundaries():
    text = "word " * 40  # 200 chars
    chunks = _split(text.strip())
    assert all(len(c) <= 100 for c in chunks)
    assert " ".join(chunks) == text.strip()


def test_split_short_text_is_one_chunk():
    assert _split("hello") == ["hello"]
