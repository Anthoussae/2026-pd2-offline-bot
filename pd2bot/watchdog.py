"""Command shim: `python -m pd2bot.watchdog` — the machinery lives in safety/watchdog.py.

tools/guarded-run.ps1 invokes this path; keep it stable.
"""

from pd2bot.safety.watchdog import main

if __name__ == "__main__":
    raise SystemExit(main())
