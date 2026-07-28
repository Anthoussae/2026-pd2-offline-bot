"""M1 spike: out-of-process perception + synthetic input vs the live PD2 client.

This is the consolidated result of the M1 probes (probe_*.py are the raw
step-by-step versions kept for the record). Spike-quality: hardcoded offsets,
minimal abstraction. The real perception module is M2's job.

MUST RUN AS ADMINISTRATOR — PD2's Game.exe runs elevated, so OpenProcess from
an unelevated process is denied.

Usage:
  python m1_spike.py read           # print player state at ~10 Hz
  python m1_spike.py click X Y      # click screen (X, Y) — see the WARNING below

WARNING (learned the hard way, see spike-log.md): a click means whatever the
currently-open UI panel says it means. One test click landed on "Save and Exit
Game" because the ESC menu was open. A readable UI-state indicator
(BH Constants.h:65-89 defines UI_GAME=0x00, UI_ESCMENU_MAIN=0x09, ...) is an M2
task; until it exists, do not send input unattended.

Offsets from Project-Diablo-2/BH @ main, fetched 2026-07-28, all verified live:
  D2Ptrs.h:235    PlayerUnit ptr, D2Client-relative, 1.13c slot = 0x11BBFC
  D2Structs.h:690 UnitAny   (pPlayerData 0x14, dwAct 0x18, pPath 0x2C, pStats 0x5C)
  D2Structs.h:213 PlayerData(szName char[16] @ 0x00)
  D2Structs.h:396 Path      (xPos WORD 0x02, yPos WORD 0x06)
  D2Structs.h:435 StatList  (base pStat 0x24/count 0x28; FULL pSetStat 0x48/count 0x4C)
"""

import ctypes
import struct
import sys
import time
from ctypes import wintypes

import pymem
import pymem.process

PLAYER_UNIT_PTR = 0x11BBFC
OFF_PLAYERDATA, OFF_ACT, OFF_PATH, OFF_STATS = 0x14, 0x18, 0x2C, 0x5C
PATH_X, PATH_Y = 0x02, 0x06
# Read the FULL list, not the base one: the base list holds stats before item and
# skill bonuses, which yields nonsense like current-HP > max-HP.
FULL_STATS_ARRAY, FULL_STATS_COUNT = 0x48, 0x4C

STAT_HP, STAT_MAXHP, STAT_MANA, STAT_MAXMANA, STAT_LEVEL = 6, 7, 8, 9, 12
# HP/mana/stamina are stored fixed-point (>>8); level, attributes, gold are not.
FIXED_POINT = {6, 7, 8, 9, 10, 11}


def attach():
    try:
        pm = pymem.Pymem("Game.exe")
    except pymem.exception.CouldNotOpenProcess:
        sys.exit("Could not open Game.exe — run this as Administrator (PD2 runs elevated).")
    base = next((m.lpBaseOfDll for m in pymem.process.enum_process_module(pm.process_handle)
                 if (m.name if isinstance(m.name, str) else m.name.decode()).lower()
                 == "d2client.dll"), None)
    if base is None:
        sys.exit("D2Client.dll not found in Game.exe.")
    return pm, base


def read_stats(pm, punit):
    pstats = pm.read_uint(punit + OFF_STATS)
    if not pstats:
        return {}
    arr = pm.read_uint(pstats + FULL_STATS_ARRAY)
    count = pm.read_ushort(pstats + FULL_STATS_COUNT)
    stats = {}
    if arr and count <= 256:
        for i in range(count):
            _sub, idx, val = struct.unpack("<HHI", pm.read_bytes(arr + i * 8, 8))
            stats[idx] = val >> 8 if idx in FIXED_POINT else val
    return stats


def read_state(pm, base):
    """Returns None when not in a game (player unit is NULL in the menus)."""
    punit = pm.read_uint(base + PLAYER_UNIT_PTR)
    if not punit:
        return None
    pdata = pm.read_uint(punit + OFF_PLAYERDATA)
    ppath = pm.read_uint(punit + OFF_PATH)
    stats = read_stats(pm, punit)
    return {
        "name": pm.read_bytes(pdata, 16).split(b"\x00")[0].decode("ascii", "replace"),
        "level": stats.get(STAT_LEVEL),
        "act": pm.read_uint(punit + OFF_ACT) + 1,
        "pos": (pm.read_ushort(ppath + PATH_X), pm.read_ushort(ppath + PATH_Y)),
        "hp": (stats.get(STAT_HP), stats.get(STAT_MAXHP)),
        "mana": (stats.get(STAT_MANA), stats.get(STAT_MAXMANA)),
    }


def game_window(pm):
    user32 = ctypes.windll.user32
    found = []

    def cb(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == pm.process_id and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(cb), 0)
    return found[0] if found else None


def cmd_read(pm, base):
    print("Reading at ~10 Hz. Ctrl+C to stop.")
    last = None
    while True:
        s = read_state(pm, base)
        line = "not in a game (menus)" if s is None else (
            f"{s['name']} lvl {s['level']} act {s['act']} pos={s['pos']} "
            f"hp={s['hp'][0]}/{s['hp'][1]} mana={s['mana'][0]}/{s['mana'][1]}")
        if line != last:
            print(f"[{time.strftime('%H:%M:%S')}] {line}")
            last = line
        time.sleep(0.1)


def cmd_click(pm, base, tx, ty):
    user32 = ctypes.windll.user32
    if read_state(pm, base) is None:
        sys.exit("Not in a game — refusing to click.")
    hwnd = game_window(pm)
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(1.0)
    if user32.GetForegroundWindow() != hwnd:
        sys.exit("Game window is not in the foreground — refusing to click.")

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                    ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("mi", MOUSEINPUT)]

    def send(flags):
        inp = INPUT(type=0, mi=MOUSEINPUT(0, 0, 0, flags, 0, None))
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    before = read_state(pm, base)["pos"]
    user32.SetCursorPos(tx, ty)
    time.sleep(0.2)
    send(0x0002)  # left down
    time.sleep(0.06)
    send(0x0004)  # left up

    last = before
    for _ in range(30):
        time.sleep(0.1)
        p = read_state(pm, base)["pos"]
        if p != last:
            print(f"  pos={p}")
            last = p
    print(f"{before} -> {last}  moved={'YES' if last != before else 'no'}")


if __name__ == "__main__":
    pm, base = attach()
    if len(sys.argv) >= 2 and sys.argv[1] == "read":
        cmd_read(pm, base)
    elif len(sys.argv) >= 4 and sys.argv[1] == "click":
        cmd_click(pm, base, int(sys.argv[2]), int(sys.argv[3]))
    else:
        print(__doc__)
        sys.exit(1)
