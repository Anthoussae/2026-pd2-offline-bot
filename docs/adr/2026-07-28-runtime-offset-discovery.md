# Discover the UI-state array by parsing the game's code, not by hardcoding it

- **Status:** accepted
- **Date:** 2026-07-28
- **Context:** M2/P2 of `docs/plans/2026-07-28-m2-perception-core/`

## Context

The bot must know which UI panel is open before it sends any input. This
is not a nicety: during M1 a test click was delivered while the in-game
ESC menu happened to be open and it activated **"Save and Exit Game"**. A
screen coordinate means whatever the currently-open panel says it means.

PD2's own maphack (BH) exposes UI state only through a *function*,
`GetUiVar_I`, because BH runs inside the game and can call it. From
outside the process we cannot call anything — we need the data the
function reads, and BH documents no address for it.

## Decision

Locate the array **at runtime by reading the function's own machine
code**. `GetUiVar_I` is 44 bytes:

```
+00: 83 F8 26            cmp eax, 0x26           ; bounds check, 38 slots
+03: 72 1F               jb  +0x24
      ...                                        ; assert path
+24: 8B 04 85 <abs32>    mov eax, [eax*4+abs32]  ; the array
+2B: C3                  ret
```

`uistate.find_ui_array()` scans for the indexed-load encoding and takes
the absolute address out of it, then refuses to trust the result unless
it passes two checks: the address lies inside D2Client's module range,
and its `UI_AUTOMAP` slot coincides with `AutomapOn`, which BH documents
*separately* (D2Ptrs.h:185). The second check is the strong one — two
unrelated facts from BH agreeing is good evidence we found the right
array, and it was later confirmed empirically when that slot toggled in
lockstep with the automap key.

## Alternatives considered

- **Hardcode the address** found by a one-off differential scan (compare
  memory with a menu open and closed). Simpler, and it was the documented
  fallback. Rejected as the primary approach because the address then
  silently rots at the next patch: the bot would keep reading *something*
  and quietly draw wrong conclusions about whether it may act — the
  failure mode this whole subsystem exists to prevent.
- **Infer UI state from proxy signals** (e.g. other observable state that
  correlates with a menu being up). Rejected: indirect, and wrong
  inferences here have destructive consequences.
- **Give up on UI state and gate input on the window being focused
  only.** Rejected outright — that is precisely the M1 configuration that
  saved-and-exited the user's game.

## Consequences

- **Seasonal resilience.** A patch that relocates the array is picked up
  automatically, because the address is re-derived on every run from
  whatever the current binary actually does.
- **A new failure mode, deliberately chosen.** If the compiler ever emits
  a different instruction shape, discovery *fails loudly*
  (`UIArrayNotFound`) rather than returning a stale address. Loud failure
  is the correct behaviour for a safety check; the fallback differential
  scan is documented in the phase file.
- **The technique generalises.** Where BH exposes a function but no
  variable, the same approach applies. It is worth reaching for only when
  the value is safety-relevant, as this one is — routine struct fields
  need no such machinery.
- **The array is not uniform**, which no amount of code-reading would
  have revealed: several slots are always-on flags rather than panel
  indicators. That was settled by live calibration and is recorded in a
  table in `pd2bot/uistate.py`.

*(2026-08-09: module paths above predate the package restructure; see
docs/adr/2026-08-09-package-layout.md for the current layout.)*
