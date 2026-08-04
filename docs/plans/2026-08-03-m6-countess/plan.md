---
kind: plan
size: md
depth: implementation
status: active
repo: 2026-pd2-offline-bot
created: 2026-08-03
adr: possible
---

# M6 — the Countess flagship run

## Size and why

`md`: six phases, each `sm` except the staged live battery (P5, `md`
by nature — live stages are serial and user-gated). One agent can
execute end-to-end; the phase boundaries exist for the live gates and
because P1/P2 (perception + traversal) must be proven against the game
before P4/P5 build on them. No follow-up `yona-plan` pass is expected;
P5's stages are defined here (the M5 P6 precedent).

## Goal

The bot farms the Countess: town chores → waypoint to Black Marsh →
traverse to the Forgotten Tower → descend Tower Cellar 1–5 → clear
Cellar 5's neighborhood → kill the Countess (approached slowly from
the north, revives tanking) → **take extra care over her drops** →
leave, repeat. Target **5–6 minutes per run** (user benchmark: ~4 by
hand). A **test battery** (T-drills + staged acceptance) is an
explicit deliverable alongside the run itself.

## Acceptance criteria

- Staged battery passed in order, ending with **3 clean unattended
  Countess runs** (created, Hell-verified, full route, Countess
  confirmed dead, her drop zone swept per the pickit, left; monitor
  silent; chicken at the config's 35 for the acceptance stage).
- Per-run wall clock reported against the 5–6 min target (reported,
  not gated — the first acceptance measures the baseline; speed tuning
  is follow-up work if it misses).
- All-new perception (exits, boss identity) live-verified with the
  drill discipline; every calibration recorded with provenance.

## Scope boundaries

**In**: level-exit perception (memory-read), the `traverse` step,
waypoint act tabs + three new destination rows, posture presets
(brisk + aggressive) with per-step selection, right-skill parking,
revive priority bump, the Countess endgame (clear-nearby, north
approach, chamber sweep / boss-read, careful pickup), the test
battery, the four carried-over P3 review issues, closeout.

**Out** (recorded in notes.md): **doors** — none need opening on this
route (user decision, R212 Q3); bundle them later with chests/boxes/
barrels and teleporter gates as "interactive objects". Vendor UI,
corpse retrieval, TP tome, boss-ID beyond the Countess, a posture
runtime-switch UI, speed optimization beyond the battery's report.

## Discovery summary

See [notes.md](notes.md) — full Q&A (R212) and code inspection. Key
facts: the whole route is already atlased (`maps/4e52715f-d2/`
area-006, 020, 021–025 — the T52 capital); cross-area walking and
level-exit perception do not exist yet (Room2 basics are in
`offsets.py`, the RoomTile chain is not); cellar connections are
single-click staircases, not doors; `WaypointConfig` knows only two
destination rows and no act tabs; posture-relevant knobs and code
seams are already mapped in behavior.md §"Combat posture".

## Files/modules expected to change

- `pd2bot/offsets.py` (RoomTile chain, MonsterData boss fields, area
  ids 6/20/21–25, staircase/warp facts — every entry cites BH source)
- `pd2bot/units.py` or new `pd2bot/exits.py` (exit reader; boss read)
- `pd2bot/uipoints.py`, `pd2bot/waypoint.py` (act tabs, three rows)
- `pd2bot/behavior/steps.py` (the `traverse` step; Countess endgame),
  `run.py` (registry entries), `necro.py`/`combat.py` (postures,
  revive priority), `execute.py` (right-skill parking), `wiring.py`
- `config/necro.toml` (posture presets, parking grace, revive bump),
  `runs/countess.toml` (new)
- `drills/` (the T battery), `docs/drill-kit.md` if conventions grow
- Review-issue files: `steps.py` (sightings memo, seam filter),
  `survey.py` (frontier stride, cache key)

## Documentation expected to change

`perception.md` (exits + boss read), `navigation.md` (cross-area
traversal section), `behavior.md` (postures become real; parking;
revive priority), README (countess run), CLAUDE.md (M6 done-line at
closeout), roadmap M6 row, teach + glossary, instruction/drill logs.

## Architecture decisions

- **Exits are read from memory** (Room2 → pRoomTiles → RoomTile →
  destination Level), the BH/kolbot-standard structure; the atlas
  remains the routing authority. Fallback if the read disappoints: the
  user-designed calibration survey (manual walk; "Exit" + hover at
  each transition; bot records) — machinery precedent T20/T25.
  **ADR candidate** at closeout: extends the hybrid map-knowledge ADR.
- **Postures are config presets over existing knobs** (behavior.md's
  classification), selected per run step; the reflex ladder and
  safety stack are posture-independent, by construction.
- The traverse step follows the waypoint.py trust pattern: every
  transition proven by area id, never by the click.

## Validation strategy

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

Plus the P5 battery: unit tests against fixed buffers for all new
decoding; sim coverage for traverse/endgame; live T-drills for every
new mechanism; staged acceptance with captured reports.

## Phases

| Phase | Size | Summary | Review gate |
|---|---|---|---|
| [P1](01-transit-and-boss-perception.md) | sm | Exit + boss perception: RoomTile chain, MonsterData boss fields, area ids, readers + unit tests | None (live proof rides P2's drills) |
| [P2](02-waypoint-tabs-and-traverse.md) | sm | Waypoint act tabs + 3 new rows (calibration drills); the `traverse` step; live traversal drills down the route | End of phase: full-descent drill observed |
| [P3](03-behavior-postures-and-defaults.md) | sm | Brisk + aggressive presets, per-step posture; right-skill parking; revive priority bump; carried P3 review fixes | None |
| [P4](04-countess-run-and-endgame.md) | sm | `runs/countess.toml`; Cellar-5 endgame (clear-nearby, north approach, sweep/boss-read, careful pickup); sim | Go/no-go before live |
| [P5](05-test-battery-staged-acceptance.md) | md | The battery: segment drills with time budget → supervised full runs (chicken 50) → threshold review (back to 35) → unattended 3/3 | Staged, per the M5 ladder |
| [P6](06-closeout.md) | sm | Docs, ADR decision, README/CLAUDE.md/roadmap, teach, sweep, logs, archive + `_DONE.md` | None |

P1 and P3 are independent and could interleave; P2 needs P1; P4 needs
P2+P3; P5 needs P4; P6 last. Live phases (P2's drills, P5) need the
user at the machine per the standing protocol; the R207-style standing
mandate should be requested for the calibration/drill stretches (M5
reduction lesson).

## Conventions and reminders

- Every offset cites its BH source file+line. Every calibration
  records provenance (drill id, date, window size).
- A cast is a request; the effect is the proof — transitions by area
  id, boss death by re-read, calibrations by hover-verify.
- Text transforms on repo files via Python, not PowerShell (R44).
- Do not commit unless the user asks; no scope expansion; stop and
  report on ambiguity; report deviations faithfully.
- Chicken: 50 for the first cellar drills, **back to 35 for proper
  runs** (R212 Q8) — the acceptance stage runs at 35.
