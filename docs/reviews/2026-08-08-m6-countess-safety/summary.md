# Review — the unstarvable-safety work and the town-walk fixes

**Target:** `m6-countess` @ `75c03b9` · **Base:** `fbb683e` (the HALT
commit) · **Reviewed:** 2026-08-08

**Scope:** 56 files, +8020 / −195. Two commits:

- `9ceb529` — friendly units are never scenery (NPC classification)
- `75c03b9` — the chicken can no longer be starved, plus the town-walk
  fixes, the `TraverseStep` cleanse, and screen-space click clearance

Requested with a specific weighting: **four defects in this diff were
already found by live runs rather than by review**, so correctness and
missed interactions were the focus, not style.

## Overall assessment

**The safety architecture is sound and I would keep it.** The two layers
are genuinely independent, the interrupt is correctly unswallowable, the
death latch is untouched, the latch asymmetry (world input blocked, menu
path open) is deliberate and tested, and the whole thing is proven live —
T80/T81 5/5 unattended, a full descent, and a watchdog that ran 2850
ticks clean.

**But the diff has a pattern worth naming:** every defect so far has been
an *interaction* between the new wall-clock cap and machinery that
predates it, not a fault inside the new code. The cap changed a contract
(`walk_to` no longer blocks until it is done) and each caller that
assumed the old contract broke in its own way — the town layer's
single-call walk, the NPC-dialog recovery keyed on `NavigationError`, and
now finding 002. Reviewing this diff means auditing *callers*, not the
new modules.

Finding 001 is the one that should be fixed before Stage D.

## Findings

| # | Severity | Title |
|---|---|---|
| [001](issues/001-watchdog-never-rearms.md) | **P1** | The watchdog never re-arms after it fires — Track B guards game 1 of N only |
| [002](issues/002-budget-check-preempts-the-avoidance-verdict.md) | P2 | The walk budget pre-empts the "hazard beside the goal" verdict, turning a correct outcome into a stall |
| [003](issues/003-dead-watchdog-spins-a-battery.md) | P2 | A dead watchdog spins create/leave through a multi-game battery instead of halting |
| [004](issues/004-run-mislabels-errors-as-blindness.md) | P3 | `run()` reports every unexpected error as a read failure |

001 and 003 both bite specifically on `--games N`, which is Stage D.
Neither affects the single-game runs done so far, which is why live
testing has not surfaced them.

## What I checked and found sound

- **The interrupt path.** `SafetyInterrupt(BaseException)` genuinely
  cannot be caught by the four broad handlers on the way out; conversion
  happens at exactly one site; `cycle.run_games` and `runner.py` catch by
  explicit type, so the base-class choice does not disturb them. Death
  still outranks stop.
- **The death latch.** Untouched, still permanent, still sends nothing.
  The watchdog mirrors it (`stopped` never cleared) — correct, and
  deliberately different from `fired`, which is finding 001.
- **Corroboration on death** (3 reads) delays a terminal, no-input
  outcome by ~0.6 s and costs nothing; the zero-hp gate also correctly
  suppresses the *chicken* on the same untrusted sample.
- **The heartbeat** is atomic (temp + `os.replace`), reports its own
  failures, and is only written after a successful read — so "blind" is
  signalled by silence rather than by a lie.
- **The latch asymmetry** is pinned by tests in both directions.
- **Test quality.** The regression tests demonstrate red: the starvation
  pair asserts the pre-fix 21.8 s blind window alongside the post-fix
  <1.5 s, and the town and traverse tests were each shown failing without
  their fix. The `say`/`alert` severity rule is pinned at source level.

## Validation inspected

- `pytest -q` → **1169 passed**; `ruff check .` → clean. Run at review
  time on the committed tree.
- Live evidence cited in the artifacts: T80/T81 (5/5 unattended), the
  Stage A descent (operator-verified to the bottom cellar floor,
  `nav.capped` 90, `safety.interrupt` 0, `watchdog.fired` 0), T82
  (allies 1 → 11), T83 (3/3 click clearance).

**Gap:** nothing has exercised a multi-game run. Both P-level findings
that are not yet observed (001, 003) live there, and Stage D is the first
thing that would meet them — unattended.

## ADR candidates

None new. `docs/adr/2026-08-07-unstarvable-safety.md` (accepted) already
covers the two-layer decision, and its stated standing rule — *any new
blocking call must take the poll* — is the right one. Worth adding a
second rule to it when 002 is fixed: **a caller that reads
`WalkResult` must distinguish "capped" from "stopped short on purpose"**,
because conflating them is what 002 is.

## Residual risk

- Stage D unattended is **not** covered by anything tested so far; fix
  001 (and preferably 003) first.
- The town route remains the least-proven path: two of the three failures
  this week were in town, and the Countess run has still never completed.
- The cap's blast radius on callers is now understood but not exhaustively
  audited — `_try_walk`, the waypoint step, and the survey path all call
  `walk_to` and were not individually re-read for the old contract.
