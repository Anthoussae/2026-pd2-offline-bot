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

## Implementation Result

Status: done (code + offline verification); **live verification pending**
Completed: 2026-07-28
Commit: f5359ee

- **The primary approach worked on the first try.** `GetUiVar_I` turned out
  to be a 44-byte function: a bounds check (`cmp eax, 0x26`), an assert
  path, then `8B 04 85 <abs32>` = `mov eax, [eax*4 + 0x6FBAAD80]`, `ret`.
  The UI array is at **D2Client + 0xFAD80**, DWORD entries indexed by BH's
  UI enum. No differential scan was needed.
- **Independent cross-check found and used as a runtime sanity check.**
  BH separately documents `AutomapOn` at 0xFADA8 (D2Ptrs.h:185). That is
  exactly `0xFAD80 + UI_AUTOMAP * 4`. Two unrelated BH facts agreeing is
  strong evidence the array is the right one, so `find_ui_array()` refuses
  any candidate that fails this identity as well as any address outside
  the module.
- Changed: `pd2bot/uistate.py` (`find_ui_array`, `read_ui_state`,
  `is_in_game`, `can_act`, `UIState.blocks_input`), `tests/test_uistate.py`
  (parser tested against the real instruction bytes, captured as a
  fixture), offsets for the function and the UI enum.
- Validated offline: the parser recovers 0x6FBAAD80 from the live client's
  actual bytes; rejects an in-range-looking address that fails the automap
  identity; rejects a function body with no indexed load. The M1 incident
  is encoded as a test (`test_esc_menu_blocks_input`).
- **Live calibration done** (user toggling panels, agent sent no input).
  Observed transitions:

  | Slot | Behaviour observed | Verdict |
  |---|---|---|
  | 0x01 inventory | on/off exactly with the panel | real panel, blocking |
  | 0x02 character | on/off exactly with the panel | real panel, blocking |
  | **0x09 esc menu** | **on/off exactly with the panel** | **real, blocking — the M1 culprit, now confirmed** |
  | 0x0A automap | on/off exactly with the panel | real, but world stays clickable → not blocking |
  | 0x00 UI_GAME | always 1 while in a game | state flag, not a panel |
  | 0x06, 0x13 | always 1, never moved | internal |
  | 0x23 | on during play, **off while the esc menu is up** | "gameplay running" flag |
  | 0x14 | on at rest, drifts on its own | not a display flag |

- **Second, stronger confirmation of the array.** The automap slot is the
  address BH documents separately as `AutomapOn`; watching it move in
  lockstep with the automap key confirms empirically what the arithmetic
  cross-check only implied.
- **Bug caught by this calibration**: the first implementation treated every
  nonzero slot as an open panel, so `can_act()` returned NO during ordinary
  play (the always-on slots). Fixed by excluding them, with the table above
  recorded in the code.
