# P3 — Postures, right-skill parking, revive priority, review fixes

Part of [plan.md](plan.md) (M6). Size: `sm`. Dependencies: none
(parallelizable with P1/P2; P4 needs it). All sim/unit-testable — no
live time required; live behavior is judged in P5's battery.

## Scope

The behavior changes the user has specified (R212 Q5/Q6 + the M5
notes), and the four carried-over P3 review issues. The reflex ladder
and the safety stack do not change — postures are offense-only, which
is behavior.md's stated boundary and what makes this phase safe.

## Implementation

1. **Posture presets** (`combat.py` loader + `necro.py` +
   `config/necro.toml`). A named posture is a preset over the knobs
   behavior.md §"Combat posture" already classified. Add a
   `[combat.postures.<name>]` table shape; unknown keys refused as
   ever. Three postures:
   - **cautious** — the shipped numbers, verbatim (the default; zero
     behavior change when no posture is named).
   - **brisk** — fights only what obstructs passage: engagement
     narrowed to a corridor around the current route leg (a
     `corridor_radius` engage filter — the survey_engage_radius
     precedent), no lingering to finish poisoned stragglers once the
     path is clear, keeps moving toward the step's target otherwise
     "as long as that is safe" — the safety half is untouched ladder
     + the existing retreat beats.
   - **aggressive** — attacks whenever safely feasible, especially
     isolated enemies; still backs off from groups that close in
     (user definition, R212 Q5). Concretely: shorter/no
     hold-until-wall beyond `approach_with_revives`, restrike freely,
     but a group-proximity check (N hostiles within R closing) still
     triggers the retreat/disengage shape.
   The exact numbers per posture ship as commented config defaults —
   judgment calls, tuned in P5 like every M5 number was.
2. **Per-step posture selection** (`steps.py`/`run.py`/engine
   context): run steps accept an optional `posture` parameter
   (validated against the loaded presets at load time), applied for
   the step's duration via the combat module. The Countess run (P4)
   will use: brisk on the traverses (Black Marsh → Cellar 4 entry),
   aggressive on Cellar 5 (R212 Q5). Runtime switching = the module
   swaps its active config dataclass between ticks — no state loss
   (`_last_strike` etc. survive).
3. **Right-skill parking** (`execute.py`, R212 Q6): after a
   `CastSelf`/`CastAtPoint` resolves, if no further cast executes
   within `park_grace_s` (~2 s, config), press the bone-armor hotkey
   through the verified switch (switch only — no cast). Implemented
   as a deadline the executor checks on subsequent executes plus an
   engine-tick hook (a parked check must not require another action
   to trigger). Rationale (user): an active Revive right-skill makes
   ground corpses selectable, interfering with pathing and pickup.
   The trace records every park.
4. **Revive priority bump** (`necro.py`, user note 1.5): below
   `revive_target` with hostiles present, the desecrate→revive loop
   currently interleaves 1:1 with offense ticks and waits out settle
   timers passively. Bump: while the wall is short AND the ladder is
   otherwise quiet, upkeep may claim consecutive ticks (bounded — the
   existing desecrate budget and settles still apply) so the
   quick desecrate→revive loop completes promptly instead of
   dribbling. Config: `revive_urgency` or similar, commented. The
   quiet-field gate (R185 A) stays — no churn in empty fields.
5. **Carried review fixes** (all P3s, R212 Q9):
   - Sightings memo keeps no-longer-wanted items pending
     (potions-live-validation 002) — re-filter the memo against the
     pickit + belt/inventory state when the sweep consumes it.
   - Seam filter silently skipped when the first patrol tick has no
     area (003) — resolve the area lazily instead of once.
   - Frontier stride can miss narrow doorways (session review 002) —
     directly cellar-relevant; tighten the stride or add a
     doorway-width probe.
   - Survey target cache misses same-count terrain updates (003) —
     key the cache on something that moves with content.

## Testing

Unit tests: posture preset loading (incl. rejection), per-step
selection, parking (grace, no-double-park, refused-switch handling —
pacing not cooldown, the stage-B-run-9 rule), revive burst bounds,
each review fix pinned by a regression test. Sim: a brisk traversal
past a non-blocking monster (walks on), an aggressive isolated-kill,
a group-close backoff.

## Docs

`behavior.md`: the posture section graduates from "classification" to
"implemented presets"; parking + revive urgency documented in the
executor/upkeep sections. `necro.toml` comments carry the user's
definitions verbatim.

## Agent reminders

Do not commit unless asked. Postures must not touch the ladder, the
monitor, or the executor's safety rules — if an implementation wants
to, stop and report. No scope creep (no posture UI, no fourth
posture). Report deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

## Definition of done

Three postures load and select per step; parking and revive bump
implemented and traced; four review issues fixed with regression
tests; sims green; docs touched; no ladder/safety diffs.

## Implementation Result

Status: done
Completed: 2026-08-03
Commit: pending

- Changed: `necro.py` (posture fields + `set_posture` — config swap,
  bookkeeping survives; `linger`, group-conditioned retreat, the
  revive-urgency hold keyed to a recent wall cast, time-based desecrate
  budget refresh); `combat.py` (posture tables — overrides only, no
  skills, cautious unredefinable; new [combat] keys incl. the two
  bools); `execute.py` + `actions.py` (`maintain()` parking with
  `ParkSkill` trace entries, paced failures); `engine.py` (per-tick
  `maintain` grant, best-effort, not activity); `steps.py` (`posture`
  step param + build-time validation via `services.postures`;
  first-tick application; sightings memo carries kind+potion and
  `pending_sightings` re-asks wantedness [review 002]; patrol ring not
  cached until an Area filtered it [review 003]); `survey.py`
  (EDGE_STRIDE 8→4, doorway coverage [session-review 002]);
  `mapstore.py` + `wiring.py` (content `revision`, survey cache keyed
  on it [session-review 003]); `run.py` (posture ParamSpec, both
  vocabularies); `config/necro.toml` (new keys + brisk/aggressive
  tables, commented as P5-tunable first guesses); `wiring.py`
  (postures → module + services, park wiring); `behavior.md` (posture
  section: classification → implemented).
- Validated: **892 tests** (was 873; 18 new + 1 reshaped), ruff clean.
  New coverage: posture loading incl. refusals, set_posture swap,
  brisk hand-back, aggressive isolated-vs-group retreat, urgency hold
  fires/expires/never-holds-hostage, budget refresh (quiet-field gate
  untouched), parking (grace, burst deferral, paced refusal, trace),
  step posture application + build-time unknown-name error, sighting
  wantedness skip, seam late-filter, doorway frontier, revision bump.
- Deviations: the urgency hold is keyed to a RECENT wall cast rather
  than the plan's looser "may claim consecutive ticks" — same intent,
  chosen precisely to avoid re-creating the pre-R163 passivity; the
  sim's no-restrike assertion was reshaped to "no restrike within the
  window" (a legal post-window restrike now occurs — designed
  behavior the old timing merely never exhibited).
