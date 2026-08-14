"""Not dying: the per-tick safety monitor and the independent watchdog.

monitor.py owns the chicken thresholds, the death latch, and
SafetyInterrupt; watchdog.py is the separate elevated process that can
press ESC even if the bot hangs. See
docs/adr/2026-08-07-unstarvable-safety.md.
"""

from pd2bot.safety.monitor import (
    ChickenExit,
    DeathHalt,
    SafetyConfig,
    SafetyInterrupt,
    SafetyMonitor,
    Verdict,
)

__all__ = [
    "ChickenExit",
    "DeathHalt",
    "SafetyConfig",
    "SafetyInterrupt",
    "SafetyMonitor",
    "Verdict",
]
