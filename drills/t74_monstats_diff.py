"""T74 — finding the NPC flag: diff a real monster against a phantom.

**READ-ONLY. Sends no input.** Stand anywhere with real monsters in view
(Tower Cellar 1 is where T73 run 2 was taken) and type OK.

WHY THIS EXISTS. T73 settled two things and destroyed a third:

- Allies carry the friendly-alignment stat (172 == 2). Merc: 76 stats,
  align 2. Revives: 14 stats, align 2.
- **Real monsters do NOT carry it.** All 39 hostiles in Tower Cellar 1
  read `align ABSENT`. So "no alignment stat" cannot mean "not an
  enemy" — that rule would make the bot pacifist, and it was the fix
  this probe's predecessor was about to justify.
- Therefore alignment separates ALLY from everything-else, and nothing
  currently separates a real monster from a non-combat unit.

The phantoms the bot has been attacking are **kind 159**: 5 stats,
hp 100, present in both the Forgotten Tower (where the operator states
there are never hostiles) and Tower Cellar 1. Real monsters there are
kinds 21 and 55: 9-10 stats, hp 128.

kolbot's own SDK declares `readonly isNPC: boolean` on a unit, so D2
carries this distinction somewhere; d2bs reads it in C++ that is not in
our reference clone. In the game's data it comes from MonStats.txt,
reachable from `MonsterData -> pMonstatsTxt` (the first field).

So this probe does what this project has always done when an offset is
unknown: **read the same structure for a known-good and a known-bad
example and diff them.** Whatever byte separates a Fallen from a kind-159
dummy is the flag we need — found by measurement, not by guessing at a
struct layout.

Output: for each distinct kind seen, one representative unit's MonStats
record as a hexdump, plus its full stat list. Diff the kind-159 record
against the kind-21 record and the discriminating field is whatever
differs consistently.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t74_monstats_diff
"""

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.units import (  # noqa: E402
    iter_units_of_type,
    player_unit,
    read_stats,
    unit_position,
)
from pd2bot.perception.world import read_area  # noqa: E402

MONSTER_TXT_PTR = 0x00  # MonsterData -> pMonstatsTxt (D2Structs.h)
RECORD_BYTES = 96  # generous: MonStats records are large; we diff, not parse
KNOWN_DUMMY_KINDS = (159,)  # what T73 caught the bot attacking
# Sample over a WINDOW rather than one instant. Run 1 of this probe came
# back "no dummy/real pair in range" purely because the critters happened
# to have wandered off at that moment — T73 had already proven three of
# them in this very level. A probe that depends on luck is a probe that
# has to be re-run and re-explained, so it now collects one representative
# per kind across the whole window and diffs whatever it accumulated.
SAMPLES = 14
SAMPLE_GAP_S = 1.5


def _hexdump(raw: bytes, width: int = 16) -> list[str]:
    lines = []
    for offset in range(0, len(raw), width):
        chunk = raw[offset : offset + width]
        hexed = " ".join(f"{b:02x}" for b in chunk)
        lines.append(f"    +{offset:03x}  {hexed}")
    return lines


def _collect(session: GameSession, origin, by_kind: dict[int, dict]) -> None:
    """Add one representative per NEW kind within perception range.

    Mutates `by_kind` so repeated calls accumulate across samples; a kind
    already held is never re-read, so the first sighting is the one kept.
    """
    for unit in iter_units_of_type(session, offsets.UNIT_TYPE_MONSTER):
        try:
            kind = session.u32(unit + offsets.UNIT_TXT_FILE_NO)
            if kind in by_kind:
                continue
            position = unit_position(session, unit, offsets.UNIT_TYPE_MONSTER)
            if position is None or origin is None:
                continue
            if max(
                abs(position[0] - origin[0]), abs(position[1] - origin[1])
            ) > 80:
                continue
            data = session.ptr(unit + offsets.UNIT_DATA)
            txt = session.ptr(data + MONSTER_TXT_PTR) if data else None
            by_kind[kind] = {
                "id": session.u32(unit + offsets.UNIT_ID),
                "kind": kind,
                "pos": position,
                "monster_data": data,
                "monstats_txt": txt,
                "stats": read_stats(session, unit),
                "record": session.raw(txt, RECORD_BYTES) if txt else None,
                # The MonsterData block too, in case the flag lives there
                # rather than in the txt record.
                "data_block": session.raw(data, 48) if data else None,
            }
        except Exception:  # noqa: BLE001 - a torn unit is skipped, not fatal
            continue


def make_drill() -> tuple[Drill, object]:
    drill = Drill(
        test_id="T74",
        title="MonStats diff — find the flag that separates a monster from a dummy",
        kind="perception",
        sends_input=False,
        instructions=(
            "READ-ONLY PROBE — no input is sent and the character will",
            "not move.",
            "Stand somewhere with REAL MONSTERS in view (Tower Cellar 1",
            "is where the last census was taken). Type OK.",
            "It reads the game's own monster-type record for one example",
            "of each kind present, so the record for a real monster can",
            "be compared byte-for-byte against the record for the",
            "kind-159 units the bot has been attacking by mistake.",
            "Takes about a second. Nothing happens on screen.",
        ),
    )

    def body(run: DrillRun) -> str:
        session = run.session
        player = player_unit(session)
        origin = (
            unit_position(session, player, offsets.UNIT_TYPE_PLAYER)
            if player is not None
            else None
        )
        area = read_area(session)
        print(
            f"area {area.level_no if area else '?'} "
            f"({offsets.AREA_NAMES.get(area.level_no, '?') if area else '?'}), "
            f"player at {origin}",
            flush=True,
        )

        # One representative per kind, accumulated across the WINDOW.
        # Run 1 came back "no dummy/real pair in range" purely because the
        # critters had wandered off at that instant, though T73 had already
        # proven three of them in this level. A probe that depends on luck
        # is one the operator has to run twice.
        by_kind: dict[int, dict] = {}
        for sample in range(SAMPLES):
            if sample:
                time.sleep(SAMPLE_GAP_S)
            _collect(session, origin, by_kind)
            have_dummy = any(k in by_kind for k in KNOWN_DUMMY_KINDS)
            have_real = any(k not in KNOWN_DUMMY_KINDS for k in by_kind)
            if have_dummy and have_real:
                print(
                    f"  (pair found after {sample + 1} sample(s))", flush=True
                )
                break

        if not by_kind:
            return "no monster-type units in range — nothing to diff"

        for kind in sorted(by_kind):
            row = by_kind[kind]
            label = " <-- SUSPECTED NON-COMBAT (T73)" if kind in KNOWN_DUMMY_KINDS else ""
            print(f"\n=== kind {kind}{label} ===", flush=True)
            print(
                f"  unit {row['id']} at {row['pos']}, "
                f"{len(row['stats'])} stat(s), "
                f"pMonstatsTxt={row['monstats_txt']!r}",
                flush=True,
            )
            print(
                "  stats: "
                + ", ".join(f"{k}={v}" for k, v in sorted(row["stats"].items())),
                flush=True,
            )
            if row["data_block"]:
                print("  MonsterData block:", flush=True)
                for line in _hexdump(row["data_block"]):
                    print(line, flush=True)
            if row["record"]:
                print("  MonStats record:", flush=True)
                for line in _hexdump(row["record"]):
                    print(line, flush=True)
            else:
                print("  MonStats record: UNREADABLE", flush=True)

        # The comparison, made explicit rather than left to the eye.
        dummies = [k for k in by_kind if k in KNOWN_DUMMY_KINDS]
        reals = [k for k in by_kind if k not in KNOWN_DUMMY_KINDS]
        if dummies and reals:
            dummy, real = by_kind[dummies[0]], by_kind[reals[0]]
            print(
                f"\n=== BYTE DIFF: kind {real['kind']} (real) vs "
                f"kind {dummy['kind']} (suspected dummy) ===",
                flush=True,
            )
            for label, key in (("MonsterData", "data_block"), ("MonStats", "record")):
                a, b = real.get(key), dummy.get(key)
                if not a or not b:
                    print(f"  {label}: one side unreadable", flush=True)
                    continue
                differing = [
                    (i, a[i], b[i]) for i in range(min(len(a), len(b))) if a[i] != b[i]
                ]
                print(
                    f"  {label}: {len(differing)} differing byte(s) of "
                    f"{min(len(a), len(b))}",
                    flush=True,
                )
                for index, left, right in differing[:40]:
                    print(
                        f"    +{index:03x}  real={left:#04x}  dummy={right:#04x}",
                        flush=True,
                    )
            # Stat indices one has and the other lacks — a stat-shape
            # difference is as usable a discriminator as a flag byte.
            only_real = sorted(set(real["stats"]) - set(dummy["stats"]))
            only_dummy = sorted(set(dummy["stats"]) - set(real["stats"]))
            print(f"  stat indices only the REAL monster has: {only_real}", flush=True)
            print(f"  stat indices only the DUMMY has: {only_dummy}", flush=True)

        return (
            f"kinds sampled: {sorted(by_kind)}; "
            f"stat counts: "
            + ", ".join(
                f"kind {k}={len(by_kind[k]['stats'])}" for k in sorted(by_kind)
            )
            + (
                f"; diffed {reals[0]} against {dummies[0]}"
                if dummies and reals else "; no dummy/real pair in range"
            )
        )

    return drill, body


if __name__ == "__main__":
    status = run_drill(*make_drill(), run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
