# Resume point — M5 P3, mid live-verification

Written 2026-07-30 at a conversation handoff. Read this plus
[notes.md](notes.md) (the "Town-layer live campaign" section especially)
and you have the state; `docs/instruction-log.md` R63–R82 and
`docs/drill-log.md` carry the detail.

## Where the milestone is

M5 = the first end-to-end run (Cold Plains clearance, Hell). Phases:

| Phase | State |
|---|---|
| P1 perception extensions | **done**, live-verified |
| P2 input extensions | **done**, live-verified |
| P3 town layer + waypoint | **code done, live verification ~70%** ← here |
| P4 behaviour engine | not started (sim-only when it comes) |
| P5 combat + pickit | not started |
| P6 staged live acceptance | not started |

`306 tests, ruff clean.` Nothing is committed — the whole M5 working
tree is uncommitted by design (no commit was requested).

## The immediate next actions

Two drills are coded, fixed, and **waiting on a live re-run**:

1. **T19 — bot repairs at Charsi.** Needs only WORN GEAR.
   `powershell -File tools\bridge-run.ps1 -Id 068-t19 -Command '& "$HOME\.venvs\pd2bot\Scripts\python.exe" -m drills.t18_t19_repair T19' -TimeoutSec 600`
2. **T20/T21 — merc resurrection.** Needs the MERC DEAD. T20's row is
   already calibrated and baked into config, so **T21 can run alone**:
   `... -m drills.t20_t21_merc_resurrect T21`

Both previously failed; four fixes landed afterwards and neither has
been re-run since. That is the single most valuable thing to do next.

Then, still outstanding for P3:

3. **Waypoint calibration + supervised round trip** — never done. The
   waypoint row hovers were part of the cancelled T8/T9 attempts, so
   `WaypointConfig.row_fractions` is still EMPTY and `waypoint.py` will
   refuse to travel until it is filled. Needs a hover drill (two rows:
   Rogue Encampment, Cold Plains) then a supervised town→Cold
   Plains→town trip. **This is the last big P3 item.**
4. **P3 review gate** — user reviews drill outcomes and approves P4.

## Live-test protocol (how anything gets verified)

The user starts the elevated bridge once per session:

```
powershell -ExecutionPolicy Bypass -File "C:\dev\2026-pd2-bot\2026-pd2-offline-bot\tools\elevated-bridge.ps1"
```

The `-ExecutionPolicy Bypass` child-process form is REQUIRED; running
the script directly fails on this machine's policy.

The agent then drives everything through `tools/bridge-run.ps1`. Drills
live in `drills/`, are built on the `pd2bot/drill.py` harness, and each
announces itself in-game (`TEST T<n> — title [kind]`, instructions, an
input warning, `TEST LIVE`, `TEST CONCLUDED — status`) and appends a row
to `docs/drill-log.md`. A running drill — including a bot looping inside
the town layer — is stoppable with:

```
powershell -File tools\drill-cancel.ps1
```

## Calibrations already measured (all baked into config)

1536x864 window. **Re-run the source drill after any window or
resolution change.**

| What | Value | From |
|---|---|---|
| inventory origin / cell | (0.5301, 0.4385) / (0.0268, 0.0461) | T11 |
| usable inventory grid | 10x4, cells (0,0)-(9,3) | T10 |
| trade/repair row | (0.5879, 0.2072) | T18 |
| repair-all button | (0.4707, 0.7523) | T18 |
| resurrect row (dead-merc only) | (0.5716, 0.2569) | T20 |
| materials tab X button | (0.2188, 0.8426) | T15 |
| waypoint rows | **MISSING** | — |

## Live facts that are easy to lose

- **Charm inventory shares the inventory container**; only the cell
  coordinate (y >= 4) separates it, and this character keeps 24 items
  there. Everything filters through `main_inventory`.
- **The Horadric Cube (kind 564) cannot be shift-clicked** — right-click
  opens it. In `UNMOVABLE_KINDS`; the deposit filters it itself.
- **PD2 renumbered potions**: 610/611 mana, 606 healing, 530/531 rejuv,
  proven by effect (T6). Belt columns are permanent: key 1 mana, 2
  rejuv, 3+4 healing.
- **Rejuvs are materials** and are never drunk or put in the regular
  stash.
- **The materials tab makes the ordinary stash read EMPTY**, and stash
  contents populate progressively — never infer fullness from a count.
  Tab state IS readable: the stash store's item-chain head goes null
  while materials is displayed (T22).
- **Services are paid from the shared stash**, not carried gold; gold is
  a non-topic by user decision.
- NPC ids (T17-verified by proximity): Akara 148, Kashya 150, Charsi
  154, Gheed 147.

## Designed but NOT yet built

The **inventory-management loop** (R75, user-designed) replaces the
current separate stash/refill steps:

    potions to belt -> drink excess healing/mana -> deposit ALL into
    MATERIALS -> switch tab -> deposit ALL into REGULAR -> halt if
    anything remains

Its point is that the game does the classification, so the bot needs no
item taxonomy. Agreed refinements: the materials phase treats "didn't
move" as normal (error only in the final phase), fast-fail timing there,
and tab identification via T22's signal. **Not implemented yet.**

## Suggested opening prompt for a fresh conversation

> Continuing the PD2 bot, milestone M5 phase P3 (town layer). Read
> `docs/plans/2026-07-29-m5-trial-run/RESUME.md` first, then `notes.md`
> in the same directory. The elevated bridge is running and I'm at the
> machine. Next up: re-run T19 (repair — my gear is worn) and T21 (merc
> resurrect — I'll get the merc killed), both of which failed before and
> have unverified fixes. After that, the waypoint calibration and
> supervised round trip, which is the last big P3 item.
