"""Saying things in the game's chat: the bot's channel to a watching human.

User-requested mid-M4 (instruction log R41 detour): during live tests the
human is looking at the game, not at the console — so test instructions
("cast a spell now") should appear *in the game*, via the chat line that
Enter opens and Enter posts.

The hazard this module is built around: if the opening Enter does not
actually open the chat box, every "typed" character lands on the game as a
hotkey — h swaps weapons, numbers drink potions, and so on. So nothing is
typed until the chat console is *verified open* in the UI array (the same
array uistate reads for the input gates; the chat console is panel 0x05),
and if it never opens, the result is a refusal with zero keys sent, not a
prayer.

That premise had a hole for three milestones (R89): it protected the
*typing* but treated the opening Enter as harmless. Enter is not harmless.
With an NPC dialog open it chooses a dialog option, so a message sent
during a dialog silently clicked through menus — and because the console
then never opened, the caller's retry loop did it again every second. The
guard now refuses while any blocking panel is up.

Guard shape (the third narrowly-scoped send path, same philosophy as
GatedInput and MenuInput): in a game AND foreground AND no panel that could
swallow the Enter; every character is then sent only while the chat console
remains open and the window remains foreground. No bypass, no unguarded
variant.

    python -m pd2bot.input.chat "message here"
"""

from __future__ import annotations

import time

from pd2bot import offsets
from pd2bot.input.gated import InputRefused, _send_char, _send_key
from pd2bot.input.keys import VK_RETURN  # the one registry (R247)
from pd2bot.input.window import GameWindow
from pd2bot.perception import uistate
from pd2bot.perception.memory import GameSession

_KEY_UP = 0x0002

_KEY_TAP_S = 0.04
_CHAR_DELAY_S = 0.02
_CONSOLE_OPEN_TIMEOUT_S = 2.0
# D2's chat line tops out around 130ish characters; stay comfortably under
# and split long messages instead of truncating silently.
MAX_CHARS_PER_MESSAGE = 100


class ChatError(RuntimeError):
    """The chat console did not behave; nothing (further) was typed."""


def _tap(vk: int) -> None:
    _send_key(vk, 0)
    time.sleep(_KEY_TAP_S)
    _send_key(vk, _KEY_UP)


class Chat:
    """Types messages into the in-game chat, console-verified at every step."""

    def __init__(
        self,
        session: GameSession,
        window: GameWindow | None = None,
        ui_array: int | None = None,
        allow_panels: frozenset[int] = frozenset(),
    ) -> None:
        self.session = session
        self.window = window if window is not None else GameWindow(session.process_id)
        self._ui_array = (
            ui_array if ui_array is not None else uistate.find_ui_array(session)
        )
        # Operator-licensed exceptions to the blocking-panel refusal
        # (R243, 2026-08-10): the SHOP screen has no Enter-activated
        # default control, so Enter opens the console normally there —
        # unlike the dialog LIST, where Enter selects a row (the M1
        # shape this guard exists for). The verify-by-effect check
        # below (`_console_open` before any typing) remains the real
        # gate: a wrong allowance costs one inert Enter, never typed
        # text landing on the game.
        self._allow_panels = allow_panels

    def _console_open(self) -> bool:
        return uistate.read_ui_state(self.session, self._ui_array).is_open(
            offsets.UI_CHAT_CONSOLE
        )

    def _check(self) -> None:
        if not uistate.is_in_game(self.session):
            raise InputRefused("not in a game — there is no chat to type into")
        if not self.window.is_foreground():
            raise InputRefused(
                "the game window is not in the foreground — keystrokes would "
                "go to another application"
            )
        # The opening Enter is itself a keystroke into whatever is on screen,
        # and this module's whole premise was that only the *typing* could
        # be misread as hotkeys. It was wrong (user diagnosis, R89): with an
        # NPC dialog open, Enter does not open the console — it SELECTS the
        # highlighted dialog option. The console then never opens, `say`
        # raises, and the drill harness retries once a second for a minute,
        # picking a dialog option every time. That is the M1 "Save and Exit"
        # shape exactly: a keystroke whose meaning changes with state, sent
        # without checking the state.
        state = uistate.read_ui_state(self.session, self._ui_array)
        blocking = [
            p
            for p in uistate.blocking_panels()
            if p != offsets.UI_CHAT_CONSOLE
            and p not in self._allow_panels
            and state.is_open(p)
        ]
        if blocking:
            names = ", ".join(
                offsets.UI_NAMES.get(p, f"ui_{p:#x}") for p in blocking
            )
            raise InputRefused(
                f"a panel is open ({names}) — Enter would act on it instead "
                "of opening the chat console (an NPC dialog would take it as "
                "choosing an option), so nothing is typed"
            )

    def say(self, text: str) -> None:
        """Post `text` to the in-game chat. Splits long messages."""
        for chunk in _split(text):
            self._say_one(chunk)
            time.sleep(0.15)

    def _say_one(self, text: str) -> None:
        self._check()

        # Open the chat line, then PROVE it is open before typing anything —
        # an unopened console turns text into hotkey presses.
        if not self._console_open():
            _tap(VK_RETURN)
            deadline = time.monotonic() + _CONSOLE_OPEN_TIMEOUT_S
            while not self._console_open():
                if time.monotonic() >= deadline:
                    raise ChatError(
                        "the chat console did not open — nothing was typed"
                    )
                time.sleep(0.05)

        for char in text:
            # Re-verify per character: if the console vanished mid-message
            # (death screen, load), stop instantly rather than spray hotkeys.
            if not self._console_open():
                raise ChatError(
                    f"the chat console closed mid-message after typing part "
                    f"of {text!r} — stopped immediately"
                )
            if not self.window.is_foreground():
                raise InputRefused("focus lost mid-message — stopped")
            _send_char(char)
            time.sleep(_CHAR_DELAY_S)

        _tap(VK_RETURN)  # post


def _split(text: str) -> list[str]:
    if len(text) <= MAX_CHARS_PER_MESSAGE:
        return [text]
    words = text.split(" ")
    chunks: list[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if len(candidate) > MAX_CHARS_PER_MESSAGE and current:
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def main(argv: list[str] | None = None) -> int:
    import argparse

    from pd2bot.perception.memory import GameNotRunning, NeedsAdministrator

    parser = argparse.ArgumentParser(description="Post a message to the in-game chat.")
    parser.add_argument("message", help="text to say in game")
    args = parser.parse_args(argv)

    try:
        session = GameSession()
    except (GameNotRunning, NeedsAdministrator) as exc:
        print(exc)
        return 1

    try:
        Chat(session).say(args.message)
    except (InputRefused, ChatError) as exc:
        print(f"refused: {exc}")
        return 1
    print("said it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
