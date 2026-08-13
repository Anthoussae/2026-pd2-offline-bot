"""THE keybinding registry: every key the bot knows, in one place (R247).

Three tiers, formerly scattered across five modules:

1. **VK codes** — the Win32 constants themselves. Moved here from
   gated.py (which keeps re-exports, so no import breaks) and deduped
   out of chat.py / menu.py / window.py, each of which had grown its
   own copy of ESC or ALT.
2. **Fixed UI keys** — ESC, Enter, the arrows. D2 does not let the
   player rebind menu navigation, dialogs or chat; these are constants
   of the CLIENT, not bindings, and no keyfile consultation applies.
3. **`KeyBindings`** — the character's ACTUAL bindings, read from the
   client's own per-character `.key` file (keyfile.py) instead of
   assumed. `default_bindings()` is the honest fallback for sims,
   tests and machines without a client, and it matches the constants
   the bot hardcoded for its whole prior life — so "no keyfile" means
   "exactly the old behavior", never something new.

The provenance comments on the codes are load-bearing history — they
record live tests (T44's ctrl-drop, T63's label toggle) that future
sessions would otherwise re-run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pd2bot.input import keyfile
from pd2bot.input.keyfile import Binding, KeyfileError

# -- tier 1: the VK codes ------------------------------------------------------

VK_SHIFT = 0x10
# Ctrl+right-click drops an inventory item (R117). VK_CONTROL is the one
# the client honours — verified live in T44, first variant, gem dropped
# and found on the ground.
#
# VK_LCONTROL exists only as a documented alternative, and the story is
# worth keeping: T43 concluded ctrl was being ignored, because the item
# it dropped could not be found on the floor. That was wrong. The drop
# had worked; T43 read the ground ONCE, immediately, and a just-dropped
# item takes a moment to enter the unit table. The antidote it "lost" was
# later found lying exactly where it fell.
#
# So the bug was in the instrument, not the game — the same shape as the
# whole P3 calibration crisis (R86). A verification that polls would have
# passed first time, and the speculative per-side keycode below was never
# needed. Keep it for the day some other client really does read key
# state per-side; do not reach for it before a poll-based test says so.
VK_CONTROL = 0x11
VK_LCONTROL = 0xA2
VK_F1, VK_F2, VK_F3, VK_F4, VK_F5, VK_F6 = 0x70, 0x71, 0x72, 0x73, 0x74, 0x75
VK_F7, VK_F8 = 0x76, 0x77
VK_1, VK_2, VK_3, VK_4 = 0x31, 0x32, 0x33, 0x34
VK_I = 0x49  # the inventory toggle's DEFAULT binding (see KeyBindings)
# ALT — in PD2 a TOGGLE of the ground-item label display (user, 2026-08-03),
# not vanilla's hold-to-show. Labels are the big click targets for pickup;
# the toggle protocol is labels ON to pick, OFF to travel (T63). ALT is
# also the inert keystroke window.py uses to satisfy Windows' foreground
# rules — that use is OS plumbing, not a game binding, and never remaps.
VK_MENU = 0x12

# -- tier 2: fixed UI keys (not bindable in D2; constants of the client) -------

# NPC dialogs are keyboard-navigable: arrows move the highlight, Enter
# selects (user discovery, R104). Sent through PanelInput, never world-
# gated — a world-gated Enter is meaningless, and an ungated one chooses
# dialog options by accident, which is the R89 defect.
VK_UP, VK_DOWN, VK_RETURN = 0x26, 0x28, 0x0D
VK_ESCAPE = 0x1B

# -- tier 3: the character's actual bindings -----------------------------------

# Skill-hotkey slots the client exposes (keyfile entries 14..21).
SKILL_SLOTS = 8


@dataclass(frozen=True)
class KeyBindings:
    """The character's resolved bindings — what a press should actually
    send. `source` says where they came from; `notes` carries anything
    the operator should hear once at build time (fallbacks, oddities).
    """

    skill_keys: tuple[int | None, ...]  # slots 1..8; None = unbound
    belt: tuple[int, int, int, int]  # columns 0..3
    inventory: int
    show_items: int
    source: str
    notes: tuple[str, ...] = field(default=())

    def skill_slot_for(self, vk: int) -> int | None:
        """Which hotkey slot (1-based) a key drives, or None."""
        for slot, key in enumerate(self.skill_keys, start=1):
            if key == vk:
                return slot
        return None


def default_bindings() -> KeyBindings:
    """The bot's historical assumptions, verbatim — the no-keyfile path.

    Skills F1..F8 (the client's own default layout; the class config has
    only ever used the first six), belt 1..4, inventory I, labels ALT.
    """
    return KeyBindings(
        skill_keys=(VK_F1, VK_F2, VK_F3, VK_F4, VK_F5, VK_F6, VK_F7, VK_F8),
        belt=(VK_1, VK_2, VK_3, VK_4),
        inventory=VK_I,
        show_items=VK_MENU,
        source="defaults",
    )


def load_bindings(path: str | Path) -> KeyBindings:
    """The character's real bindings from their `.key` file.

    Raises `KeyfileError` — loudly, at build time — when a function the
    bot cannot run without is unbound: a missing binding discovered at
    press time would fail somewhere deep in a run with the character
    standing in Hell. Show Items alone gets a fallback-with-note (ALT)
    because its keyfile entry sits in the PD2-divergent region of the
    function list (see keyfile.SHOW_ITEMS) and a wrong refusal there
    would ground the bot over a label toggle.
    """
    path = Path(path)
    table = keyfile.read_keyfile(path)
    notes: list[str] = []

    def resolved(index: int) -> Binding:
        return table.get(index, Binding(index=index, primary=None, secondary=None))

    missing: list[str] = []
    inventory = resolved(keyfile.INVENTORY).any_key
    if inventory is None:
        missing.append("inventory")
    belt = tuple(resolved(i).any_key for i in keyfile.BELT)
    for column, key in enumerate(belt):
        if key is None:
            missing.append(f"belt {column + 1}")
    skill_keys = tuple(resolved(i).any_key for i in keyfile.SKILL_HOTKEYS)
    if not any(k is not None for k in skill_keys):
        missing.append("at least one skill hotkey")
    if missing:
        raise KeyfileError(
            f"{path} leaves required function(s) unbound: "
            f"{', '.join(missing)} — bind them in the game's options "
            "(Esc -> Options -> Configure Controls) and try again"
        )

    show_items = resolved(keyfile.SHOW_ITEMS).any_key
    if show_items is None:
        show_items = VK_MENU
        notes.append(
            "Show Items reads unbound in the keyfile — using ALT (the "
            "PD2 default); if ground labels stop toggling, check the "
            "game's Configure Controls screen"
        )

    return KeyBindings(
        skill_keys=skill_keys,
        belt=belt,  # type: ignore[arg-type]  # lengths checked above
        inventory=inventory,
        show_items=show_items,
        source=f"keyfile:{path}",
        notes=tuple(notes),
    )


def key_name(vk: int | None) -> str:
    """A human-readable name for a VK, for messages and the T89 table."""
    if vk is None:
        return "unbound"
    names = {
        VK_SHIFT: "Shift", VK_CONTROL: "Ctrl", VK_MENU: "Alt",
        VK_RETURN: "Enter", VK_ESCAPE: "Esc", VK_UP: "Up", VK_DOWN: "Down",
        0x09: "Tab", 0x20: "Space",
    }
    if vk in names:
        return names[vk]
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    return f"VK 0x{vk:02X}"
