# P3 — The game cycle: create, verify, dwell, leave, repeat

Part of [M4 game cycle](plan.md). Size: `sm`. Depends on: P1 (screen
classification, difficulty read), P2 (`MenuInput`).

## Scope

`pd2bot/cycle.py`: the state machine that drives the client between
"in a game" and "at the menus", plus the run-loop skeleton around it.
CLI: `python -m pd2bot.cycle --games 3 --dwell 10`.

Out of scope: chicken/death monitoring (P4 — but design the loop so
P4's monitor slots into the per-tick path); any real run content (M5 —
the M4 "run" is dwelling in town); doors, waypoints, travel.

## The two sequences

**Leave** (from in-game): `MenuInput.press_escape()` → wait for
`UI_ESCMENU_MAIN` open → `MenuInput.click` on "Save and Exit Game"
(control rect from P1; fallback coordinate if blind mode) → wait for
`is_in_game()` false → wait for `CHAR_SELECT` classification.

**Create** (from char select): click OK (char is pre-selected — this
is guaranteed by our own leave sequence; if the user started the bot
fresh, the last-played character is pre-selected too) → wait for
`DIFFICULTY` → click **Hell** → wait for `is_in_game()` true → wait
for the player unit chain to read fully (position + area readable —
loading screens leave nulls mid-chain, M2's established polling
pattern) → **difficulty guard** (below).

Every "wait" is a poll with a timeout and a bounded retry of the
triggering click (kolbot's `locationTimeout` pattern, mined in
notes.md): default ~1 s poll interval, per-transition timeout on the
order of 10–20 s (loading screens are slow; be generous, then retry
the click once or twice, then fail the cycle). All timing injected for
testability, per `navigate.py`'s pattern.

## The difficulty guard (unconditional — user decision R29)

After every game entry, before the run callback executes:
`world.read_difficulty(session)` must equal Hell (2). Anything else:
**abort loudly** — leave the game via the leave sequence, halt the
loop, tell the human which difficulty was actually entered. Rationale
(from notes.md): a misclicked difficulty popup would silently record
wrong-difficulty terrain into the Hell atlas; this one-byte read makes
that impossible regardless of which P1 strategy (control list or
blind) is in use.

## Error taxonomy (decided at R27, do not relitigate)

| Event | Response |
|---|---|
| `InputRefused` / focus lost | Try `GameWindow.bring_to_foreground()` **once** after a short delay; if it refuses or focus is lost again soon after, pause the loop and wait for a human (loud message). Never fight a human for the mouse. |
| Screen transition timeout (retries exhausted) | Fail the cycle: describe the screen (`oog` classification + control dump), stop the loop. `UNKNOWN` screen → same, immediately — never click into a screen we cannot name. |
| `NavigationError` (from any walking a run callback does) | Abort the cycle: leave the game, count it as failed, start the next cycle. (A fresh game resets position — the cheapest recovery there is.) |
| Client process gone / reads failing | Stop and request the human. We attach, never launch (roadmap constraint). |
| Death detected (P4 wires this in) | **Permanent halt + alert. No input of any kind after detection** — not even leave-game. The game is left exactly as the human needs to see it. |

## The run-loop skeleton

```python
class GameCycle:
    def __init__(self, session, oog, menu_input, *, clock=time, config=...): ...
    def leave_game(self) -> None: ...
    def create_game(self) -> None: ...
    def ensure_at_char_select(self) -> None:
        """From any recognizable state (in game, char select), get to char select."""
    def run_games(self, run_callback, max_games: int) -> CycleReport: ...
```

`run_callback(session)` is the pluggable body — M4's demo callback
dwells N seconds (ticking the safety monitor once P4 lands); M5
replaces it with real runs. `CycleReport` records per-cycle outcomes
(created, verified-hell, run result, left cleanly, errors) — the
acceptance evidence and the future run log.

Startup (`ensure_at_char_select`): classify where we are — in a game →
run the leave sequence; at `CHAR_SELECT` → done; `MAIN_MENU` → click
Single Player; anything else → stop and describe. Never assume.

## Tests

All against fakes (scripted screen/session sequences + fake
clock/inputs, per `tests/test_navigate.py`'s pattern):

- Happy path: leave → create → hell verified → callback ran → leave.
- Difficulty guard: wrong difficulty → loop halts, no callback.
- Transition timeout → bounded retries → described failure.
- `UNKNOWN` screen → immediate stop.
- Focus-loss policy: one refocus, then pause.
- `NavigationError` in callback → cycle failed, next cycle starts.

## Live verification — the M4 acceptance gate

🔶 requests (IDs continue from the instruction log):

1. Leave-game sequence alone, from a game the user opened.
2. Create-game sequence alone, from char select (verify Hell guard
   passes; then, if cheaply possible, verify the guard *fires* by
   temporarily pointing the click at Normal — an expected-abort run —
   and confirm the abort message; delete any atlas writes from that
   game — there should be none, the guard aborts before the callback,
   but *verify* `maps/` is unchanged).
3. **Acceptance: `python -m pd2bot.cycle --games 3 --dwell 10`
   unattended — ≥ 3 consecutive full cycles, no human input.**

## Review gate

End-of-phase, after the acceptance run: report the CycleReport, any
retries/timeouts observed, and the strategy in use (control list vs
blind). The user confirms before P4 builds on the loop.

## Conventions

Narrative docstring; injected timing; no magic offsets here (P1 owns
them); no new dependencies; `ruff` clean.

## Agent reminders

- Do not commit unless the user asked.
- Do not expand scope (no combat, no travel, no potions).
- Do not weaken either input gate; do not suppress warnings or
  disable tests.
- Stop and report if blocked or if a live check contradicts the
  design.
- Report what changed, what was validated, and any deviations.

## Definition of done

Acceptance run passed (≥3 unattended cycles) and reported at the
review gate; difficulty guard demonstrated; error taxonomy unit-tested;
tests + lint green; instruction log updated.

## Implementation Result

Status: done
Completed: 2026-07-29
Commit: pending

- Changed: `pd2bot/cycle.py` (new — CycleConfig, GameCycle with
  leave/create/ensure_at_char_select, the unconditional difficulty
  guard, focus policy, CycleReport, run-loop + CLI),
  `pd2bot/menuinput.py` (public `ui_array` property),
  `tests/test_cycle.py` (new, 14 tests against a scripted client).
- Validated: 171 tests pass; ruff clean. Live (bridge 020–023):
  Save-and-Exit hover calibration (fractions 0.4889/0.4236 @1536×864);
  first autonomous round trip (leave→main_menu→create→difficulty 2);
  **acceptance 3/3 `[CVRL]`** via the real CLI, no retries, no focus
  interventions. User watched throughout and confirmed visually.
- Deviations from the phase file: (1) leave lands at MAIN_MENU (live
  finding R34) — sequences and tests written to that reality, with
  CHAR_SELECT also accepted post-exit for robustness. (2) The planned
  "expected-abort" wrong-difficulty live test was skipped: deliberately
  entering a Normal game would create exactly the risk the guard
  exists to prevent, and the guard logic (leave + halt before any
  callback) is fully unit-tested; difficulty read itself verified live
  (R34/008). (3) ERROR_POPUP policy is stop-and-describe (not
  auto-dismiss) per the safety-first posture. (4) `_with_focus` retries
  unconditionally on InputRefused (one wasted attempt on genuine state
  refusals) instead of classifying refusal flavor — simpler and
  race-free.
