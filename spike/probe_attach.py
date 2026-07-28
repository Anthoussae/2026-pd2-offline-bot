"""Throwaway probe: can we attach to the 32-bit PD2 client and see its modules?"""

import sys

import pymem
import pymem.process

pm = pymem.Pymem("Game.exe")
print("attached pid:", pm.process_id)
print("python:", sys.version.split()[0], "64-bit" if sys.maxsize > 2**32 else "32-bit")

mods = list(pymem.process.enum_process_module(pm.process_handle))
print("modules found:", len(mods))
for m in mods:
    name = m.name if isinstance(m.name, str) else m.name.decode(errors="replace")
    if name.lower() in ("game.exe", "d2client.dll", "d2common.dll", "d2game.dll",
                        "bh.dll", "projectdiablo.dll", "pd2_ext.dll"):
        print(f"  {name:24s} base=0x{m.lpBaseOfDll:08X} size={m.SizeOfImage}")
