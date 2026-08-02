"""Verified skill switching and belt keys: trust the read-back, never the
keypress.

The pattern is M4's difficulty guard applied to skills (M5 plan, decision 4):
a hotkey press is a *request*, and the only proof it took is the right-skill
id read back from memory (player.read_active_skills, live-verified in R52
drill A). No cast click may be sent on an unverified skill — casting Blood
Warp when the game heard Desecrate would teleport-cost the character instead
of making corpses, mid-combat.

The hotkey table below is the character's binding as captured live (R47,
R52): F1-F6 on the right skill. It is the *default*; the behavior layer (P4)
passes its own table from the class config, so other characters need no code
change here.

Belt drinking is the dumb primitive only — press the column's key through
the gate. Cooldown bookkeeping (10 s heal, 15 s mana, R49) belongs to the
reflex ladder, which owns the *when*; this module owns the *how*.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from pd2bot import offsets
from pd2bot.input import (
    VK_1,
    VK_2,
    VK_3,
    VK_4,
    VK_F1,
    VK_F2,
    VK_F3,
    VK_F4,
    VK_F5,
    VK_F6,
    GatedInput,
)
from pd2bot.memory import GameSession
from pd2bot.player import read_active_skills

# The necro's right-skill hotkeys, as bound in the live client (R47.1, ids
# captured R52 drill A). Callers with their own config pass their own table.
DEFAULT_HOTKEYS: dict[int, int] = {
    offsets.SKILL_BONE_ARMOR: VK_F1,
    offsets.SKILL_BLOOD_WARP: VK_F2,
    offsets.SKILL_TP_TOME: VK_F3,
    offsets.SKILL_BONE_WALL: VK_F4,
    offsets.SKILL_DESECRATE: VK_F5,
    offsets.SKILL_REVIVE: VK_F6,
}

# Belt columns 0-3 are the keys 1-4 (permanent layout, R53: mana / rejuv /
# health / health — but the *meaning* is config; this maps column to key).
BELT_KEYS = (VK_1, VK_2, VK_3, VK_4)

# One press usually registers within a frame or two; the game runs a 25 fps
# sim, so 0.6 s is ~15 frames of patience before re-pressing.
_VERIFY_TIMEOUT_S = 0.6
_POLL_S = 0.05
_PRESSES = 3  # initial press + 2 re-presses before giving up


class SkillSwitchFailed(RuntimeError):
    """The right skill never read back as the requested one. No cast was sent."""


def ensure_right_skill(
    session: GameSession,
    gated: GatedInput,
    skill_id: int,
    *,
    hotkeys: dict[int, int] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Make `skill_id` the active right skill, verified from memory.

    Returns only when the read-back confirms the switch; raises
    SkillSwitchFailed (never a guess) otherwise. Already-active skills
    return without sending anything.
    """
    table = hotkeys if hotkeys is not None else DEFAULT_HOTKEYS

    def active() -> int | None:
        skills = read_active_skills(session)
        return skills.right_id if skills is not None else None

    if active() == skill_id:
        return

    key = table.get(skill_id)
    if key is None:
        raise SkillSwitchFailed(
            f"skill {skill_id} has no hotkey in the table — cannot switch to it"
        )

    started = clock()
    for _ in range(_PRESSES):
        gated.press_key(key)
        deadline = clock() + _VERIFY_TIMEOUT_S
        while clock() < deadline:
            if active() == skill_id:
                return
            sleep(_POLL_S)

    raise SkillSwitchFailed(
        f"right skill reads {active()} after {_PRESSES} presses of the hotkey "
        f"for skill {skill_id} — no cast will be sent on an unverified skill "
        f"[{_failure_context(session, clock() - started)}]"
    )


def _failure_context(session: GameSession, waited: float) -> str:
    """What the world looked like at the moment a switch would not verify.

    This exists because the failure has now outlived two theories and three
    live runs. T47 pressed all six hotkeys and every one selected exactly
    what `config/necro.toml` claims, so the bindings are right and the
    presses land. T48 then showed a press sent 110 ms into a cast animation
    still registers within 62 ms, so a cast does not eat them either. Two
    more candidates die on the code as written: a blocking panel (the chat
    console included) makes `press_key` raise `InputRefused` instead, and so
    does losing the foreground.

    What is left can only be told apart from inside the failure, so the next
    occurrence carries its own evidence rather than costing another
    supervised run. Everything here is read ONLY on the failure path and
    every read is defended: an exception while explaining an exception would
    replace the diagnosis with a traceback about the diagnosis.
    """
    parts = [f"waited {waited:.2f}s"]
    try:
        from pd2bot.player import read_player

        player = read_player(session)
        parts.append(
            f"player mode {player.mode}, hp {player.hp}, mana {player.mana}"
            if player is not None
            else "player UNREADABLE"
        )
    except Exception as exc:  # noqa: BLE001 - diagnosis must not raise
        parts.append(f"player read raised {type(exc).__name__}")
    try:
        from pd2bot import uistate

        state = uistate.read_ui_state(session)
        parts.append(
            f"ui {', '.join(state.names) or 'nothing open'}"
            + (" (BLOCKING)" if state.blocks_input else "")
        )
    except Exception as exc:  # noqa: BLE001
        parts.append(f"ui read raised {type(exc).__name__}")
    try:
        skills = read_active_skills(session)
        parts.append(
            f"left reads {skills.left_id}" if skills is not None
            else "skills UNREADABLE"
        )
    except Exception as exc:  # noqa: BLE001
        parts.append(f"skill read raised {type(exc).__name__}")
    return "; ".join(parts)


def belt_drink(gated: GatedInput, column: int) -> None:
    """Press one belt column's drink key (0-3 -> keys 1-4), through the gate."""
    if not 0 <= column < len(BELT_KEYS):
        raise ValueError(f"belt column must be 0-3, got {column}")
    gated.press_key(BELT_KEYS[column])


def belt_give_merc(gated: GatedInput, column: int) -> None:
    """Shift + one belt column's key: feed that potion to the mercenary
    (R179, chord corrected to Shift at R183 — user-verified by hand).

    The dumb primitive only, like `belt_drink`: the WHEN (merc hp
    threshold, pacing, which column holds a healing potion) is the reflex
    ladder's; the chord sequencing (Shift provably down first) is the
    input layer's."""
    if not 0 <= column < len(BELT_KEYS):
        raise ValueError(f"belt column must be 0-3, got {column}")
    gated.press_key_with_shift(BELT_KEYS[column])
