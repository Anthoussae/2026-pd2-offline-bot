# Review — m5-trial-run session work (786f7be..HEAD)

Reviewed 2026-08-02. Target: branch `m5-trial-run`, 21 commits, 63
files, +5710/-141. Scope: the perception/workflow mega-commit, cleanse
hygiene + reposition reflex (P1/P2), the survey system + stall fixes
(P3), drills T52/T53, and the plan/log/teach artifacts.

## Overall assessment

Sound. The work is heavily tested (752 → 779 tests, all green, ruff
clean at every commit), live-validated (T52 ×2 PASS, automated survey
[CVRL] twice, T53 run 2 [CVRL] with the click audit at 2/339 vs the
31/39 baseline), and consistently documented in the repo's own voice.
One P1 was found — the newest code repeating the session's own signature
bug class — and FIXED in-review with regression tests. Three P3s are
tracked, none merge-blocking.

## Findings

| # | Sev | Title | State |
|---|---|---|---|
| 001 | P1 | Cleanse hygiene walks were unbounded (livelock shape) | FIXED in-review + 2 tests |
| 002 | P3 | Frontier edge sampling can miss a narrow doorway | tracked |
| 003 | P3 | Survey target cache misses same-count terrain updates | tracked |
| 004 | P3 | `_hp_lost_in_window` re-reads the clock | tracked |

## Validation inspected

- Full suite 781 green post-fix; ruff clean.
- The R173 loop, the survey livelock, the target flapping, and now the
  hygiene walks each have named regression tests.
- Gaps, acknowledged: the reposition rung and the drop hygiene paths
  are sim-tested but never yet exercised live (T53 run 2 never needed
  them); the P5 route-aware-legs phase will surface both via the
  narrative log.

## Residual risk

- Step-level movement remains bearing-based until P5 lands (approved,
  R181) — dawdling at dead edges continues to be possible, bounded by
  budgets.
- The belt remains layout-rigid until the potion plan's P1 — the
  restock halt can recur (it cost two runs tonight).

## ADR candidates

None: every decision extends existing recorded patterns (atlas ADR,
step/reflex conventions, the Drill Kit contract).
