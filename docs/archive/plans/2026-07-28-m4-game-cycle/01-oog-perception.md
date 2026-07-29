# P1 — OOG perception: reading the menus from memory

Part of [M4 game cycle](plan.md). Size: `sm`. Depends on: nothing.
Can run in parallel with P2.

## Scope

When not in a game, the player unit is null and the in-game UI array
means nothing — the bot currently knows *that* it is at the menus, not
*which screen*. This phase gives it eyes out of game:

1. An offsets block for the **D2Win control list** (D2's menus are a
   linked list of controls — buttons/textboxes with type, position,
   size, and for buttons usually text).
2. `pd2bot/oog.py`: walk the list, model controls, classify the
   current screen.
3. `world.read_difficulty(session)`: the one-byte difficulty read
   (consumed by P3's post-join guard; 0=Normal, 1=Nightmare, 2=Hell).
4. `python -m pd2bot.oog`: a dump CLI for live calibration — prints
   the control table and the screen classification.

Out of scope: sending any input (P2), driving any transition (P3).

## Where the offsets come from

BH is in-game-only and will likely not carry OOG pointers. Use the
same lineages already cited for the CollMap block in
`pd2bot/offsets.py` (see that file's header and the CollMap section
for the citation style): **D2BS engine source** (its OOG layer is
exactly this feature) and a second independent community source
(D2Warden headers / 1.13c address tables, e.g. the
Diablo-II-Address-Table repo noted in the roadmap notes). Rules,
per established convention:

- Every constant cites source file + line. Two independent lineages
  must agree, or the disagreement is documented and resolved live.
- 1.13c values only (PD2's client). Do not trust my (the planner's)
  memory of any address — fetch and cite.
- The control struct fields needed: next pointer, type, x, y, width,
  height, and the text field(s). Note D2's menu coordinate system in a
  comment once discovered (top-left origin of the 800×600 render area
  is expected; verify against the dump).

⚠ **Render-vs-window scaling**: M3 measured that PD2 draws at a
smaller resolution and upscales (20/10 px per subtile instead of
16/8 — see `docs/architecture/navigation.md`). Control coordinates
are in *render* space; clicking them (P2/P3) must project through the
same window-scale factor. In this phase, just record both raw and
projected coordinates in the dump so the scale question is answered by
data before P2 needs it.

## Screen classification

`oog.py` returns a `Screen` enum + the raw controls. Classify by
control fingerprint (count/types/geometry, text where readable):

- `MAIN_MENU` (has Single Player button)
- `CHAR_SELECT` (character list + OK / Exit)
- `DIFFICULTY` (the popup: Normal / Nightmare / Hell buttons)
- `ERROR_POPUP` (centered OK — kolbot's `OkCenteredErrorPopUp`)
- `LOADING` / `UNKNOWN` (anything unrecognized — never guess)

Prefer text matching when control text reads cleanly; fall back to
geometry fingerprints if text is encoded awkwardly. Kolbot's
`libs/OOG.js` + `sdk` locations/controls are the behavioral reference
for which controls exist per screen (reference only — never edit
`kolbot/`).

If a screen is ambiguous, return `UNKNOWN` — P3 treats `UNKNOWN` as
"stop and describe", and a wrong confident answer is worse than an
honest shrug.

## The fallback decision (pre-approved R27/Q1)

PD2 modifies the client (SGD2FreeRes renderer); the control list is
*probably* stock but must be proven. First live check: dump at the
char select screen. If the list is unreadable or nonsense, switch to
the **blind fallback**: a `MenuScreens` interface whose blind
implementation infers state only from `is_in_game` + elapsed
time + fixed click coordinates (P2/P3 consume the interface either
way). Report which strategy landed at phase end; if blind, note in the
report that P3's difficulty guard is then the *only* wrong-difficulty
protection (it is unconditional anyway).

## Live verification (user request protocol)

🔶 requests, IDs continuing from `docs/instruction-log.md` (next:
R30); elevated terminal, human present. Expected checks:

1. Dump at char select (the state after save-and-exit) — controls
   sane, classification correct.
2. Dump at the difficulty popup, main menu, and (if reachable) an
   error popup — user navigates, agent reads.
3. `read_difficulty` in a Hell game → 2 (compare against the game).

Log every request + outcome in the instruction log as you go.

## Conventions (from the repo)

- Module docstring explains *why the module exists* with the narrative
  style of `uistate.py`/`input.py`.
- No magic offsets outside `offsets.py`; mark values "verified live"
  once they are.
- Reads return `None`/`UNKNOWN` on null pointers or failed sanity
  checks — never raise for a normal mid-transition state, never return
  garbage. Sanity-check the walked list (bounded length, coordinates
  within the render area) before trusting it.
- Tests: fake memory buffers (see `tests/` for the pattern); pytest
  must never require the game.
- Lint: `python -m ruff check .` clean.

## Validation

- `python -m pytest -q` (existing 121 + new tests pass).
- `python -m ruff check .`.
- Live checks above.

## Agent reminders

- Do not commit unless the user asked.
- Do not expand scope; no input-sending in this phase.
- Do not suppress warnings or disable tests.
- Stop and report if blocked or if reality contradicts the design
  (e.g. control list unreadable → fallback decision is pre-approved,
  but *report* it).
- Report what changed, what was validated, and any deviations.

## Definition of done

`oog.py` classifies all four named screens correctly against the live
client (or the fallback is in place and reported); `read_difficulty`
verified live; dump CLI exists; offsets dual-cited; tests + lint
green; instruction log updated.

## Implementation Result

Status: done
Completed: 2026-07-28
Commit: pending

- Changed: `pd2bot/oog.py` (new — control-list walk, MenuControl,
  Screen classification by kolbot-mined fingerprints, dump CLI),
  `pd2bot/offsets.py` (D2Win section: FIRST_CONTROL BH D2Ptrs.h:624,
  Control struct BH CommonStructs.h:567-585 × d2bs D2Structs.h:132-168,
  button text 0x64 CommonStructs.h:665; GetDifficulty D2Ptrs.h:152 +
  difficulty constants), `pd2bot/world.py` (`read_difficulty` via
  GetDifficulty code-parse, dual-encoding, module-bounds sanity),
  `pd2bot/memory.py` (lazy D2Win base + `wstring`), tests
  (`test_oog.py`, `test_world.py`, conftest additions).
- Validated: 143 tests pass; ruff clean. Live (bridge 006/008/011):
  char select dump exact vs kolbot table incl. state semantics
  (disabled button = 4); difficulty=2 in a Hell game; full transition
  walk classified with zero unknowns; `in_game` stable through
  waypoint travel, combat, and focus changes.
- Deviations: (1) **save-and-exit lands at MAIN MENU** in offline SP,
  not char select — live-found (user), P3 must expect it. (2)
  ERROR_POPUP could not be safely triggered live; its fingerprint is
  kolbot-sourced + unit-tested only. (3) The control list proved fully
  stock under PD2 — the blind fallback was never built (pre-approved
  either way; interface seam remains via fingerprint constants).
- The menu render-vs-window scale question is *deferred to P2's click
  test* as planned: P1's dump shows menu space is 800x600 as expected;
  the projection hypothesis (scale by client-rect ratio) gets proven
  by clicking.
