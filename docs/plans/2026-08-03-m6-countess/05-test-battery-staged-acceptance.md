# P5 — The Countess test battery and staged acceptance

> **Before restarting this battery, read
> [p5-preflight.md](p5-preflight.md).** T71 run 5 died mid-battery on
> 2026-08-07 (chicken starvation); the fix changed the walking layer,
> added a required watchdog process, and added three run-log event kinds
> to watch. The pre-flight records the delta, what could regress, and a
> suggested cheaper first step (a descent-only run) before the full
> Countess.

Part of [plan.md](plan.md) (M6). Size: `md` — live work is serial and
user-gated; no further planning pass needed, the stages are defined
here (the M5 P6 precedent). Dependencies: P4 passed its go/no-go. The
user is at the machine for every stage until the final one; abort
paths standing (chat abort, ESC/Enter kill switch, drill-cancel, the
mouse). Any death: full stop for a conversation — no same-day retry
without an explicit decision.

## Scope

The battery the user asked for: T-numbered drills per segment with a
time budget, then escalating acceptance to 3 clean unattended runs.
Threshold policy per R212 Q8: **chicken 50 for stages A–B, the review
at stage C decides, and proper runs are back at 35** — the acceptance
stage runs the config default.

## The time budget (reported every stage, gated never until tuning)

Against the 5–6 min target (user manual benchmark ~4): town ≤ 30 s,
waypoint ≤ 15 s, Black Marsh → Tower ≤ 60 s, the five cellar
traversals ≤ 45 s each, Cellar 5 clear + Countess ≤ 90 s, pickup +
leave ≤ 30 s ≈ **6:10 worst case**. These are instrumentation
(narrative-log per-step durations already exist), not abort criteria;
a stage that blows a segment budget passes on cleanliness and the
overage becomes a named tuning item.

## The stages (strictly in order; each a Drill Kit entry)

- **Stage A — segment drills** (carried from P2/P4 where already
  passed; re-run anything code has touched since): waypoint rows +
  tabs; T-descent (full traversal chain, brisk); a Cellar-5-only
  session — enter from Cellar 4, neighborhood clear, north approach,
  Countess kill, drop pickup — the endgame in isolation. Chicken 50.
- **Stage B — supervised full runs**: the complete
  `runs/countess.toml`, user watching hands-off, chicken 50. Two
  clean runs. Watch: posture switches at the boundaries (brisk
  traversal actually brushing past non-blockers; aggressive Cellar 5
  behavior incl. group backoff), right-skill parking after revive
  bursts, revive urgency, the chamber sweep firing (or the boss read
  making it a formality), the per-segment timings.
- **Stage C — threshold + posture review** (🔶 decision): with Stage
  B logs — chicken back to 35 (the Q8 note says yes); posture numbers
  (brisk corridor width, aggressive backoff trigger); any budget
  overages worth tuning now vs deferring. Config updated only here,
  not ad hoc.
- **Stage D — unattended acceptance**: `--games 3` via live-run.ps1,
  chicken 35, zero human input, monitor silent, Countess confirmed
  dead each run, drops swept. Report captured into this planning dir
  (the M4/M5 precedent) with per-run wall clock vs the target.

## Drill-kit conventions

Every stage's ask is a 🔶 numbered request with the outcome logged;
every run a drill-log row; PASS/FAIL announced in chat (R183 rule);
"clean" means clean — a retried stage is reported as such. Request the
standing-mandate form for Stage A's drill batch (the M5 reduction
lesson) — one 🔶 covering the batch, per-drill OKs waived, the user
tabbed in.

## Failure policy

A failure that needs more than a threshold/calibration tweak or a
small obvious fix is a stop-and-report, not an improvisation (the M4
robustness constraint, still standing). Livelock-shaped symptoms in
the cellars (line-of-sight churn — the user's named risk) get a
transcript capture before any fix attempt: the narrative log + engine
context exist precisely for this.

## Agent reminders

Do not commit unless asked. No scope expansion mid-battery. Report
faithfully; capture evidence into this dir before P6 archives it.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

Plus: Stage D's 3/3 report captured here; drill-log rows for every
stage; the time-budget table filled with measured numbers.

## Definition of done

Stages A–D passed in order with logged outcomes; thresholds finalized
via Stage C (chicken 35 for proper runs); the acceptance report and
timing table captured; open tuning items (if any) named for the
closeout's follow-ups.

## Named tuning item, already open (2026-08-06)

The first complete run (T71 run 4) landed before this battery formally
began and produced the battery's biggest finding early: **pickup
accuracy is ~42% failure on wanted items (13 of 31 attempted never came
up), and pickup is the largest single cost in the run.** The operator's
call: *"this level of delay and potential failure is too high for the
working bot."*

Full evidence and analysis: **notes.md → "NAMED TUNING ITEM: pickup
accuracy and the pickup logic as a whole"**. It is a workstream needing
its own planning pass, not a Stage C threshold tweak — so it does not
belong inside this battery, but Stage B/D reports must record pickup
attempted-vs-collected counts so the fix has a before-number to beat.
