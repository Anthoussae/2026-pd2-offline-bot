"""T42 — read the game's own item-code table, and regenerate item_codes.toml.

`dwTxtFileNo` — the number every item unit carries and the only item
identity our perception has — is an INDEX into the game's combined item
record array. Each record holds the item's 3/4-letter code ('hp5', 'r30',
'box'). So that array is the Rosetta stone between what we can read and
what a human (or a loot filter) calls things.

**Finding it needs no offset.** The array's address is a heap pointer that
moves every launch, so it is triangulated instead, from ids already
verified by other means:

    533 -> 'tbk' and 534 -> 'ibk' are ADJACENT, so the distance between
    those two strings in memory IS the record stride — no guessing.
    564 -> 'box' must then also land correctly at that stride.

Three simultaneous anchors is far more than coincidence can supply, and
the fit is checked afterwards against six further independently-verified
ids (530/531 rejuvs, 606 healing, 610/611 mana, and index 0 = 'hax', the
first record in the game's own ordering).

One subtlety, and it is the reason this drill states its reasoning: each
record holds the code FOUR times over — code, normcode, ubercode,
ultracode — so several bases satisfy the anchors. They are told apart
structurally: only the true `code` column ever contains ELITE codes
('uap' Shako, 'utp' Archon Plate). The normcode column holds base-item
codes exclusively, because that is what a normcode IS.

Read-only, and needs no human at all: nothing is sent, nothing is
clicked, the character is not touched. Re-run it after a PD2 season
patch, which is exactly when item numbering can move.

Run from the repo root (bridge, elevated):
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t42_item_code_table
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
OUT_PATH = REPO / "config" / "item_codes.toml"

# (index -> code) pairs verified by earlier live work. The first two are
# adjacent, which is what makes the stride derivable rather than guessed.
ANCHOR_LOW, ANCHOR_HIGH = (533, b"tbk"), (534, b"ibk")
ANCHOR_CHECK = (564, b"box")
# Independently verified elsewhere; used to score the fit, not to find it.
CORROBORATION = {
    0: "hax", 530: "rvs", 531: "rvl", 606: "hp5", 610: "mp4", 611: "mp5",
}
# Elite codes: present in the true code column, absent from normcode.
ELITE_MARKERS = ("uap", "uea", "uul", "utp")
MAX_INDEX = 800


T42 = Drill(
    test_id="T42",
    title="Item code table by triangulation",
    kind="perception",
    instructions=(
        "READ-ONLY and fully automatic - nothing is sent, nothing is",
        "clicked, and you do not need to do anything at all.",
        "Just be in a game so the client's data is loaded.",
    ),
)


def find_table(session) -> tuple[int, int]:
    """(base, stride) of the item-code array. Raises if not triangulated."""
    def occurrences(code: bytes) -> set[int]:
        found: set[int] = set()
        for pad in (b" ", b"\x00"):
            found |= set(session.search(code + pad, limit=600))
        return found

    low_idx, low_code = ANCHOR_LOW
    high_idx, high_code = ANCHOR_HIGH
    check_idx, check_code = ANCHOR_CHECK
    lows, highs, checks = (
        occurrences(low_code), occurrences(high_code), occurrences(check_code)
    )
    print(
        f"occurrences: {low_code!r} {len(lows)}, {high_code!r} {len(highs)}, "
        f"{check_code!r} {len(checks)}",
        flush=True,
    )

    strides = Counter()
    candidates = []
    for a_low in lows:
        for a_high in highs:
            stride = a_high - a_low
            if not 0x40 <= stride <= 0x800:
                continue
            strides[stride] += 1
            base = a_low - low_idx * stride
            if base > 0 and base + check_idx * stride in checks:
                candidates.append((base, stride))
    print(f"candidate strides: {strides.most_common(5)}", flush=True)
    if not candidates:
        raise DrillAborted(
            "could not triangulate the item table — the anchors did not "
            "line up at any stride. PD2 may have changed its item ordering; "
            "re-derive the anchors before trusting anything downstream"
        )

    # Several bases fit (code/normcode/ubercode/ultracode all hold codes).
    # Only the true code column carries elite codes.
    best = None
    for base, stride in sorted(set(candidates)):
        codes = read_codes(session, base, stride)
        elites = [m for m in ELITE_MARKERS if m in codes.values()]
        print(
            f"  base {base:#x} stride {stride:#x}: {len(codes)} codes, "
            f"elite markers {elites}",
            flush=True,
        )
        if len(elites) == len(ELITE_MARKERS) and best is None:
            best = (base, stride)
    if best is None:
        raise DrillAborted(
            "found the array but no candidate base carried elite codes — "
            "every fit looks like a normcode column, so the true code "
            "column was not located"
        )
    return best


def read_codes(session, base: int, stride: int) -> dict[int, str]:
    codes: dict[int, str] = {}
    for index in range(MAX_INDEX):
        try:
            raw = session.raw(base + index * stride, 4)
        except Exception:
            break
        text = raw.decode("ascii", "replace").strip()
        if not text or any(not (32 <= ord(c) <= 126) for c in text):
            continue
        codes[index] = text
    return codes


def t42_body(run: DrillRun) -> str:
    session = run.session
    run.say("T42: reading the game's item table. Nothing to do - sit tight.")

    base, stride = find_table(session)
    codes = read_codes(session, base, stride)
    print(f"\ntable at {base:#x}, stride {stride:#x}, {len(codes)} codes", flush=True)

    # Score the fit against ids verified by other means. A single miss
    # here means the array was located but is not the one we think.
    misses = [
        f"{idx}: expected {want}, read {codes.get(idx)!r}"
        for idx, want in CORROBORATION.items()
        if codes.get(idx) != want
    ]
    if misses:
        raise DrillAborted(
            "the located table disagrees with independently-verified ids — "
            + "; ".join(misses)
        )
    print("corroboration: all " + str(len(CORROBORATION)) + " known ids agree", flush=True)

    lines = [
        "# kind (dwTxtFileNo) -> the game's own 3/4-letter item code.",
        "#",
        "# GENERATED by the T42 drill, read from the LIVE game. Do not",
        "# hand-edit: PD2 renumbers item kinds between seasons, which is",
        "# why no inherited table is trusted here. Re-run T42 after a",
        "# season patch.",
        "#",
        f"# located by triangulation at stride {stride:#x}; corroborated by "
        f"{len(CORROBORATION)} independently-verified ids.",
        "",
        "[codes]",
    ]
    lines += [f'{index} = "{code}"' for index, code in sorted(codes.items())]
    OUT_PATH.write_text("\n".join(lines) + "\n", encoding="ascii")

    run.say(f"Read {len(codes)} item codes. Done - nothing else needed.")
    return (
        f"{len(codes)} codes written to {OUT_PATH.name} "
        f"(stride {stride:#x}); {len(CORROBORATION)} known ids corroborate"
    )


if __name__ == "__main__":
    raise SystemExit(0 if run_drill(T42, t42_body, session=GameSession()) == "PASS" else 1)
