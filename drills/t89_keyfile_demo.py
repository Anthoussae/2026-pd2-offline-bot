"""T89 — DEMONSTRATION: the bot reads the character's REAL hotkeys (R247).

Three acts, each printed as it happens:

1. Discover and parse the live character's `.key` file; print the
   detected bindings as a table (function -> key, named the way the
   game's Configure Controls screen names them).
2. Verify the class config's `[hotkeys]` against the client's layout —
   the drift check every real launch now performs.
3. In a game, effect-verify every configured skill hotkey by actually
   switching to it and reading the right-skill slot back (the R47.1
   manual capture, now automated end-to-end from the client's own
   config file).

    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t89_keyfile_demo

Town only; skill switches and chat are the only input. The game is left
in a `finally`.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot.input import keys  # noqa: E402
from pd2bot.input.chat import Chat  # noqa: E402
from pd2bot.input.keyfile import (  # noqa: E402
    BELT,
    INVENTORY,
    SHOW_ITEMS,
    SKILL_HOTKEYS,
    read_keyfile,
)
from pd2bot.input.skills import ensure_right_skill  # noqa: E402
from pd2bot.wiring import build_bot  # noqa: E402


def main() -> int:
    bot = build_bot()
    session = bot.session

    # -- act 1: detect ---------------------------------------------------------
    path = keys.discover_keyfile(getattr(session, "process_id", None))
    if path is None:
        print("no .key file discoverable — nothing to demonstrate")
        return 1
    print(f"keyfile: {path}")
    table = read_keyfile(path)
    bindings = keys.load_bindings(path)

    def show(index: int, label: str) -> None:
        b = table[index]
        print(
            f"  {label:22s} {keys.key_name(b.primary):>8s}"
            + (f" / {keys.key_name(b.secondary)}" if b.secondary is not None else "")
        )

    print("--- detected bindings ---")
    show(INVENTORY, "inventory")
    for slot, index in enumerate(SKILL_HOTKEYS, start=1):
        if table[index].any_key is not None:
            show(index, f"skill hotkey {slot}")
    for column, index in enumerate(BELT, start=1):
        show(index, f"belt {column}")
    show(SHOW_ITEMS, "show items (labels)")

    # -- act 2: verify the class config against the client ---------------------
    skill_names = {
        skill_id: name for name, skill_id in bot.class_config.skills.items()
    }
    keys.verify_skill_hotkeys(bot.class_config.hotkeys, bindings, skill_names)
    print("--- config check ---")
    for skill_id, vk in sorted(bot.class_config.hotkeys.items()):
        print(
            f"  {skill_names.get(skill_id, skill_id):22s} on "
            f"{keys.key_name(vk):>8s} -> skill-hotkey slot "
            f"{bindings.skill_slot_for(vk)} in the keyfile: OK"
        )

    # -- act 3: effect-verify in a game ----------------------------------------
    cycle = bot.cycle()
    created = False
    verified = 0
    try:
        print("creating a game...", flush=True)
        cycle.create_game()
        created = True
        chat = Chat(session)
        chat.say(
            "T89 keyfile demo: switching through every configured skill "
            "hotkey, each switch memory-verified"
        )
        for skill_id, vk in sorted(bot.class_config.hotkeys.items()):
            ensure_right_skill(
                session, bot.gated, skill_id, hotkeys=bot.class_config.hotkeys
            )
            verified += 1
            print(
                f"  pressed {keys.key_name(vk)} -> right skill reads "
                f"{skill_names.get(skill_id, skill_id)}: VERIFIED"
            )
        chat.say(f"T89 done: {verified} hotkeys verified — back to the terminal")
        print(f"\nVERDICT: {verified}/{len(bot.class_config.hotkeys)} configured "
              "hotkeys switch the right skill exactly as the keyfile says")
    except Exception as exc:  # noqa: BLE001 - a drill reports, never explodes
        print(f"\nDRILL FAILED: {type(exc).__name__}: {exc}")
        return 1
    finally:
        if created:
            try:
                print("leaving the game...", flush=True)
                cycle.leave_game()
                print("left cleanly")
            except Exception as exc:  # noqa: BLE001
                print(f"leave failed ({exc}) — a human should look")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
