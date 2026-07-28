"""Throwaway probe: locate the PD2 game window and report its geometry."""

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
PID = None

import pymem
pm = pymem.Pymem("Game.exe")
PID = pm.process_id

results = []


def cb(hwnd, _):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == PID and user32.IsWindowVisible(hwnd):
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        client = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(client))
        pt = wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        results.append((hwnd, buf.value, rect, client, pt))
    return True


WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
user32.EnumWindows(WNDENUMPROC(cb), 0)

for hwnd, title, rect, client, pt in results:
    print(f"hwnd=0x{hwnd:X} title={title!r}")
    print(f"  window rect: ({rect.left},{rect.top})-({rect.right},{rect.bottom})")
    print(f"  client size: {client.right}x{client.bottom}  client origin on screen: ({pt.x},{pt.y})")
    print(f"  client center on screen: ({pt.x + client.right // 2}, {pt.y + client.bottom // 2})")
print(f"foreground hwnd = 0x{user32.GetForegroundWindow():X}")
