"""Throwaway probe: bring the PD2 window to the front and hold, sending no input."""

import ctypes
import time
from ctypes import wintypes

import pymem

user32 = ctypes.windll.user32
pm = pymem.Pymem("Game.exe")
hwnds = []


def cb(hwnd, _):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == pm.process_id and user32.IsWindowVisible(hwnd):
        hwnds.append(hwnd)
    return True


user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(cb), 0)
hwnd = hwnds[0]
user32.ShowWindow(hwnd, 9)
user32.SetForegroundWindow(hwnd)
time.sleep(0.5)
print("foreground ok:", user32.GetForegroundWindow() == hwnd)
time.sleep(6)
