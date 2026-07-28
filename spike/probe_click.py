"""Throwaway probe: synthetic click moves the character (and position reads track it).

Foregrounds the PD2 window, samples position, sends ONE left-click offset from
screen centre, then samples position for a few seconds. Aborts before clicking
if the game window is not actually in the foreground.
"""

import ctypes
import time
from ctypes import wintypes

import pymem
import pymem.process

PLAYER_UNIT_PTR = 0x11BBFC
OFF_PATH = 0x2C
PATH_X, PATH_Y = 0x02, 0x06

user32 = ctypes.windll.user32
pm = pymem.Pymem("Game.exe")

base = next(m.lpBaseOfDll for m in pymem.process.enum_process_module(pm.process_handle)
            if (m.name if isinstance(m.name, str) else m.name.decode()).lower() == "d2client.dll")


def pos():
    punit = pm.read_uint(base + PLAYER_UNIT_PTR)
    if not punit:
        return None
    ppath = pm.read_uint(punit + OFF_PATH)
    return pm.read_ushort(ppath + PATH_X), pm.read_ushort(ppath + PATH_Y)


# --- find the game window ---
hwnds = []


def cb(hwnd, _):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == pm.process_id and user32.IsWindowVisible(hwnd):
        hwnds.append(hwnd)
    return True


user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(cb), 0)
hwnd = hwnds[0]

rect = wintypes.RECT()
user32.GetClientRect(hwnd, ctypes.byref(rect))
origin = wintypes.POINT(0, 0)
user32.ClientToScreen(hwnd, ctypes.byref(origin))
cx, cy = origin.x + rect.right // 2, origin.y + rect.bottom // 2

# Target: absolute screen coords if given, else offset right of the player.
import sys
if len(sys.argv) >= 3:
    tx, ty = int(sys.argv[1]), int(sys.argv[2])
else:
    tx, ty = cx + 160, cy - 40

start_pos = pos()
print(f"before: pos={start_pos}  window centre=({cx},{cy})  click target=({tx},{ty})")

# Guard: never click unless we are actually in a game. (A click sent while the
# ESC menu was open once hit "Save and Exit Game" — see spike-log.md. A proper
# UI-state check lands in M2; this is the crude version.)
if start_pos is None:
    print("ABORT: player unit is NULL — not in a game. No click sent.")
    raise SystemExit(2)

user32.ShowWindow(hwnd, 9)  # SW_RESTORE
user32.SetForegroundWindow(hwnd)
time.sleep(1.0)

fg = user32.GetForegroundWindow()
if fg != hwnd:
    print(f"ABORT: game window not foreground (fg=0x{fg:X}, game=0x{hwnd:X}); no click sent.")
    raise SystemExit(2)

INPUT_MOUSE, LEFTDOWN, LEFTUP = 0, 0x0002, 0x0004


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("mi", MOUSEINPUT)]


def send(flags):
    inp = INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, flags, 0, None))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


user32.SetCursorPos(tx, ty)
time.sleep(0.2)
send(LEFTDOWN)
time.sleep(0.06)
send(LEFTUP)
print("click sent")

start, end = pos(), None
for _ in range(30):
    time.sleep(0.1)
    p = pos()
    if p != end:
        print(f"  pos={p}")
        end = p
print(f"after: {end}   moved={'YES' if end != start else 'no'}")
