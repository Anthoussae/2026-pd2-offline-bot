# DONE — survey system + post-run fixes (M5 P6, R175/R176/R177)

Completed 2026-08-02. Final commit at completion: see plan frontmatter.

## Outcome

Everything the plan promised landed and is live-proven, plus two
mid-flight additions the live runs demanded.

## Completed work

- **P1 cleanse hygiene** (`a00a650`): drop clear of wanted items, step
  off the pile, one differing retry per item then final. The R173 loop
  shape is a regression test.
- **P2 reposition reflex** (`a00a650`): rung 6.5, user-approved numbers
  (2% / 2.5 s / <3 subtiles / 10-step / 2 s pace), below the
  potion/warp rungs, never in town.
- **P3 survey** (`e1e5c1f`): `pd2bot/survey.py` frontier extraction,
  `SurveyStep`, wiring closures over the shared MapStore, two run
  files, loud unsurveyed-ground reporting (R176 Q2).
- **Mid-flight fixes** (`5b4b405`): fight patience (distance-or-hp
  progress, 20 stale ticks) after the first Cold Plains survey
  livelocked for 14 minutes on an approachable-never-reachable monster;
  sticky frontier targets after nearest-first flapping; max legs 500.
- **T52, the manual-survey drill** (`6a1536c`): user-driven surveys on
  the Drill Kit protocol with test-scoped END/DONE words
  (`DrillRun.heard`). Run 1: Cold Plains 57→114 rooms, frontier zero.
  Run 2: the whole Countess route (Black Marsh corridor, Tower,
  Cellars 1-5; the Countess floor frontier-zero).
- **T53, the patrol acceptance drill** (`c51bd14`, honesty fix
  `0d08d13`): run 1 halted on a potion shortage (R180); run 2 PASS,
  [CVRL] clean, 464 s.

## Validation

- 779 tests, ruff clean at every commit.
- Live: T52 x2 PASS; automated survey [CVRL] on both a fresh area
  (town, 29 rooms to frontier-zero) and a finished one (7-tick no-op);
  T53 run 2 [CVRL] with the click audit at **2/339** near-item clicks
  vs the R167 baseline of 31/39 accidental exemptions.

## Deviations from the plan

- The Cold Plains automated survey was superseded mid-plan by the
  user's manual T52 walk (faster, same atlas); the automated path was
  validated separately via the town run and the no-op sanity check.
- Two stall bugs (fight-gate livelock, target flapping) were not in the
  plan and were found by the first live survey; fixed with regression
  tests before any retry.

## Documentation

`docs/architecture/navigation.md` (survey section), `docs/drill-kit.md`
(test-scoped words), run-file headers, this plan's notes.

## ADRs

None — extensions of the existing atlas/step/reflex patterns, as
planned.

## Follow-ups outside this scope

- The R179 plan (`docs/plans/2026-08-02-potions-and-narrative-log/`):
  type-based belt, merc first aid, narrative log.
- ALT-1b (label-off policy): deferred; the T53 audit (2/339) suggests
  it may never be needed.
- Reposition rung: sim-tested, live-unexercised — nothing pinned the
  bot in this run; first real fire will show up in a narrative log.
