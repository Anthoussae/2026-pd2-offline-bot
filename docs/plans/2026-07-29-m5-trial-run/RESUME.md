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
| P3 town layer + waypoint | **COMPLETE — awaiting the review gate** ← here |
| P4 behaviour engine | not started (sim-only when it comes) |
| P5 combat + pickit | not started |
| P6 staged live acceptance | not started |

`346 tests, ruff clean.` Nothing is committed — the whole M5 working
tree is uncommitted by design (no commit was requested).

## The immediate next actions

**P3 is functionally complete.** Every town step, the waypoint round
trip, and the full R75 inventory loop (belt-fill, drink, materials,
regular, gold — all live-proven, T35/T37) run through the production
`run_preamble`, which is now heal -> repair -> manage_inventory -> merc
and takes no keep-predicate: the game classifies the items. Full
coverage was demonstrated across a halted run and its resume (T27 runs
136+137, one staged world): heal, repair, belt, drink, deposits, the
Tome of Identify, gold, merc — and the halt/resume pair incidentally
proved the preamble is resumable, since every step is conditional on
the world rather than on a checklist.

Late-session structural fixes worth knowing before P4:

- **Navigator-level click avoidance** (R111): travel clicks aimed
  within 4 subtiles of any interactive unit (objects AND NPCs, read
  fresh per click) are nudged 6 clear. This ended the waypoint-misclick
  loop after two positional recoveries failed. Monsters deliberately
  not avoided.
- **The modifier race** (R113): shift and click sent in the same frame
  can resolve as an UNMODIFIED click — invisible on potions (a naked
  right-click just drinks), discovered when it CAST a Tome of Identify.
  `_MODIFIER_SETTLE_S` now flanks every modified click in PanelInput
  and GatedInput's stand-still path (M5 combat would have hit it).
- **NPC dialog rows are ordinals, not positions** (R104): arrows +
  Enter, highlight opens on row 1 and wraps. Kashya's resurrect is row
  2 of 4 IN THE DEAD-MERC MENU ONLY (alive, row 2 is HIRE — R56).
- **Gold's amount dialog raises no panel flag** (T37): undetectable,
  ungateable; verify by balance, and a stray Enter opens the chat
  console — deposit_gold clears it.

Remaining: **the P3 review gate** — user reviews drill outcomes and
approves P4 (behaviour engine, sim-only). The /teach step for this
cycle has not been done yet either.

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

Panel click targets live in `pd2bot/uipoints.py` as named `UIPoint`s, each
carrying the provenance of its measurement; grid geometry stays in
`TownConfig`. **Every point below was proved by its effect, not by the
click landing.**

| What | Value | From |
|---|---|---|
| inventory origin / cell | (0.5301, 0.4385) / (0.0268, 0.0461) | T11 |
| usable inventory grid | 10x4, cells (0,0)-(9,3) | T10 |
| charsi.trade_repair | **keyboard row 2 of 3** | T34/T19 — no position at all |
| charsi.repair_all | (0.4648, 0.7650) | T25 — durability to 0 |
| waypoint.cold_plains | (0.3249, 0.2928) | T25 — arrived area 3 |
| waypoint.rogue_encampment | (0.3197, 0.2384) | T25 — arrived area 1 |
| stash.materials_tab | (0.2188, 0.8426) | T15/T16 |
| kashya.resurrect | **keyboard row 2 of 4** (dead-merc menu) | R105/T21 |

Area ids confirmed live: **Rogue Encampment 1, Cold Plains 3**.

**NPC dialog rows carry no position at all.** They are drawn relative
to the NPC and NPCs wander, so no fraction and no anchored offset can
locate one — four separate attempts each verified by effect when taken
and each stale by the next opening. They are chosen by ORDINAL instead:
arrows move the highlight, Enter selects, the highlight opens on row 1
and wraps (T34). Kashya's index differs by merc state, since the
resurrect row only exists while the merc is dead (R56) — alive, row 2
is HIRE.

**Do not trust a calibration whose drill is not in the current tree.**
T18's and T20's numbers were discarded wholesale (R86): they were taken
with a capture that armed immediately and recorded the cursor resting on
the NPC the user had just clicked.

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

## The R75 inventory loop (user-designed, BUILT and live-proven)

`TownLayer.manage_inventory`: potions to belt (FILL, not top-up — R107)
-> drink excess healing/mana -> deposit ALL into MATERIALS (fast-fail;
"didn't move" is the expected answer there) -> switch tab -> deposit ALL
into REGULAR (a leftover halts loudly) -> deposit gold -> close. The
game does the classification, so the bot has no item taxonomy to go
stale. Rejuvs are never drunk; they fall through to materials once the
belt's rejuv column is full. The Cube is exempt and named in the log
even when it is all that remains.

## Suggested opening prompt for a fresh conversation

> Continuing the PD2 bot, milestone M5. Read
> `docs/plans/2026-07-29-m5-trial-run/RESUME.md` first, then `notes.md`
> in the same directory (the calibration-crisis section especially).
> P3 (town layer) is COMPLETE and live-proven end to end; we are at the
> P3 review gate. Next: the gate decision, the /teach step for this
> cycle, and then P4 — the behaviour engine, sim-only.
