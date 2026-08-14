# P3 — berserk as the default posture, and longer quiet-field legs

Size: sm. Dependencies: none (parallel-safe with P2; both before P4).
Review gate: none.

## Scope

1. A `default_posture` knob in the class config, set to `"berserk"` —
   the operator's R256 QA ruling, verbatim: *"switch the bot's default
   combat behavior to Berserk, henceforth. We may shelve the skirmish
   stance entirely; for the foreseeable future, please set Berserk as
   the default posture. I'm fairly convinced that it's not just the
   fastest, but the safest too (best defense is a good offense)."*
2. `patrol_step` 12 → 20 (quiet-field leg length).

Out of scope: touching the reflex ladder, the safety monitor, retreat
mechanics inside postures, or `dash_step` (stays 8 — berserk barely
dashes; the strike ends where it lands).

## 1. default_posture

- `config/necro.toml`: add `default_posture = "berserk"` under
  `[combat]`, with a comment carrying the R256 QA ruling and date, and
  noting the cautious base + skirmish beat stay DEFINED (posture
  overrides still work) but nothing selects them by default anymore.
- `behavior/combat.py` (`ClassConfig` loading): parse the key; validate
  the name against the loaded posture presets AT LOAD — an unknown name
  refuses with a message listing valid names (same fail-loud manner as
  `keys.verify_skill_hotkeys`). Absent key = today's behavior (the
  cautious base), so old configs and every existing test fixture load
  unchanged.
- `behavior/necro.py` (`NecroCombat.__init__`): when the config names a
  default posture and the module has posture presets, apply it at
  construction (the existing `set_posture` — bookkeeping survives the
  swap, M6 P3). Steps that call `set_posture` later still win, exactly
  as today (`ClearRadiusStep.posture` is applied on the step's first
  tick and overrides).
- Berserk's mechanics need NO changes — R241 shipped and validated
  them: `style="charge"` skips wait-for-revives, the wall gate, and
  the post-strike retreat; armor recast tightened to 60%; the reflex
  ladder owns survival.
- Check `runs/*.toml` for steps that explicitly name `posture =
  "cautious"` — none are expected (countess uses brisk/aggressive;
  cold-plains names none). If one exists, leave it working and note it.

## 2. patrol_step

`behavior/steps/services.py`: `patrol_step: int = 12` → `20`. Update
the comment honestly: the cap exists so the reflex ladder gets its look
between legs; the 2 s walk budget (navigate.py) already bounds any
single blocking walk, and at the character's measured ~16.5 st/s a
20-subtile leg completes inside it. Cite T92.

## Validation

- Unit tests: config loading (valid name applied, unknown name
  refuses, absent key = base config); NecroCombat constructed with a
  default posture starts in it (assert via behavior: e.g. engage takes
  the charge path / config numbers match the preset) and a step-level
  `set_posture` still overrides.
- The engine sim (`tests/simworld.py` consumers) must stay green — sim
  fixtures don't set the new key, so nothing changes for them; if any
  sim asserts cautious-beat specifics against the REAL necro.toml,
  read carefully and adjust the test's own config, not the assertion.
- `python -m pd2bot.wiring --dry-run`-shaped checks are live-only; the
  pre-flight `describe` should print the default posture — add a line
  to `wiring.describe` (`posture    berserk (default; steps may
  override)`), tested if describe has tests.
- Full suite + ruff green.

## Conventions and reminders

- necro.toml comments carry rulings with dates — follow that idiom.
- This changes standing combat behavior by explicit operator ruling;
  do NOT water it down (no "berserk only when X" gates) and do not
  extend it (no preset edits).
- Do not commit unless asked; stop and report if any safety-adjacent
  coupling surfaces (e.g. a test that ties chicken behavior to the
  cautious beat).

## Definition of done

Default posture wired and validated, patrol_step 20, describe() says
the posture, suite + ruff green, notes.md updated with anything found.

## Implementation Result

Status: done
Completed: 2026-08-13
Commit: pending

- Changed: `default_posture` on ClassConfig + loader validation (unknown
  name/non-string refuse at load; absent = cautious base); NecroCombat
  `default_posture` field applied via `set_posture` in `__post_init__`;
  wiring passes the class config value and `describe()` prints the
  standing posture pre-flight; `config/necro.toml` sets
  `default_posture = "berserk"` with the R256 QA ruling quoted;
  `patrol_step` 12 -> 20 with the T92-cited rationale.
- Validated: 8 new tests (4 loader, 4 module incl. step-override-wins
  and unknown-name-loud); 4 steps tests updated 12 -> 20 hop
  expectations; 1 leash test given a deeper stray (20-subtile legs
  return to the line before the old geometry's heartbeat — the behavior
  improved out from under the test). Full suite 1335 green, ruff clean.
- Deviations: none.
