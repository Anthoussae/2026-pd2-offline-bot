"""Throwaway probe: sample player state for N seconds, print distinct values."""

import struct
import sys
import time

import pymem
import pymem.process

PLAYER_UNIT_PTR = 0x11BBFC
OFF_PLAYERDATA, OFF_ACT, OFF_PATH, OFF_STATS = 0x14, 0x18, 0x2C, 0x5C
PATH_X, PATH_Y = 0x02, 0x06
STATS_ARRAY, STATS_COUNT = 0x24, 0x28

seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0

pm = pymem.Pymem("Game.exe")
base = None
for m in pymem.process.enum_process_module(pm.process_handle):
    name = m.name if isinstance(m.name, str) else m.name.decode(errors="replace")
    if name.lower() == "d2client.dll":
        base = m.lpBaseOfDll
        break
print(f"D2Client.dll base = 0x{base:08X}")

seen = []
end = time.time() + seconds
while time.time() < end:
    punit = pm.read_uint(base + PLAYER_UNIT_PTR)
    if not punit:
        line = "player unit = NULL (in menus / not in game)"
    else:
        pdata = pm.read_uint(punit + OFF_PLAYERDATA)
        name = pm.read_bytes(pdata, 16).split(b"\x00")[0].decode("ascii", "replace")
        ppath = pm.read_uint(punit + OFF_PATH)
        x, y = pm.read_ushort(ppath + PATH_X), pm.read_ushort(ppath + PATH_Y)
        act = pm.read_uint(punit + OFF_ACT) + 1
        stats = {}
        pstats = pm.read_uint(punit + OFF_STATS)
        if pstats:
            arr, cnt = pm.read_uint(pstats + STATS_ARRAY), pm.read_ushort(pstats + STATS_COUNT)
            for i in range(min(cnt, 128)):
                _sub, idx, val = struct.unpack("<HHI", pm.read_bytes(arr + i * 8, 8))
                stats[idx] = val
        line = (f"name={name!r} lvl={stats.get(12)} act={act} pos=({x},{y}) "
                f"hp={stats.get(6, 0) >> 8}/{stats.get(7, 0) >> 8} "
                f"mana={stats.get(8, 0) >> 8}/{stats.get(9, 0) >> 8}")
    if not seen or seen[-1] != line:
        print(f"[{time.strftime('%H:%M:%S')}] {line}")
        seen.append(line)
    time.sleep(0.1)

print(f"-- {len(seen)} distinct states over {seconds}s --")
