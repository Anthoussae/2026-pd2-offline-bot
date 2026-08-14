# Pickup reliability — planning notes

Discovery log. Trigger: the operator's call after T71 run 4
(2026-08-06) — *"we need to refine item pickup accuracy considerably
more, and the whole pickup logic more. This level of delay and
potential failure is too high for the working bot."*

Their suggestion, verbatim, to be answered rather than deflected:
*"perhaps we could track the coordinates of dropped items, and the
coordinates of the mouse pointer, so that pickup can be reliable?"*

## The measured problem

From `logs/runs/20260806-025952-countess`, correlating
`action.pickup_attempt` against `item.collected` by unit id (the
correlation itself is a finding — see the instrument gaps below):

| | count |
|---|---|
| distinct wanted items attempted | 31 |
| collected | 18 |
| **never came up** | **13 (42%)** |

Two were valuable: a **flawless emerald** (kind 691) on Cellar 1 at
(12644, 5146), and a **Nef rune** (kind 702) in the Countess's chamber
at (12544, 11084).

### Finding 1 — failure is bimodal, so it is systematic

Successes take **1–2 attempts**. Failures take the **full 8**, which is
`pickup_click_attempts` and, by design, the exact length of the aim
schedule in `execute.py::_PICKUP_OFFSETS`. Nothing sits in between.
This is not flakiness; it is a click that was never going to land.

### Finding 2 — misses cluster in dense ground-item fields

| | mean ground items on screen | mean neighbours ≤2 subtiles |
|---|---|---|
| missed (13) | **26.3** | **1.6** |
| collected (18) | 15.1 | 0.9 |

### Finding 3 — "clicked A, got B"

**9 of the 13 misses have a COLLECTED item within 1–2 subtiles.** The
cleanest case is the one that cost a rune:

    MISS  nef_rune at (12544, 11084)
    OK    hel_rune at (12545, 11083)   -- ONE subtile away, 16 attempts

Also: three healing potions at (12545,11090), (12544,11091),
(12543,11090) — two missed, one collected.

### Finding 4 — a separate item-CLASS failure

The flawless emerald missed with **zero** neighbours, so occlusion does
not explain it. It matches T65 run 4: kind 619, **245 probes, zero
hits**. At least one class of item is not reachable by the current
schedule at all. Gems/jewels are the suspects.

## Prior art — DO NOT RE-DERIVE

The pickup click path has already been the subject of a five-drill hunt
(T58–T63, 2026-08-03). What it established:

- **T58** — the hovered-unit pointer exists and is durable:
  `offsets.PLAYER_HOVER_ITEM = 0xE8`, **player-unit-relative** (no
  pointer chain), read and validated by `units.hovered_item_id`, which
  rejects non-item units because the slot retains its last item while
  the cursor sits on a living unit.
- **T60 run 3 — the wall.** The hover pointer **ignores synthetic
  cursor motion**: 421 probes across a potion, the label visibly
  highlighting, **zero pointer flips**. It tracks a real hand. Labels
  poll the cursor position; the pointer listens to motion of a kind we
  cannot synthesise.
- **T61** — went looking for a motion dialect the pointer would accept
  (relative deltas, glides, jiggle). **Failed**; even a by-hand hover
  would not hold the pointer on the target, so its Q2 never ran.
- **T63 — the answer that shipped, and it answers T61's Q2 anyway:**
  *"position clicks DO pick items (no hover state needed; the hover
  pointer was a red herring for clicks)"*. Clicks resolve against the
  **cursor position**, not against pointer state. Measured offsets:
  labels **off** (0, −28), labels **on** (−16, −40).
- **T65 run 4** — the label band: small classes (runes, gems, charms)
  survived 58–147 direct probes on their ground sprites, while both
  hits landed at **y = −48**. Those items are effectively
  *label-clicked*, not sprite-clicked.
- **T66** — the ALT label-display flag is readable
  (`BH.dll+0x14D2CA`), and the executor ensures labels ON.

### What this means for the operator's suggestion

Half of it is already built, and the other half is measured shut.
*Tracking item coordinates* is done — every wanted drop is now logged
with world/local/relative position (fixed 2026-08-06). *Tracking the
mouse pointer* cannot drive pickup: the pointer will not follow a
synthetic cursor, and — decisively — **clicks do not consult it
anyway**. `hovered_item_id` is production-ready code with no production
caller, and wiring it in would verify nothing about a click that
resolves on position.

The **spirit** of the suggestion is still the right instinct and is
what this plan adopts: pickup today is **open-loop** (project → click →
hope → notice next tick), and it should be **closed-loop** — know what
we are about to hit, and know what happened.

## The leading hypothesis (to be tested, not assumed)

**Labels displace when items are close, and the aim schedule is a fixed
set of offsets.** PD2 stacks item labels vertically so a human can read
and click them individually in a pile. If the label for our target is
pushed off its expected offset by neighbours, then:

- every fixed offset misses → all 8 attempts fail → **bimodal**;
- worse in dense fields → **the density correlation**;
- a click at the expected offset lands on a *neighbour's* label →
  **"clicked A, got B"**;
- small classes that are label-only (T65) fail hardest → **the rune and
  the gem**.

One hypothesis explains all four findings. That is worth a measurement
before any code changes.

Rival hypotheses kept live: draw-order/occlusion of the sprites
themselves (collect order is currently world-distance, unrelated to
draw order); stand-off geometry (the projection may be less accurate at
some relative bearings); and the navigator oscillation putting the
character in a bad place to click from at all.

## Where the code is

- `pd2bot/behavior/execute.py::_PICKUP_OFFSETS` — the 8-offset schedule.
- `pd2bot/behavior/steps.py::_PickupMixin.collect` — reach, walk budget,
  click budget, retry pacing, the belt-full vs inventory-full reasoning.
- `pd2bot/behavior/steps.py::_PickupMixin.wanted_items` /
  `log_wanted_drops` — enumeration and the wanted-drop record.
- `pd2bot/units.py::hovered_item_id` — built, validated, uncalled.
- `pd2bot/units.py::label_display_on` — label state, read live.

## Instrument gaps in scope

1. **A click-budget write-off is silent.** 11 of the 13 misses emitted
   no `item.abandoned`; only walk-based give-ups are logged. "What did
   we fail to pick up" currently needs hand correlation.
2. **A failed walk emits nothing.** `send()` swallows `NavigationError`
   into `services.log`, so the four 25–35 s ticks in T71 run 4's
   endgame are visible only as durations with nothing inside them.
3. Fixed already (2026-08-06): `item.dropped` firing on every floor.

## Related, possibly the same problem

`performance-notes.md` — the navigator oscillates around close targets
(clicks alternating ~5 subtiles either side of a goal, giving up after
"5 plan cycles without progress"), costing ~120 s of T71 run 4's 186 s
endgame. A click issued from the wrong stand-off position fails no
matter how good the aim schedule is, so pickup accuracy and walk
accuracy may be one problem. Kept in scope for measurement; fixing the
navigator is not in scope unless the measurement implicates it.

## Out of scope

- Speed tuning of the descent (M6 scopes it out; evidence banked).
- Tightening the pickit's rules to fetch fewer potions. It buys descent
  time while **hiding** the accuracy problem — explicitly not the first
  move, and a decision for after the accuracy work.
- Hold-to-move (R215) — separate discovery, though it interacts.

## Questions for the operator

See the phase table and the discussion question raised in chat
(2026-08-06). Answers get recorded here.
