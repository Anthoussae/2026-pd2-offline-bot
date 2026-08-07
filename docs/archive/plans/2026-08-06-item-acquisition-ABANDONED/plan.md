---
kind: plan
size: md
depth: implementation
status: active
repo: 2026-pd2-offline-bot
created: 2026-08-06
adr: expected
---

# Item acquisition — separating detection from pickup, and picking by GID

## Size and why

`md`: five phases, each `sm`. One agent can drive it, but the boundaries
are real — P1 is a refactor that must land green before anything builds
on it, and P4 is a **dangerous, gated spike** (out-of-process memory
writes) that the operator must go/no-go before it is trusted.

## Goal

Item pickup that is fast, accurate and reliable — and *structured* so
the "which items do we want" problem (detection) and the "get this known
item off the floor" problem (acquisition) never bleed into each other
again.

Baseline to beat: **18/31 (58%)** wanted items collected (T71 run 4),
worst-case **12 s** per failed item, and pickup as the single largest
time cost in a run (192 s of 930 s).

The frame-perfect ceiling the operator remembers is real and reachable:
kolbot's fast pickup is one `PickupItem` command by GID with no screen
aim at all (`notes.md`). Whether we can issue it out-of-process is P4.

## Acceptance criteria

- **Structure**: acquisition is its own module with the contract
  `acquire(unit_id, budget) -> outcome(reason, clicks, latency)`.
  Detection (pickit, sightings, the scan) lives outside it and does not
  import it. Provable by a drill that acquires *junk* — no pickit
  involved.
- **Accuracy**: on a full Countess run, wanted-item collection beats the
  18/31 baseline materially (target ≥90%), each remaining miss explained
  by the log.
- **Speed**: per-item acquisition latency reported and materially below
  today's 1.5 s-per-attempt pacing.
- **Safety**: no regression in the belt/inventory-full reasoning (T56);
  the death latch and gated-send contract untouched; any new write
  capability isolated behind its own guard and off by default until P4's
  go/no-go.

## Scope

**In**: an `ItemScan` detection surface and an `Actuator` acquisition
module; the click actuator improved (poll, draw-order, reposition,
schedule); the BH label-rect hunt; the out-of-process command-by-GID
spike; re-measurement; docs + ADR.

**Out**: whitelist/pickit accuracy (detection's *content*, a separate
track), muling, telekinesis pickup, the descent speed pass. Supersedes
`2026-08-06-pickup-reliability` P3/P4 only; its P1/P2/P5 stand.

## Discovery summary

See [notes.md](notes.md). The load-bearing findings:

- kolbot picks by **GID via a `0x16 PickupItem` command**, never by
  screen aim. That is the "frame-perfect" pickup, and it is a *command*,
  not a fast click.
- Our actuator is aim-based and T76 measured its ceiling: 7/8 unpickable
  in a pile, first offset wins 1/15, 12 s worst case.
- `_PickupMixin.collect` fuses detection, reach and lift; lift failures
  are mis-attributed to the other two.
- Command-by-GID needs an out-of-process **memory-write** capability the
  project has never had (`memory.py` is read-only). koolo is the
  precedent that it works without injection.

## Files/modules expected to change

- **New** `pd2bot/acquire.py` (the Actuator) and possibly
  `pd2bot/itemscan.py` (detection surface), or a clean split within
  existing modules — P1 decides.
- `pd2bot/behavior/steps.py` — `_PickupMixin` delegates to the Actuator.
- `pd2bot/behavior/execute.py` — the click actuator moves behind the
  seam.
- `pd2bot/memory.py` — a **write** path, only in P4, behind its own
  guard.
- `pd2bot/offsets.py` — the pickup handler address (P4), BH-cited.
- `drills/` — an acquisition drill (T1-shaped, junk items) and the P4
  spike drill.
- Docs: `behavior.md`, `perception.md`, a new ADR.

## Architecture decisions

- **Detection and acquisition are separate modules with one interface.**
  The operator's structural charge, and what makes the mechanism
  swappable.
- **The actuator's mechanism is pluggable** — click today, command
  tomorrow, with click as the permanent fallback (kolbot's shape).
- **ADR expected**: the out-of-process write/remote-call actuation
  extends and partially reopens `2026-07-28-python-out-of-process-
  perception`. Written at P4 whether the spike passes or fails — a
  measured "we tried command-by-GID and here is why not" is exactly the
  kind of decision an ADR exists to preserve.

## Validation strategy

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

Plus: the acquisition drill on junk (structure), T76 re-run after P2
(click accuracy), the P4 spike drill (supervised, isolated), and a full
run re-measured against the 18/31 baseline via `runlog --pickup`.

## Phases

| Phase | Size | Summary | Live? | Gate |
|---|---|---|---|---|
| [P1](01-separate-acquisition.md) | sm | Split detection from acquisition; `Actuator` with the click mechanism preserved exactly; a junk-item acquisition drill | No | End: the seam is clean (junk drill passes) |
| [P2](02-close-the-click-loop.md) | sm | Track 1: tight confirm poll, draw-order collection, reposition-on-miss, reordered schedule | 1 run | None |
| [P3](03-bh-label-geometry.md) | sm | The BH.dll label-rectangle hunt — if labels are readable, aim stops being a guess | read-only probe | End: readable or provably not |
| [P4](04-command-by-gid-spike.md) | sm | **Gated spike**: out-of-process `PickupItem` by GID; isolated, supervised | supervised drill | **go/no-go before anything trusts it** |
| [P5](05-adopt-and-remeasure.md) | sm | Adopt the winning mechanism; re-measure vs baseline; ADR, docs, teach, cleanup | 1 run | None |

P1 first and unconditional. P2/P3 are Track 1 and independent of P4. P4
is the risky spike — **on its own branch, rewindable wholesale** (the
operator's instruction). P5 last.

## Rewind contract (operator, 2026-08-06)

*"Be ready to rewind all changes we make."* The risky work — the memory
write path and the command-by-GID spike (P4, and P5 if it adopts P4) —
lives on an **isolated branch** off the stable line. Abandoning the
branch abandons the capability entirely, with the read-only,
SendInput-only architecture intact. P1–P3 carry no new capability and
are safe to keep regardless.

## Conventions and reminders

- Every offset/address cites its BH source. Every write is guarded and
  off by default until P4's go/no-go.
- The method note this project keeps paying for: read the event log;
  if it cannot answer, add the instrument, not a story.
- Do not commit unless asked. Do not weaken the belt/inventory reasoning
  or the death latch. A crash in P4 is a stop-and-report.
