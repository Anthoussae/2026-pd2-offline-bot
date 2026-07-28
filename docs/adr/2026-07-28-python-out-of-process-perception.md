# Python + out-of-process memory reading for PD2 perception

- **Status:** accepted
- **Date:** 2026-07-28
- **Context:** M1 of `docs/plans/2026-07-28-bot-from-scratch/`

## Context

We need a bot that can perceive and act on a running Project Diablo 2
client (a mod of Diablo II 1.13c, 32-bit, Windows). Diablo II exposes no
API, no IPC, no scripting interface, and no live machine-readable state
export; offline single-player generates no network traffic to observe,
and the save file is written only on exit. The available perception
surfaces are therefore:

1. the client's process memory (its own C structs),
2. the rendered screen (pixels/OCR),
3. in-process injection (a DLL inside the game, e.g. D2BS/kolbot).

Option 3 was attempted first via kolbot and failed outright: kolbot
supports only D2 1.13d/1.14d, PD2 is 1.13c, and the community bridge
(pd2bs) is publicly dead — see
`docs/archive/plans/2026-07-28-pd2-offline-bot/spike-log.md`.

## Decision

Perceive by **out-of-process memory reading** (`ReadProcessMemory` via
pymem) and act by **OS-level synthetic input** (`SendInput`), written in
**Python**.

Memory-structure offsets are derived from **Project-Diablo-2/BH**, the
mod team's own open-source maphack, which pins the structures for the
exact client we target and is maintained alongside the mod.

## Alternatives considered

- **Pixel/OCR perception** — no version-coupling, but brittle to
  resolution, UI, lighting and animation, and it cannot see quantities
  the UI does not draw. Rejected.
- **DLL injection** — the richest access (kolbot's approach) and it
  could call the game's own functions rather than inferring state, but
  it means shipping a C++ payload into a client we do not control, it
  is what already failed for PD2, and it is a much harsher debugging
  environment. Rejected.
- **C# instead of Python** — best Win32 affinity and prior art
  (D2SharpMemory, DiabloInterface), but those references are stale and
  the iteration loop is slower. **Go** — koolo precedent, but the
  learning spend goes to the language rather than to botting concepts.
  Both rejected: the workload is I/O-bound (read → decide → act at
  human-ish rates), so Python's speed disadvantage does not bind, and
  this project is explicitly a learning exercise.

## Consequences

- **Validated in M1** against the live Season 13 client: correct reads
  of name/level/act/position/stats, position tracked at 10 Hz during
  movement, and a synthetic click moved the character.
- **The bot must run as Administrator**: PD2's client runs elevated, so
  `OpenProcess` from an unelevated process is denied. This goes in the
  manual and should produce a friendly startup error.
- **Seasonal maintenance cost**: memory layouts are not a contract.
  Patches can move them; re-verify offsets against BH each season. Every
  derived offset is cited back to its BH source line for exactly this.
- **Perception is inference, not truth**: values must be validated
  semantically, not just structurally. M1 read a *structurally correct*
  but *semantically wrong* max-HP (D2 keeps base and fully-computed stat
  arrays separately) — the kind of error only a reality check catches.
- **Input is the dangerous half.** Reads are passive; writes are not.
  A click means whatever the open UI panel says it means (an M1 test
  click hit "Save and Exit Game" because the ESC menu was open), so
  input must be gated on window-foreground **and** UI state **and**
  in-game status.
- We forgo the ability to call game functions directly; anything the
  client does not keep in readable memory must be derived another way
  (e.g. map collision comes from seed-based offline generation).
