# Item acquisition — planning notes

The operator's charge (2026-08-06, verbatim in the parts that bind):

> *"Our current item pickup algorithm is slow and inaccurate. ...
> I've definitely seen D2 bots that INSTANTLY pick up items, nearly
> frame-perfectly, and they did so 25 years ago on very slow and crude
> hardware. Such a technology should be within our grasp, if we can
> just find the way to do it. ... It may be necessary to separate out
> the 'item detection' problem from the 'item pickup' problem too, so
> that there isn't conceptual bleed."*

This plan is dedicated to pickup **speed, accuracy and reliability**.
The operator explicitly licensed reconsidering the whole mechanism and
consulting kolbot's source.

## The answer to "how did 25-year-old bots do it": they never clicked

Read from the kolbot clone in this repo (behavioral reference only):

**`libs/core/Packet.js::click`** — the fast path of every pickup —

```js
new PacketBuilder()
  .byte(sdk.packets.send.PickupItem)   // 0x16 (sdk.js:5289)
  .dword(sdk.unittype.Item)            // 4
  .dword(who.gid)                      // the item's unit id
  .dword(toCursor ? 1 : 0)
  .send();
```

**One engine packet.** No cursor, no screen coordinates, no sprite or
label hit-testing, no aim schedule. The game's own code resolves the
unit id server-side (in single player the "server" is in-process). The
whole geometry problem this project has fought through T57–T76 — sprite
offsets, label bands, pile occlusion, clicked-A-got-B — **does not
exist on that path.** Our own T63 docstring recorded this a month ago:
*"kolbot never solved screen clicking (it sends engine packets)."*

The surrounding loop (`Pickit.js::pickItem`):

1. move within **4–6 subtiles** first (`Pather.move`, `minDist: 4`);
2. send the packet (`Config.FastPick || i < 1`; falls back to
   `Misc.click` — a screen click — only on later retries without
   fastpick);
3. verify by **polling the item's own mode** (`onGroundOrDropping`) at
   10–40 ms granularity, up to 1 s;
4. 3 retries, then a per-item ignore list.

Per-item wall clock ≈ walk + ~100–500 ms. Telekinesis variant for
sorcs (`Packet.telekinesis`, range 5–20) — not available to a necro.

## Why ours is slow and inaccurate — measured, not guessed

### Accuracy (T76 run 2 + T71 run 4, all on the record)

- In a dense pile **7 of 8 targets could not be picked by ANY of the 8
  offsets**; 6 clicks landed on a neighbour instead.
- The schedule's first offset won **1 of 15** targets; winners
  scattered over four offsets; one uncrowded helm needed all 8.
- Runes failed 2 of 2, one at crowd 1. Charms unmeasured live but T65
  put 245 probes into one (kind 619, `cm2`) with zero hits.
- Run baseline: **18/31 (58%)** wanted items collected (T71 run 4).

### Speed (constants in `steps.py` / observed)

- `pickup_retry_s = 1.5` between clicks on one item → a success on
  attempt k costs ~1.5·k s; the *median successful* pickup in T76 run 2
  took 2 attempts, i.e. ~2–3 s; a write-off costs 8 × 1.5 = **12 s**.
- Verification is "did it leave `ground_items`" checked on a LATER
  TICK (tick cadence 0.25–0.8 s), not a tight poll — kolbot verifies
  the same fact at 10 ms granularity.
- The engine tick also interleaves the ladder, combat looks, etc.
  between attempts (correct for safety, but the pacing above dominates).
- T71 run 4: `pickup` step alone 192 s of a 930 s run; traversal-floor
  collecting dominated a ~9-minute descent.

### The conceptual bleed the operator named

`_PickupMixin.collect` fuses three concerns: *should we want this*
(pickit — actually decided earlier, but re-consulted for logging),
*can we reach it* (walk budgets), and *can we physically lift it*
(click schedule + belt/inventory diagnosis). Failure of the third is
routinely mis-attributed to the first two ("inventory full (inferred
from persistence)"). Detection is instrumented (`item.dropped`) and
basically works; acquisition is the broken half — and there is no
module whose single job is "given a unit id, get it off the floor".

## The fork in the road

### Track 1 — stay with synthetic input, close the loop, fix the pacing

No architecture change. Components, each independently valuable:

- **An acquisition module** with a narrow contract:
  `acquire(unit_id, budget) -> outcome(reason, clicks, latency)`.
  Detection (pickit, sightings) stays outside it. Drillable with ANY
  item, junk included — exactly the operator's separation.
- **Tight verification**: after a click, poll perception for the item
  leaving the ground at ~50 ms for ~600 ms (T76 observed sub-0.9 s
  confirm latency; measure precisely first). Cuts per-attempt cost
  from 1.5 s toward ~0.3 s and makes attempt N+1 start the moment N
  provably failed.
- **Draw-order collection** for piles: collect the topmost sprite
  first (screen depth = wx+wy descending), uncovering the next — the
  current order is world-distance-to-player, unrelated to occlusion.
- **Reposition on repeated miss**: step 2–3 subtiles and re-project
  instead of spending the whole budget from one spot (T76: the same
  offsets from the same spot just fail again).
- **Schedule reorder** from T76 win data ((0,-40) and (-16,-40)
  outperform the current leader (0,-28)) and per-class tails.
- **The BH label-rect probe**: labels are drawn by BH.dll (PD2's loot
  filter — where T66 found the label-display flag). If BH keeps label
  rectangles readable, aim stops being a guess entirely: click the
  rect centre. T76's probe only scanned each item's own unit block
  (0x140 bytes); BH's data sections were never searched. This is the
  accuracy endgame for the click path and deserves a real hunt
  (T58/T66 methodology: correlate across state changes).

Honest ceiling: even perfect clicks cost a cursor round-trip per item
and are serialized by the game's input hit-test. This track makes the
click path as good as it can be — which T76 shows is *not* good enough
in a dense pile, where no offset works at all. It is the safe floor,
not the answer to "frame-perfect".

### Track 2 — acquire by unit id, the way the fast bots do

Do what kolbot's fast path does: hand the game a **`PickupItem` command
addressed by GID**, and let its own code resolve the unit. No cursor, no
projection, no hit-test — so nothing to miss, and the cost collapses to
walk + one command + a tight confirm poll.

The catch is a real one, and it is an **architecture decision, not an
implementation detail**. This project is out-of-process by ADR
(`2026-07-28-python-out-of-process-perception`) and has only ever
*written* to the game through `SendInput`; `memory.py` is read-only
(`u32`, `ptr`, no write path). Commanding a pickup by GID needs a
capability we do not have, and there are two out-of-process ways to get
it, both requiring memory **writes**:

1. **Remote function call** — `CreateRemoteThread` / thread-hijack to
   call D2's own pickup handler with `(unittype.Item, gid, toCursor)`.
   This is the class of technique **koolo** (the Go, out-of-process bot
   our own ADR cites as a precedent) uses — the existence proof that a
   *non-injected* out-of-process bot picks frame-perfectly. Needs the
   handler's address + calling convention, sourced from BH like every
   offset.
2. **Packet into the client's own buffer** — write the 0x16 bytes where
   the client's dispatch will process them. Offline SP has no socket,
   but the client still runs a local packet loop; reachability by an
   out-of-process write is unknown and is itself the spike question.

*Pro*: retires the entire geometry problem — accuracy becomes ~100%,
speed collapses to the walk. *Con*: a genuinely new and **dangerous**
capability. A wrong remote call crashes the client. It reopens the
actuation half of the ADR ("input is the dangerous half"), and seasonal
maintenance grows by a function address, not just a struct offset. So it
is a **spike with a hard go/no-go**, isolated and supervised, before any
run depends on it.

## T76 run 3 (2026-08-06): label state may be the pile variable

A charm re-run that nearly INVERTED run 2, and the standout difference is
not the items — it is the **ALT label display**:

| | run 2 | run 3 |
|---|---|---|
| label display (ALT) | **ON** | **OFF** |
| pile (crowd 8-9) result | **7 of 8 FAILED** | **all lifted, ~1 attempt each** |

In run 3, a genuine pile of nine (crowd 8) was swept almost perfectly at
the leading offset `(0,-28)` — the exact case run 2 could not pick at
all. The one variable that flipped is label state.

**Hypothesis (a lead, not a conclusion):** the stacked *label boxes*,
not the sprites, are what create the pile occlusion. Labels OFF → click
the sprite at `(0,-28)` and it lands, even in a pile. Labels ON → the
vertically-displaced label boxes overlap and a fixed offset hits the
wrong one (run 2's "clicked A got B" at scale).

**Why this matters for the real bot:** the executor **ensures labels ON**
(so small classes can be label-clicked, T65). If labels-ON is what
defeats piles, then that policy is plausibly a *contributor* to T71 run
4's pile failures — the bot fights the Countess chamber in exactly the
labels-ON, dense-floor regime run 2 measured as worst-case.

**The tension it exposes:** T65 measured runes/gems/charms as
near-unclickable by sprite (245 probes, 0 hits) — they *need* labels ON
to be hit at their label band. So "labels OFF always" is not the answer;
"labels OFF for a pile of normal items, ON for an isolated small item"
might be. This is a P2 question with a clean experiment: same pile,
toggle labels, measure.

**Caveats, because the confound is real:** two runs, label state was NOT
the controlled variable (items and positions also differed), town, small
samples. And the **charms were never directly aimed at** — all three
(cm1/cm2/cm3, kinds 618-620, now correctly classified) were
neighbour-swept off the floor before the schedule reached them, so
"can we deliberately pick a charm" is still unmeasured. The classifier
fix is validated; the charm-aim question is not.

**What it does NOT change:** the command-by-GID path (Track 2) sidesteps
all of this — no labels, no offsets, no occlusion, no label-state
regime. That the click path's behaviour swings this wildly with a UI
toggle is itself an argument for the command path.

## T79 controlled runs (2026-08-06): the label lead did NOT hold up

Three attempts to pin the label-state effect under control, and the
honest outcome is that **it does not replicate** and the click
measurement is too confounded to settle it:

- **Run 1** (operator-dropped, two piles): labels-ON pile failed, but the
  labels-OFF side was **n=1** (a single gem) — no basis.
- **Run 2** (automated): a **drill bug** — the inventory never closed
  (`GatedInput` refuses input through an open panel, and I closed it with
  the wrong primitive), so every click was refused. Zero valid data;
  fixed with `TownLayer.close_panels()` + a hard guard.
- **Run 3** (automated, fixed, within-subjects on one pile): **labels ON
  cleared the whole 8-item pile** — 780 lifted directly, and the rest
  vanished as collateral/neighbour pickups while the schedule worked the
  tight cluster. Only the fix's *side effect* mattered: measuring the
  first items' 8-click schedules **picks up their neighbours**, so the
  pile was consumed before the labels-OFF condition ran (OFF got no
  data). Items all recovered (floor clear).

**What this means, stated plainly:**

1. **The run-2/run-3 gap was not the label flag.** A controlled
   labels-ON pile (T79 run 3) picked up cleanly, the opposite of T76 run
   2's labels-ON pile (7/8 failed) — same drill, same mechanism, same
   tight-pile shape, opposite result. That is **variance**, not a label
   effect. The lead is dead.
2. **Within-subjects is impossible for click pickup**: measuring an item
   consumes its neighbours, so the same pile cannot be measured twice.
   A clean test would need matched *fresh* piles per condition
   (between-subjects), and given (1) it is not worth the runs.
3. **The click path is erratic** — that is the durable finding. Its
   outcome on a pile swings from 1/8 to 8/8 with nothing but noise. You
   cannot tune a reliable bot on a primitive this variable.

**So the label experiments are CLOSED**, and their real contribution is
negative evidence that strengthens the plan's core: command-by-GID (P4)
is deterministic — no labels, no offsets, no collateral, no variance —
and is the only path to reliable pickup. Do not spend more runs tuning
clicks; the payoff is in P4.

(Method note, paid again tonight: two of the three T79 runs were lost to
drill bugs I built blind — a silent refusal branch and the wrong
panel-close primitive. Drills that send input need their close/refusal
paths exercised before they run, not after.)

## The recommendation

Both tracks, in this order, because they are not exclusive — Track 1 is
Track 2's permanent fallback, exactly as kolbot keeps `Misc.click`
behind `Packet.click`:

1. **Separate acquisition from detection** (the operator's structural
   point) — a module whose only job is `acquire(unit_id, budget) ->
   outcome`. Pure refactor, current click mechanism preserved. Unblocks
   everything and is worth doing whichever track wins.
2. **Track 1 wins inside the new module** — tight confirm poll,
   draw-order collection, reposition-on-miss, reordered schedule. Banks
   real reliability at zero architectural risk.
3. **Track 2 as a gated spike** — prove an out-of-process GID pickup in
   an isolated supervised drill; go/no-go; if go, the module adopts it
   as primary and Track 1 becomes the fallback.

## Open questions for the operator — ANSWERED 2026-08-06

1. Is out-of-process memory-write / remote-call actuation on the table?
   **YES** — *"lets try and see. Be ready to rewind all changes we
   make."* So Track 2 is licensed as a spike, on an isolated branch that
   can be abandoned wholesale.
2. Does this supersede the pickup-reliability plan's P3/P4 (the aim fix)?
   **YES.** That plan's P1 (instrumentation — done), P2 (the T76
   calibration — done), and P5 (the item-exception registry) still
   stand; its P3/P4 are absorbed here as Track 1.
3. Appetite for the spike's crash risk in a supervised drill? **YES.**

## Out of scope

- Whitelist / pickit accuracy — a *detection* problem, its own track.
- Muling and telekinesis pickup (kolbot has both; not the necro's need).
- The descent's general speed pass (M6's separate concern).