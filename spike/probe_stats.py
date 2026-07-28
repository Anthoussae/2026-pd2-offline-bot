"""Throwaway probe: compare D2's two stat lists, and sample position (no input sent).

StatList (D2Structs.h:435) exposes two arrays:
  pStat      @0x24 / wStatCount1 @0x28  -- base stats
  pSetStat   @0x48 / wSetStatCount @0x4C -- the merged/full list (item + skill bonuses)
Which one holds the HP the game actually displays is the question.
"""

import struct
import time

import pymem
import pymem.process

PLAYER_UNIT_PTR = 0x11BBFC
OFF_PLAYERDATA, OFF_PATH, OFF_STATS = 0x14, 0x2C, 0x5C
PATH_X, PATH_Y = 0x02, 0x06
BASE_ARR, BASE_CNT = 0x24, 0x28
FULL_ARR, FULL_CNT = 0x48, 0x4C

NAMES = {0: "strength", 1: "energy", 2: "dexterity", 3: "vitality", 6: "hitpoints",
         7: "maxhp", 8: "mana", 9: "maxmana", 10: "stamina", 11: "maxstamina",
         12: "level", 13: "experience", 14: "gold", 15: "goldbank"}

pm = pymem.Pymem("Game.exe")
base = next(m.lpBaseOfDll for m in pymem.process.enum_process_module(pm.process_handle)
            if (m.name if isinstance(m.name, str) else m.name.decode()).lower() == "d2client.dll")

punit = pm.read_uint(base + PLAYER_UNIT_PTR)
if not punit:
    raise SystemExit("player unit NULL — not in a game")

pdata = pm.read_uint(punit + OFF_PLAYERDATA)
print("character:", pm.read_bytes(pdata, 16).split(b"\x00")[0].decode("ascii", "replace"))

pstats = pm.read_uint(punit + OFF_STATS)


def dump(label, arr_off, cnt_off, cnt_is_word=True):
    arr = pm.read_uint(pstats + arr_off)
    cnt = pm.read_ushort(pstats + cnt_off) if cnt_is_word else pm.read_uint(pstats + cnt_off)
    print(f"\n--- {label}: array=0x{arr:08X} count={cnt} ---")
    if not arr or cnt > 256:
        print("  (implausible; skipping)")
        return {}
    out = {}
    for i in range(cnt):
        sub, idx, val = struct.unpack("<HHI", pm.read_bytes(arr + i * 8, 8))
        out[idx] = val
        if idx in NAMES:
            print(f"  {NAMES[idx]:12s} (stat {idx:3d}) raw={val:<12d} >>8={val >> 8}")
    return out


b = dump("BASE  pStat/wStatCount1", BASE_ARR, BASE_CNT)
f = dump("FULL  pSetStat/wSetStatCount", FULL_ARR, FULL_CNT)

print("\n=== HP/mana comparison ===")
for src, d in (("base", b), ("full", f)):
    if d:
        print(f"  {src}: hp={d.get(6, 0) >> 8}/{d.get(7, 0) >> 8}  "
              f"mana={d.get(8, 0) >> 8}/{d.get(9, 0) >> 8}")

print("\n=== position sampling, 8s (walk around; no input is sent) ===")
seen = None
for _ in range(80):
    ppath = pm.read_uint(pm.read_uint(base + PLAYER_UNIT_PTR) + OFF_PATH)
    p = (pm.read_ushort(ppath + PATH_X), pm.read_ushort(ppath + PATH_Y))
    if p != seen:
        print(f"  [{time.strftime('%H:%M:%S')}] pos={p}")
        seen = p
    time.sleep(0.1)
