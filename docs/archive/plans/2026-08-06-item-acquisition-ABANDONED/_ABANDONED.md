# ABANDONED — 2026-08-06

The operator ended this direction: *"rewind the branch. Let's abandon
this direction, and return to the main, without using dll injections
etc."*

## What was abandoned

The plan's **Track 2 — command-by-GID pickup** (the frame-perfect path).
It required a NEW capability the project has never had — out-of-process
**memory writes** / a remote call to PD2's own pickup handler
(`CreateRemoteThread` or writing into the client's packet buffer). The
operator declined that class of technique outright ("no DLL injections
etc."). **The project stays out-of-process, read-only + `SendInput`**, as
the accepted ADR `2026-07-28-python-out-of-process-perception` has it.
`memory.py` remains read-only.

## What was tried and reverted

An `item-acquisition-spike` branch (off `m6-countess`, tagged
`stable-pre-acquisition` = the rewind anchor) held:

- `pd2bot/acquire.py` — an `Actuator` seam (`ClickActuator`) so the
  pickup *mechanism* was swappable. Live-proven harmless (T78: 4/4 junk
  lifted, 1043 tests green), but only useful as the insertion point for
  the abandoned command actuator.
- `drills/t78_acquire.py`, `t79_label_state.py` — the acquisition and
  label-state experiments.

All reverted by checking out `m6-countess` (the stable line). The branch
is retained on the remote as an archived record; none of it is on main.

## What was learned, and is worth keeping

- **kolbot's fast pickup is a `0x16 PickupItem` command by GID, not a
  screen click** (`notes.md`). That is why it is frame-perfect — and why
  it is unreachable without the write capability now off the table.
- **The click path is erratic** (T76/T79): a dense pile's pick rate
  swings 1/8–8/8 on noise; the "labels-OFF fixes piles" lead did NOT
  replicate under control. Do not re-chase it.
- The **detection vs acquisition** framing and the measured pickup costs
  (baseline 18/31, 12 s per failed item) are real and still true.

## Where pickup work goes now

Within the SendInput constraint, via the still-active
`docs/plans/2026-08-06-pickup-reliability/` plan — instrumentation (done:
`item.abandoned`, `runlog --pickup`), the item-exception registry
(scrolls/maps/quest items — non-injection safety work), and any
click-path tuning the operator wants. No memory-write actuation.
