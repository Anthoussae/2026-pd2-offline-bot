---
kind: plan
size: md
depth: implementation
status: active
repo: 2026-pd2-offline-bot
created: 2026-08-06
adr: possible
---

# Pickup reliability — making the bot actually get what it wants

## Size and why

`md`: five phases, each `sm`. One agent can execute end-to-end, but the
phase boundaries are real — **P2 is a live calibration whose answer
picks the P3 fix**, and the operator's time is the scarce resource. No
follow-up `yona-plan` pass expected.

## Goal

The bot collects the items its pickit decides it wants. Today it
collects 18 of 31 (T71 run 4) and spends the full 8-click budget on
every failure. Pickup is also the single largest time cost in a
Countess run (192 s of 930 s, plus the traversal-floor collecting that
dominates a ~9-minute descent).

Operator's framing, 2026-08-06: *"This level of delay and potential
failure is too high for the working bot."*

## Acceptance criteria

- **Accuracy**: on a full Countess run, wanted-item collection is
  materially better than the **18/31 (58%)** baseline, measured by the
  P1 report rather than by eye. Target ≥90%; a miss that remains is
  explained by the log, not a mystery.
- **Honesty**: every failure to collect emits an event saying which
  item, where, how many clicks, which aim points were tried, and the
  step's own diagnosis. No silent write-offs.
- **No regression** in the belt/inventory-full reasoning, which is
  load-bearing and was hard-won (T56's starvation loop).

## Scope

**In**: the click aim schedule and how it is chosen; collect ordering
and stand-off geometry; the click-budget write-off path and its
diagnosis; pickup instrumentation end to end; the P2 calibration drill;
a re-measurement run.

**Out**:
- Speed tuning of the descent (M6 scopes it out; evidence banked in
  `performance-notes.md`).
- **Tightening the pickit's rules** so fewer potions are fetched. It
  buys descent time while *hiding* the accuracy problem. Revisit as a
  deliberate decision once pickup is reliable.
- The navigator oscillation — measured and in scope only as a
  *suspect*; fixing it needs its own evidence (P2 may implicate it).
- Hold-to-move (R215), corpse retrieval, vendor UI.

## Discovery summary

See [notes.md](notes.md). The short version:

- Failure is **bimodal** (1–2 attempts or all 8), so it is systematic.
- Misses cluster where ground items are dense (26.3 vs 15.1 on screen).
- **9 of 13 misses have a collected item within 1–2 subtiles** — the
  "clicked A, got B" signature.
- A separate **item-class** failure exists (flawless emerald with no
  neighbours; T65's kind 619 at 245 probes, zero hits).
- **The pointer path is closed**: the hover slot ignores synthetic
  cursor motion (T60 run 3, 421 probes, zero flips) and clicks resolve
  against cursor position anyway (T63). `units.hovered_item_id` is
  built and correct but would verify nothing.

**Leading hypothesis**: PD2 displaces item labels vertically when items
are close, and `_PICKUP_OFFSETS` is 8 *fixed* offsets — one hypothesis
that predicts all four findings. P2 tests it.

## Files/modules expected to change

- `pd2bot/behavior/execute.py` — `_PICKUP_OFFSETS` and how an aim point
  is chosen; the pickup-attempt event's detail.
- `pd2bot/behavior/steps.py` — `_PickupMixin.collect` (write-off
  diagnosis, ordering), `send()` (the swallowed `NavigationError`).
- `pd2bot/runlog.py` — a `--pickup` report mode.
- `pd2bot/units.py` — only if P2 finds label geometry readable.
- `drills/t76_pickup_calibration.py` — new (P2).
- `tests/` — throughout.

## Documentation expected to change

`docs/architecture/behavior.md` (the pickup section — how aim is
chosen, what a write-off means), `docs/architecture/run-log.md` (new
events), `docs/architecture/perception.md` only if P2 adds a read.
Drill log + instruction log per protocol. `/teach` at the end.

## Architecture decisions

- **Clicks resolve on position, not pointer state** (T63) — treated as
  settled; do not re-litigate without new evidence.
- **The pickit's verdict and the bot's ability to act on it stay
  separate.** A full belt is a fact about us; a missed click is a fact
  about aim. Conflating them cost T56 a starved chicken.
- **ADR `possible`**: if P3 introduces a genuinely new mechanism
  (reading label geometry from BH.dll), that is new perception
  territory and deserves an ADR extending the perception approach.

## Validation strategy

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

Plus: P2's drill output captured into this directory; P5's re-measured
run compared against the 18/31 baseline using the P1 report.

## Phases

| Phase | Size | Summary | Live? | Review gate |
|---|---|---|---|---|
| [P1](01-instrumentation.md) | sm | Close the instrument gaps; `runlog --pickup` report; the baseline captured as a number | No | None |
| [P2](02-calibration-drill.md) | sm | The calibration: staged piles × item classes; does the hit offset shift with neighbours; probe for readable label geometry | **Yes** | **End of phase — the answer picks P3's fix** |
| [P3](03-the-aim-fix.md) | sm | Implement the fix P2 selected | Maybe | None |
| [P4](04-closed-loop-pickup.md) | sm | Verification and honest failure; unconflate belt-full from click-missed | No | None |
| [P5](05-remeasure-and-closeout.md) | sm | Re-measure on a real run vs the baseline; docs, teach, cleanup | **Yes** | None |

P1 and the *authoring* of P2's drill need no game and run immediately.
P3 needs P2. P4 is largely independent of P2 and can be pulled forward
if the operator's game time is delayed. P5 last.

## Operating constraint (operator, 2026-08-06)

*"Pause before we need any game time; we'll leave that for later. Do as
much as possible without needing access to the game."* Execute to the
live boundary and stop: P1 complete, P2's drill written and
unit-tested but **never launched**, P4 pulled forward where it does not
depend on P2's answer.

## Conventions and reminders

- Live checks need the elevated bridge; drills announce in game chat
  and only launch when the operator says they are tabbed in.
- Every calibration records provenance (drill id, date, window size).
- The method note this project has paid for repeatedly: **when
  something misbehaves, read the event log; if it cannot answer, add
  the instrument rather than a story.**
- Do not commit unless asked. No scope expansion. Report deviations.
