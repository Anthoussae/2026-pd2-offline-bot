"""Out-of-process perception and control for Project Diablo 2.

The bot reads the running game client's memory (it never injects code into it)
and drives it with OS-level synthetic input. See docs/architecture/perception.md
and docs/adr/2026-07-28-python-out-of-process-perception.md.

Requires Administrator: the PD2 client runs elevated.
"""

__version__ = "0.1.0"
