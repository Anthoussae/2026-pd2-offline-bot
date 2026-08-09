# safety/ — not dying

Two independent layers; each covers what the other cannot (defence in
depth, ADR 2026-08-07-unstarvable-safety).

| file | one job |
|---|---|
| monitor.py | in-process per-tick monitor: chicken thresholds, the death latch, SafetyInterrupt (a BaseException no `except Exception` can swallow), the heartbeat check |
| watchdog.py | a SEPARATE elevated process that reads vitals itself and presses ESC; dead-man heartbeat; the launcher refuses to run without it |

Invariants (contractual, CLAUDE.md): after a detected death the bot
sends no input of any kind, permanently; nothing may starve the monitor
— blocking calls poll safety and are bounded.
