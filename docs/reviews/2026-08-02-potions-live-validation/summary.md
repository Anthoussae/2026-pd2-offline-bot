# Review — the potions cycle's live-validation session (2026-08-02)

- **Target:** `m5-trial-run`, `e6d9f4d..476f4a6` (20 commits, 51 files,
  +3570/−230) plus the in-review fix commit that follows.
- **Scope:** the potions/narrative/route implementation cycle (P1-P5),
  its live validation (T54 runs 1-4, T55 runs 1-4), and the R183-R191
  fixes each run's failure bought: the Shift merc chord, the 0-128 merc
  hp scale, bottom-of-column type checks, tick-level abort, the
  chat-console exemption, quiet-field/honest-budget upkeep, heal/repair
  skip thresholds, sweep-on-evidence, the collect no-progress budget,
  the patrol progress margin, seam-point filtering, route-answer
  debouncing, and the Enter/ESC operator kill switch.
- **Reviewer stance:** self-review of same-day work; the passes hunted
  for interactions the writing missed rather than re-reading intent.

## Overall assessment

Sound. The session's pattern — every live failure became a named
mechanism with a regression test — held throughout; the suite grew from
775 to 857 with live-derived fixtures (the 128/1620 merc probe, the
R178 belt, the seam livelock's arrival-short walk). One genuine defect
was found in review and fixed in place; two small refinements are filed
as issues rather than fixed, both bounded in cost.

## Findings

| # | Sev | Title | State |
|---|---|---|---|
| 001 | P1 | Stop checks preempted the death latch | **fixed in review** — `monitor.tick()` now precedes both stop checks in `engine.tick`; `DeathHalt` wins a same-tick race with any stop (test: `test_the_death_latch_outranks_every_stop`) |
| 002 | P3 | Sightings memo keeps no-longer-wanted items pending | open — fold into the next phase |
| 003 | P3 | Seam filter silently skipped when the first patrol tick has no area | open — fold into the next phase |

## Validation

- `pytest -q`: 857 passed (before fix: 856). `ruff check .`: clean.
- Live: T54 run 4 PASS (both stages), T55 runs 3-4 PASS at 217 s /
  236 s against the 1032 s baseline — the strongest validation this
  code has is the eight supervised runs in `docs/drill-log.md`.

## ADR candidates

None new. The kill switch and stop-priority policy are operational
conventions recorded in `docs/drill-kit.md` and enforced by tests; the
behavior ADR's amendments section already carries the cycle's
architectural changes. Nothing here chooses among plausible
alternatives with consequences the existing records miss.

## Residual risk

- The kill switch has not yet been triggered live; its first real ESC
  is the outstanding live test (unit-covered, low mechanism risk).
- The seam/border class of bug is defused for ring points and collects,
  but any FUTURE step that walks toward arbitrary coordinates should
  reuse `_route_leg`/collect-budget patterns rather than raw hops —
  noted for the M6 (Countess) planning pass, where multi-area routes
  are the whole job.
- `describe()`'s throwaway engine now constructs a Narrator and stop
  closures per build; verified inert (no file, no sends) but worth
  remembering when adding future per-build side effects.
