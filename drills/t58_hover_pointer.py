"""T58 — does the client keep a pointer to the unit under the cursor?

**Why this exists (T57, 2026-08-02):** 30 potion-pickup decisions produced
ONE arrival. The clicks land on a projected POINT and hope the potion's
small sprite is under it — blind, and mostly wrong. The game itself knows
what the cursor is on: if a hovered-unit pointer exists in memory, the bot
can move the cursor, READ what it is actually over, adjust until the
target confirms, and only then click. This drill goes and finds that
pointer, the way T40 found the chat buffer: a value the user can change at
will (by hovering), scanned for, then made to change twice more to
separate the real pointer from list links and coincidences.

Read-only: the bot sends nothing; you drive the cursor.

## Protocol

1. Self-check — the player's own unit address must be findable by the
   scanner, or every negative below is meaningless and the drill stops.
2. You DROP A POTION (any type) on open ground near your character; the
   drill spots the new ground unit and records its address.
3. Round A — you hover the potion, holding the cursor still; the whole
   address space is scanned for pointers to its unit.
4. Round B — you move the cursor to EMPTY ground: a real hover pointer
   must CHANGE; candidates still holding the address are struck off.
5. Round C — you hover the potion again: survivors must return to it.
6. Round D — you hover your MERC: reports whether the pointer tracks
   living units too, or only items (either answer is useful).

## How it ends

On its own, after round D — about 3-5 minutes. Cancel any time: type
'abort' in chat, or run tools\\drill-cancel.ps1.
"""

import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.units import (  # noqa: E402
    _read_ground_item,
    iter_units_of_type,
    player_unit,
    unit_position,
)

MAX_REPORTED = 12
DROP_TIMEOUT_S = 300.0
HOVER_SETTLE_TIMEOUT_S = 180.0
NEAR_SUBTILES = 15  # a dropped potion lands at the feet, not across town

T58 = Drill(
    test_id="T58",
    title="hovered-unit pointer hunt — what is the cursor on?",
    kind="human calibration",
    sends_input=False,
    instructions=(
        "SETUP: in town, panels closed. You drive the cursor; I only read.",
        "You will DROP A POTION on the ground, then hover it / leave it /",
        "hover it again / hover your merc, on my marks. Four short rounds.",
        "IT ENDS ON ITS OWN after the merc round (3-5 minutes).",
        "Cancel any time: 'abort' in chat, or tools\\drill-cancel.ps1.",
    ),
)


def _ground_units_near(
    run: DrillRun, origin: tuple[int, int]
) -> dict[int, tuple[int, int, tuple[int, int]]]:
    """unit_id -> (address, kind, position) for floor items near `origin`."""
    found: dict[int, tuple[int, int, tuple[int, int]]] = {}
    for unit in iter_units_of_type(run.session, offsets.UNIT_TYPE_ITEM):
        item = _read_ground_item(run.session, unit)
        if item is None:
            continue
        if (
            abs(item.position[0] - origin[0]) <= NEAR_SUBTILES
            and abs(item.position[1] - origin[1]) <= NEAR_SUBTILES
        ):
            found[item.unit_id] = (unit, item.kind, item.position)
    return found


def _player_origin(run: DrillRun) -> tuple[int, int]:
    unit = player_unit(run.session)
    if unit is None:
        raise RuntimeError("no player unit — not in a game?")
    position = unit_position(run.session, unit, offsets.UNIT_TYPE_PLAYER)
    if position is None:
        raise RuntimeError("the player unit has no readable position")
    return position


def _await_hover_still(run: DrillRun, prompt: str) -> None:
    """Announce `prompt`, then wait for a deliberate move + a still cursor.

    `capture_hover` carries the two lessons this would otherwise relearn:
    the re-arm (the capture must not fire on wherever the hand already
    rests, R57/R86) and the stillness window. The point it returns is not
    needed — 'the cursor has settled' is the whole signal.
    """
    run.say(prompt)
    if (
        run.capture_hover(
            required_panel=None,
            last_point=None,
            timeout_s=HOVER_SETTLE_TIMEOUT_S,
        )
        is None
    ):
        raise RuntimeError(f"the cursor never settled: {prompt!r}")


def _describe_value(run: DrillRun, value: int) -> str:
    """What a candidate points AT right now, resolved as a unit if it is one."""
    if value == 0:
        return "null"
    try:
        unit_type = run.session.u32(value + offsets.UNIT_TYPE)
        unit_id = run.session.u32(value + offsets.UNIT_ID)
        kind = run.session.u32(value + offsets.UNIT_TXT_FILE_NO)
    except Exception:
        return f"0x{value:x} (not readable as a unit)"
    return f"0x{value:x} (unit type {unit_type} id {unit_id} kind {kind})"


def t58_body(run: DrillRun) -> str:
    session = run.session
    modules = session.modules()

    # -- self-check: the scanner must find a pointer we KNOW exists --------
    me = player_unit(session)
    if me is None:
        raise RuntimeError("no player unit — not in a game?")
    started = time.monotonic()
    self_hits = session.search(struct.pack("<I", me))
    scan_s = time.monotonic() - started
    print(
        f"self-check: player unit 0x{me:x} found at {len(self_hits)} "
        f"address(es) in {scan_s:.1f}s",
        flush=True,
    )
    if not self_hits:
        raise RuntimeError(
            "SCANNER IS BLIND — the player unit pointer is at a cited offset "
            "and must be findable; stopping rather than reporting a false "
            "negative"
        )

    # -- the dropped potion ------------------------------------------------
    origin = _player_origin(run)
    before = set(_ground_units_near(run, origin))
    dropped: list[tuple[int, int, int, tuple[int, int]]] = []

    def check_drop() -> bool:
        for unit_id, (address, kind, position) in _ground_units_near(
            run, _player_origin(run)
        ).items():
            if unit_id not in before:
                dropped.append((unit_id, address, kind, position))
                return True
        return False

    if not run.announce_until(
        "Drop ONE potion (any type) on open ground near your character.",
        check_drop,
        timeout_s=DROP_TIMEOUT_S,
    ):
        raise RuntimeError("no new ground item appeared — nothing was dropped?")
    unit_id, address, kind, position = dropped[0]
    needle = struct.pack("<I", address)
    run.say(f"Saw it: kind {kind} at {position}.")
    print(
        f"target: unit id {unit_id} kind {kind} at {position}, "
        f"unit address 0x{address:x}",
        flush=True,
    )

    # -- round A: hover it, scan for pointers to it ------------------------
    _await_hover_still(
        run,
        "ROUND A: hover the cursor DIRECTLY over the dropped potion "
        "and hold still.",
    )
    candidates = session.search(needle)
    print(f"round A: {len(candidates)} address(es) hold 0x{address:x}", flush=True)
    for hit in candidates[:MAX_REPORTED]:
        print(f"  A: {session.describe(hit, modules)}", flush=True)
    if not candidates:
        return (
            "NO POINTER AT ALL: nothing in memory holds the hovered item's "
            "unit address — hover is tracked some other way (id? screen "
            "coords?); scanner verified working"
        )

    # -- round B: hover empty ground; the real pointer must move -----------
    _await_hover_still(
        run,
        "ROUND B: move the cursor to EMPTY ground, away from every item, "
        "unit and NPC, and hold still.",
    )
    away = [c for c in candidates if session.raw(c, 4) != needle]
    print(
        f"round B: {len(away)} of {len(candidates)} changed away "
        "(list links and coincidences hold on)",
        flush=True,
    )

    # -- round C: hover it again; survivors must come back -----------------
    _await_hover_still(
        run, "ROUND C: hover the SAME potion again and hold still."
    )
    stable = [c for c in away if session.raw(c, 4) == needle]
    print(f"round C: {len(stable)} candidate(s) returned to the potion", flush=True)
    for hit in stable[:MAX_REPORTED]:
        print(f"  STABLE: {session.describe(hit, modules)}", flush=True)
    if not stable:
        return (
            f"NO STABLE POINTER: round A found {len(candidates)} holder(s), "
            f"{len(away)} moved away in B, none returned in C — the hover "
            "location is reallocated per hover and needs a pointer chain"
        )

    # -- round D: does it track living units too? --------------------------
    _await_hover_still(
        run, "ROUND D: hover your MERCENARY (or any NPC) and hold still."
    )
    readings = [
        f"{session.describe(c, modules)} -> "
        f"{_describe_value(run, session.u32(c))}"
        for c in stable[:MAX_REPORTED]
    ]
    for line in readings:
        print(f"  D: {line}", flush=True)

    in_module = [
        session.describe(c, modules) for c in stable if "heap:" not in session.describe(c, modules)
    ]
    return (
        f"FOUND {len(stable)} stable hover pointer(s): "
        f"{'; '.join(session.describe(c, modules) for c in stable[:6])}. "
        f"{len(in_module)} module-relative (durable offset candidates). "
        f"Merc round: {'; '.join(readings[:3]) or 'n/a'}"
    )


if __name__ == "__main__":
    status = run_drill(T58, t58_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
