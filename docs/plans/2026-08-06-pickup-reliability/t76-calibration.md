# T76 run 2 — the pickup calibration, measured

2026-08-06. PASS: 15 targets across solo/pair/pile, 2 classes measured
both ways. Raw transcript in the drill output; this is the reading.

**Correction applied after the run**: `classify()` ignored PD2's `s`
family (`r05s`, `gzvs`), which R126 had already measured as *"the family
that actually drops"*. Two runes and a gem were filed as "other",
burying the two most interesting results. Fixed; the tables below use
the corrected classes.

## What was measured

| target | kind | code | class | crowd | result |
|---|---|---|---|---|---|
| 532 | 685 | `gzvs` | **gem** | 0 | won `(0,-28)`, 1 click |
| 941 | 387 | `xuc` | other | 1 | won `(-16,-40)`, 2 |
| 944 | 279 | `ob4` | other | 0 | won `(0,-40)`, 6 |
| 866 | 532 | `wms` | other | 0 | won `(-16,-40)`, 2 |
| 458 | 606 | `hp5` | **potion** | 0 | won `(0,-40)`, 6 |
| 592 | 703 | `r05s` | **rune** | 1 | **FAILED, all 8** |
| 862 | 420 | `ba5` | other | 0 | won `(0,-48)`, 8 |
| 941 | 387 | `xuc` | other | 9 | **FAILED, all 8** |
| 450 | 606 | `hp5` | **potion** | 8 | **FAILED, all 8** |
| 866 | 532 | `wms` | other | 8 | **FAILED, all 8** |
| 944 | 279 | `ob4` | other | 9 | **FAILED**, 2 neighbour steals |
| 946 | 189 | `7ar` | other | 9 | **FAILED**, 2 neighbour steals |
| 862 | 420 | `ba5` | other | 9 | **FAILED**, 1 neighbour steal |
| 449 | 605 | `hp4` | **potion** | 9 | won `(0,-40)`, 6 |
| 763 | 700 | `r02s` | **rune** | 9 | **FAILED**, 1 neighbour steal |

## Findings

### 1. In a dense pile the schedule simply does not work — 7 of 8 failed

Every one of those seven spent all eight offsets. Only a single potion
came up (at `(0,-40)`, on the sixth try). This is **stronger and
different** from the hypothesis under test: the prediction was "the
label displaces, so a *different* offset would work". The measurement
says that for a crowded item there is often **no offset in the schedule
that works at all**.

### 2. "Clicked A, got B" is confirmed live — 6 events

Six clicks aimed at one item picked up a different one. This was
inferred from T71 run 4's correlation; it is now measured directly,
which retires the inference.

### 3. The schedule's ORDER is bad — the first offset won 1 of 15

`(0,-28)` leads the schedule and won once. The winners were spread
across four different offsets — `(0,-28)`, `(-16,-40)`, `(0,-40)`,
`(0,-48)` — with no single dominant point, and one uncrowded item (862,
a barbarian helm) needing all eight before `(0,-48)` landed.

**The offset that wins is not stable per class, per crowding, or at
all.** That is the core result, and it is not what either the plan or
T63 assumed.

### 4. Runes failed 2 of 2 — one of them barely crowded

The Eth rune (592) failed all eight offsets at **crowd 1**. That is T71
run 4's Nef rune reproduced under controlled conditions, and it means
the rune problem is not only a pile problem.

### 5. Label geometry is NOT readable from the unit block

The probe found no screen-like coordinate pairs in any item's unit
block. **Direction A is provisionally dead** — though the probe only
scanned the unit's own 0x140 bytes, so this rules out the easy version,
not the idea. A BH.dll-side structure (where the loot filter lives, and
where T66 found the label flag) has not been searched.

## What this selects

Not **Direction B** (derive the offset from the neighbourhood): there is
no evidence of a *predictable* displaced offset to derive, and plenty
that no offset works in a pile.

**Direction C — unstack the pile behaviourally** — with a strong prior
on the two cheapest forms:

- **collect in draw order** (screen depth, `wx+wy` descending) so the
  top sprite goes first and uncovers the next; today the sort is world
  distance to the player, which is unrelated to what occludes what;
- **step and re-approach** — change the projection geometry and retry,
  rather than spending 8 clicks from one spot.

Plus a **re-ordered and probably extended schedule**, since even solo
items needed up to 8 tries and the first offset almost never wins.

## Caveats, stated because the sample is small

Single run, one town spot, one screen resolution. Class counts: gem 1,
rune 2, potion 3, other 9 — no charms at all, and charms are the class
T65 put 245 probes into with zero hits. The pile was crowd 8–9, which is
denser than the Countess chamber's 1–3. Before P3 commits, a second run
with charms and a moderate pile (crowd 2–4) would firm this up
considerably.
