# P2 — MenuInput: the second, separately-guarded send path

Part of [M4 game cycle](plan.md). Size: `sm`. Depends on: nothing
(the guard needs only existing `uistate`/`window`). Can run in
parallel with P1.

## Scope

`pd2bot/menuinput.py`: a `MenuInput` class that can click menu
buttons and press ESC — the things `GatedInput` rightly refuses
(game creation happens where `can_act()` is false, and "Save and Exit
Game" lives on a blocking panel).

Out of scope: any knowledge of *which* screen is up or *what* to click
(P1/P3); world-coordinate clicks (that is `GatedInput.click_world`'s
job, unchanged).

## The invariant this phase must not break

From CLAUDE.md and `docs/architecture/navigation.md`: M4's menu
clicking **adds its own separately-guarded method rather than weakening
`GatedInput`**. Concretely:

- `pd2bot/input.py`'s guard logic is not modified. Reusing its
  module-level SendInput primitives (`_send_mouse_flag`, `_send_key`,
  the ctypes structs) by import is fine — the *guard* is what is
  sacred, not the plumbing. If sharing gets awkward, lift the
  primitives into a tiny private helper module both import; do not
  copy-paste them.
- `MenuInput` gets no bypass flag and no unguarded variant either.
  Same philosophy: one send path per context, the guard runs at the
  moment of sending, refusal raises `InputRefused` (reuse the same
  exception — callers should not care which gate said no) with a
  message naming the failed condition.

## The menu guard

A menu click is safe when it will land in the game's window *and* the
client is in a state where a menu is what receives it. Guard, checked
at send time (mirroring `GatedInput.check`'s structure):

1. The game window is the foreground window
   (`GameWindow.is_foreground()`).
2. The click target lies inside the window's client rect (re-queried
   per send; the user may move the window).
3. **Menu context**: `not uistate.is_in_game(session)` (at the OOG
   menus) **or** the in-game ESC menu is open
   (`UI_ESCMENU_MAIN` in the open panels) **or** the player is
   dead (death screen expects ESC — but note the M4 death policy is
   full stop, so in practice this arm exists for the *chicken* exit
   path and manual recovery, not automation after death).

Note the deliberate symmetry: `GatedInput` requires "in a game with no
blocking panel"; `MenuInput` requires the complement. Neither can do
the other's job, and the M1 "Save and Exit" incident click is now
possible only through the path whose guard means it on purpose.

Re-check between cursor move and button event, exactly like
`GatedInput.click_screen` (same accepted-and-documented race).

## API sketch

```python
class MenuInput:
    def __init__(self, session, window=None, ui_array=None): ...
    def check(self, sx: int | None = None, sy: int | None = None) -> None:
        """Raise InputRefused unless a menu click/keypress is safe now."""
    def click(self, sx: int, sy: int) -> None:
        """Guarded left click at absolute screen coordinates."""
    def press_escape(self) -> None:
        """Guarded ESC (VK 0x1B): opens the ESC menu in game, backs out at menus."""
```

P3 composes these with P1's control rects (projected render→window —
P1's dump settles the scale factor; centers of button rects).
`press_escape`'s guard is arms 1 (foreground) + "the session is
attached" — ESC is context-safe in both worlds (toggles the ESC menu
in game, navigates back at menus), and it is the chicken's first move,
so it must work while `can_act()` is still true.

## Timing

Reuse `input.py`'s proven constants (`_PRE_CLICK_PAUSE_S`,
`_CLICK_HOLD_S` — 60 ms hold proven in M1). Menus are not
latency-sensitive; do not invent new timings without live evidence.

## Tests

Fake the OS layer (window + send functions) and the session, per the
existing pattern in `tests/` (see the `GatedInput` tests):

- Refusal: not foreground; outside client rect; in a game with no ESC
  menu open (the complement guard actually guards).
- Allowed: OOG; in-game with ESC menu open.
- ESC allowed in both worlds; refused when not foreground.
- The re-check-before-send behavior (state flips between move and
  click → refused, nothing sent).

## Live verification

🔶 requests (IDs continue from the instruction log): a gate-refusal
test mirroring M3's R3 — attempt `MenuInput.click` while in a game
with no panel (must refuse), while backgrounded (must refuse), at char
select in the foreground (must send; harmless coordinate). Small CLI
hook: extend `pd2bot.oog` (P1's CLI) or `navdemo` with a
`menu-gate` subcommand, whichever is less code.

## Conventions

- Narrative module docstring (why this exists, what incident shaped
  it) in the style of `input.py`.
- `python -m ruff check .` clean; no new dependencies.

## Validation

`python -m pytest -q`; `python -m ruff check .`; live gate checks.

## Agent reminders

- Do not commit unless the user asked.
- Do not modify `GatedInput`'s guard, ever, for any reason — if the
  design seems to require it, stop and report.
- Do not expand scope; no screen knowledge in this module.
- Do not suppress warnings or disable tests.
- Report what changed, what was validated, and any deviations.

## Definition of done

`MenuInput` exists with the three-arm guard; `GatedInput` untouched
(diff shows `input.py` changed only if primitives were lifted, with
zero guard changes); tests + lint green; live refusals/allowed checks
pass; instruction log updated.

## Implementation Result

Status: done
Completed: 2026-07-29
Commit: pending

- Changed: `pd2bot/menuinput.py` (new — MenuInput with the complement
  guard, menu_to_screen projection, click/click_menu/click_control/
  press_escape), `tests/test_menuinput.py` (new, 13 tests).
  `input.py` untouched (primitives imported, zero guard changes).
- Validated: 157 tests pass; ruff clean. Live (bridge 013, 015/016,
  019): in-game-no-ESC-menu refusal, backgrounded refusal, and the
  allowed path — bot clicked OK at char select, difficulty popup
  appeared, bot's ESC returned to char select (PASS, user-confirmed).
- Deviations: (1) the projection needed one live correction — menus
  are **aspect-fit (1.44x) and pillarboxed** on the 16:9 window, not
  stretched; first click missed 140 px right, hover calibration then
  confirmed the corrected model to ±2 px before any further clicks
  (the M3 config-file mystery scale 1.44 is hereby explained: it is
  the menu scale). (2) The planned death-screen guard arm was dropped:
  M4's death policy is full stop (R27/Q6), so no automated input ever
  follows a death — the arm would be dead code. (3) Live-found for
  P3: the in-game ESC menu is NOT in the D2Win control list — Save
  and Exit needs a calibrated fixed coordinate (R37).
