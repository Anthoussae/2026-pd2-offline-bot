"""T73 — the hostile census: what does the bot think is an enemy, and why?

**READ-ONLY. Sends no input.** The character never moves. Stand where you
want the census taken (the Forgotten Tower for the run this was built
for), type OK, and the probe reads memory and prints a table.

WHY THIS EXISTS. T72 recorded the bot attacking two units, 23 strikes
each, that never died — in a room the operator states has never contained
a hostile, and cannot. The same run counted 2 then 5 "hostiles" in the
**Rogue Encampment**, which provably has none. So the classifier is
wrong, and the code shows two ways it can be:

1. **Locality is a radius, not a level.** `scan_units` keeps any unit
   within 80 subtiles of the player. Its own docstring says the hash
   table holds "the whole stash, units from other levels, expired
   summons". A unit's level IS readable (Path -> Room1 -> Room2 ->
   Level -> dwLevelNo) and nothing checks it.
2. **Hostility is inferred from absence.** `_read_monster` does
   `alignment = stats.get(STAT_ALIGNMENT, 0)` and `is_ally` is
   `alignment == 2`. `read_stats` returns `{}` for an unreadable stat
   list — so a torn read, a stat-less unit and a genuine enemy are
   indistinguishable, and all three come out hostile. `offsets.py`
   already records that town guards "lack the friendly-alignment stat
   entirely, so they show up in the *monster* list in town"; nobody
   asked whether the same happens outside town.

This probe does not assume either. It records every signal that could
separate a real enemy from a phantom and lets the data decide:

- **alignment ABSENT vs alignment == 0** — the distinction the current
  code destroys, and the single most likely culprit.
- the unit's own level id vs the player's — the locality question.
- mode, hp, flags, the MonsterData pointer, the stat-list count.
- what `scan_units` classifies it as TODAY, side by side with the raw
  reads, so the disagreement is visible rather than inferred.

It samples several times a second apart, because a phantom that persists
is a different animal from one that flickers.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t73_hostile_census
"""

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.units import (  # noqa: E402
    iter_units_of_type,
    player_unit,
    read_stats,
    unit_position,
)
from pd2bot.world import read_area  # noqa: E402

SAMPLES = 8
SAMPLE_GAP_S = 1.5
# MonsterData's first field is pMonstatsTxt (D2Structs.h). Read as a
# CANDIDATE only — it is the documented route to the MonStats "npc"
# column, which is how a townsfolk is told from a monster, and this
# probe exists to find out whether we need it.
MONSTER_TXT_PTR = 0x00


def _level_of(session: GameSession, unit: int) -> int | None:
    """The level a unit is actually in: Path -> Room1 -> Room2 -> Level.

    The locality check `scan_units` does not do. None means the chain
    could not be walked, which is itself a finding — a unit with no room
    is not standing anywhere.
    """
    try:
        path = session.ptr(unit + offsets.UNIT_PATH)
        if path is None:
            return None
        room1 = session.ptr(path + offsets.PATH_ROOM1)
        if room1 is None:
            return None
        room2 = session.ptr(room1 + offsets.ROOM1_ROOM2)
        if room2 is None:
            return None
        level = session.ptr(room2 + offsets.ROOM2_LEVEL)
        if level is None:
            return None
        return session.u32(level + offsets.LEVEL_NO)
    except Exception:  # noqa: BLE001 - a broken chain is data, not an error
        return None


def _census(session: GameSession) -> tuple[list[dict], dict]:
    """Every type-1 unit the client knows about, with every signal."""
    player = player_unit(session)
    origin = (
        unit_position(session, player, offsets.UNIT_TYPE_PLAYER)
        if player is not None
        else None
    )
    area = read_area(session)
    context = {
        "player_pos": origin,
        "area": area.level_no if area is not None else None,
        "area_name": (
            offsets.AREA_NAMES.get(area.level_no, f"area {area.level_no}")
            if area is not None else "?"
        ),
        "player_level": _level_of(session, player) if player else None,
    }

    rows: list[dict] = []
    for unit in iter_units_of_type(session, offsets.UNIT_TYPE_MONSTER):
        row: dict = {}
        try:
            row["id"] = session.u32(unit + offsets.UNIT_ID)
            row["kind"] = session.u32(unit + offsets.UNIT_TXT_FILE_NO)
            row["mode"] = session.u32(unit + offsets.UNIT_MODE)
            position = unit_position(session, unit, offsets.UNIT_TYPE_MONSTER)
            row["pos"] = position
            row["dist"] = (
                max(abs(position[0] - origin[0]), abs(position[1] - origin[1]))
                if position and origin else None
            )
            row["level"] = _level_of(session, unit)

            data = session.ptr(unit + offsets.UNIT_DATA)
            row["has_monster_data"] = data is not None
            row["flags"] = (
                session.u8(data + offsets.MONSTER_FLAGS) if data else None
            )
            row["monstats_txt"] = (
                session.ptr(data + MONSTER_TXT_PTR) if data else None
            )

            # THE distinction the production code destroys: was the
            # alignment stat present, or merely absent?
            stat_list = session.ptr(unit + offsets.UNIT_STATS)
            row["has_stat_list"] = stat_list is not None
            stats = read_stats(session, unit)
            row["stat_count"] = len(stats)
            row["align_present"] = offsets.STAT_ALIGNMENT in stats
            row["align"] = stats.get(offsets.STAT_ALIGNMENT)
            row["hp"] = stats.get(offsets.STAT_HP)
            row["max_hp"] = stats.get(offsets.STAT_MAX_HP)

            # What the bot decides TODAY, reproduced exactly.
            align_now = stats.get(offsets.STAT_ALIGNMENT, 0)
            is_corpse = row["mode"] in (
                offsets.MONSTER_MODE_DEATH, offsets.MONSTER_MODE_DEAD
            )
            row["verdict"] = (
                "corpse" if is_corpse
                else "ALLY" if align_now == offsets.ALIGNMENT_FRIENDLY
                else "HOSTILE"
            )
            row["near"] = (
                row["dist"] is not None and row["dist"] <= 80
            )
        except Exception as exc:  # noqa: BLE001 - a torn unit is a finding
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
    return rows, context


def _format(rows: list[dict], context: dict) -> list[str]:
    lines = [
        f"area {context['area']} ({context['area_name']}), "
        f"player at {context['player_pos']}, "
        f"player's room level {context['player_level']}",
        "",
        f"{'verdict':<8} {'id':>8} {'kind':>5} {'mode':>4} {'dist':>5} "
        f"{'lvl':>4} {'align':>7} {'stats':>5} {'hp':>6} {'flags':>5}  pos",
    ]
    for row in rows:
        if "error" in row:
            lines.append(f"  UNREADABLE: {row['error']}")
            continue
        align = (
            str(row["align"]) if row["align_present"]
            else ("ABSENT" if row["has_stat_list"] else "NO-LIST")
        )
        flag = "" if row["flags"] is None else f"{row['flags']:#04x}"
        mark = "" if row["near"] else "  (outside the 80-subtile radius)"
        lines.append(
            f"{row['verdict']:<8} {row['id']:>8} {row['kind']:>5} "
            f"{row['mode']:>4} {str(row['dist']):>5} {str(row['level']):>4} "
            f"{align:>7} {row['stat_count']:>5} "
            f"{str(row['hp']):>6} {flag:>5}  {row['pos']}{mark}"
        )
    return lines


def make_drill() -> tuple[Drill, object]:
    drill = Drill(
        test_id="T73",
        title="hostile census — what the bot calls an enemy, and why",
        kind="perception",
        sends_input=False,  # READ-ONLY: nothing is clicked, nothing moves
        instructions=(
            "READ-ONLY PROBE — the bot sends NO input and will not move.",
            "Stand where you want the census taken (the Forgotten Tower",
            "floor, with your merc and revives up, is the case this was",
            "built for), then type OK.",
            "It reads every monster-type unit the client knows about and",
            "prints what it is, where it is, which LEVEL it is in, and",
            "whether it carries the friendly-alignment stat at all.",
            "Takes about 5 seconds. Nothing will happen on screen.",
        ),
    )

    def body(run: DrillRun) -> str:
        samples = []
        for index in range(SAMPLES):
            rows, context = _census(run.session)
            samples.append((rows, context))
            print(f"\n=== sample {index + 1} of {SAMPLES} ===", flush=True)
            for line in _format(rows, context):
                print(line, flush=True)
            if index < SAMPLES - 1:
                time.sleep(SAMPLE_GAP_S)

        # The summary the analysis actually needs, aggregated over EVERY
        # sample rather than judged on the last one. In a live area the
        # monsters are dying and the character is moving while this runs,
        # so a unit seen once is evidence and a last-sample snapshot
        # would throw most of it away.
        context = samples[-1][1]
        here = context["area"]
        best: dict[int, dict] = {}
        for rows, _ in samples:
            for row in rows:
                if "error" in row or not row.get("near"):
                    continue
                # Keep the LIVE reading of a unit in preference to its
                # corpse: a monster that died mid-probe still answers the
                # question this probe was launched to ask.
                previous = best.get(row["id"])
                if previous is None or (
                    previous.get("verdict") == "corpse"
                    and row.get("verdict") != "corpse"
                ):
                    best[row["id"]] = row
        near = list(best.values())
        hostile = [r for r in near if r.get("verdict") == "HOSTILE"]
        ally = [r for r in near if r.get("verdict") == "ALLY"]
        corpse = [r for r in near if r.get("verdict") == "corpse"]
        wrong_level = [
            r for r in hostile
            if r.get("level") is not None and r["level"] != here
        ]
        no_level = [r for r in hostile if r.get("level") is None]
        no_align = [r for r in hostile if not r.get("align_present")]
        # Which phantoms persisted across every sample? A stable id is a
        # different problem from a flickering one.
        ids = [
            {r["id"] for r in s[0] if r.get("verdict") == "HOSTILE" and r.get("near")}
            for s in samples
        ]
        persistent = set.intersection(*ids) if ids else set()

        print("\n=== VERDICT ===", flush=True)
        findings = [
            f"in area {here} ({context['area_name']}): "
            f"{len(hostile)} hostile, {len(ally)} ally, {len(corpse)} corpse "
            f"(within 80 subtiles)",
            f"hostiles persisting across all {SAMPLES} samples: "
            f"{sorted(persistent) or 'none'}",
            f"hostiles in a DIFFERENT level than the player: {len(wrong_level)}"
            + (f" -> {[r['id'] for r in wrong_level]}" if wrong_level else ""),
            f"hostiles whose room chain is unreadable: {len(no_level)}"
            + (f" -> {[r['id'] for r in no_level]}" if no_level else ""),
            f"hostiles MISSING the alignment stat entirely: {len(no_align)}"
            + (f" -> {[r['id'] for r in no_align]}" if no_align else ""),
            f"hostiles WITH the alignment stat: {len(hostile) - len(no_align)}"
            + (
                f" -> values {sorted({r['align'] for r in hostile if r['align_present']})}"
                if len(hostile) - len(no_align) else ""
            ),
            f"hostile kinds seen: {sorted({r['kind'] for r in hostile})}",
            # THE question this second census exists to answer: do real
            # monsters carry stat 172? If they do, "absent means unknown,
            # never attack" is exact. If they do not, that rule would
            # make the bot pacifist and the discriminator must come from
            # somewhere else entirely.
            "stat counts by verdict: "
            + f"hostile {sorted(r['stat_count'] for r in hostile)}, "
            + f"ally {sorted(r['stat_count'] for r in ally)}",
        ]
        for line in findings:
            print(f"  {line}", flush=True)

        return "; ".join(findings)

    return drill, body


if __name__ == "__main__":
    status = run_drill(*make_drill(), run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
