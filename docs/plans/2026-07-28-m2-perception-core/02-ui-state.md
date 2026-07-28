# P2 — UI and game-state detection

**Work item:** P2 · **Size:** sm · **Depends on:** P1 ·
**Blocks:** all input work in M3/M4 · **Review gate: YES**

## Why this phase exists

M1 sent a test click while the ESC menu happened to be open; it landed
on **"Save and Exit Game"**. The same screen coordinate means different
things depending on which panel is open, so **no input may ever be sent
without knowing the UI state**. This phase is the prerequisite for the
bot being allowed to act at all.

## Scope

Expose two things from `pd2bot/uistate.py`:

- `is_in_game(session) -> bool` — player unit non-NULL. Already proven
  in M1; trivial, but belongs here as part of the same guard surface.
- `ui_state(session) -> dict[int, bool]` (or a small dataclass) — which
  UI panels are currently open, keyed by BH's enum.

Plus a `can_act(session) -> bool` convenience: in a game **and** no
blocking panel open. M3's input layer will call this, and additionally
require window-foreground.

## The open problem, and the approach

BH `Constants.h:65-89` defines the enum (`UI_GAME 0x00`,
`UI_INVENTORY 0x01`, `UI_ESCMENU_MAIN 0x09`, `UI_NPCSHOP 0x0C`,
`UI_WPMENU 0x14`, …). But `D2Ptrs.h:156` exposes only a *function*,
`GetUiVar_I` at `D2Client+0xBE400` (1.13c slot) — BH runs in-process and
calls it. Out-of-process we must find the data it reads.

**Primary approach — parse the function's own code.** Read the
instruction bytes at `D2Client + 0xBE400` and extract the array base
address from the indexed-load instruction (expect something of the shape
`mov al, [ecx + <abs32>]` / `movzx eax, byte ptr [ecx*1 + <abs32>]`).
Then `ui_state[i] = read_u8(array + i)`.

This is deliberately chosen over hardcoding: the address is *derived at
runtime*, so a patch that moves the array is picked up automatically
rather than silently returning garbage. Implement it as: dump ~64 bytes,
locate the load, extract the little-endian absolute address, then
**sanity-check** the result (address inside D2Client's module range;
`UI_GAME` reads as expected while in a game).

**Fallback — differential scan.** If the instruction shape is not
recognisable, find the address empirically: read candidate memory with
the ESC menu closed, then open, and diff. This needs the user to toggle
the menu on cue. It yields a hardcoded address requiring re-discovery
each season — acceptable as a fallback, and useful anyway as an
independent cross-check of whatever the code-parse finds.

**If both fail: stop and report.** Do not ship a heuristic guess. A
wrong UI-state read is precisely what causes another destructive click.

## Out of scope

- Sending any input, or acting on the UI state (M3+).
- Enumerating or interacting with menu contents, NPC dialogue trees,
  shop inventories (M4 territory).
- Detecting the out-of-game main-menu screens specifically (M4 needs
  this for game creation; here, "not in a game" suffices).

## Files

- New: `pd2bot/uistate.py`, `tests/test_uistate.py`.
- Updated: `pd2bot/offsets.py` (the `GetUiVar_I` function offset, the
  UI enum, and — if the fallback is used — the discovered array address
  with a loud comment that it is season-specific).

## Validation

- `pytest`: the byte-parsing logic tested against recorded instruction
  bytes committed as a fixture (capture them during development), so the
  parser is testable without a running game.
- **Live, with the user**: verify the state readback in at least these
  situations — in town with nothing open; inventory open; ESC menu open;
  a shop/NPC screen open; and at the main menu (not in a game). Record
  the observed values per situation in the Implementation Result.
- `ruff check` passes.

## ADR expectation

**Likely.** If the runtime code-parse works, write
`docs/adr/YYYY-MM-DD-runtime-offset-discovery.md`: deriving addresses by
reading the game's own instructions rather than hardcoding them, why
(seasonal resilience), the risk (instruction shape changes), and the
fallback.

## Review gate — stop at the end of this phase

Report to the user:

1. Which discovery method worked, and the address found.
2. The live verification table (situation → observed UI state).
3. Whether `can_act()` is trustworthy enough for M3's input layer to
   depend on it.

If **neither** method worked, stop and report that instead — with what
was tried and what the next options are. Do not proceed to a heuristic.

## Agent reminders

- Do not commit unless the user asked.
- Do not expand scope; this phase reads state, it does not act on it.
- **Send no input during this phase.** Live verification is done by the
  user opening and closing panels, not by the agent clicking.
- Do not hardcode an address the code-parse could derive.
- Stop and report if blocked by ambiguity or an unexpected design issue.
- Report what changed, what was validated, and any deviations.

## Definition of done

`ui_state()` and `is_in_game()` return correct values across all live
situations listed under Validation, the discovery method and its
sanity-checks are documented in code, tests pass, and the review-gate
conversation has been held.
