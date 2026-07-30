# Drill log

One row per live-test run (harness: `pd2bot/drill.py`). Statuses:
PASS / FAILED / ABORTED / NOT STARTED. The instruction log carries the
full request context; this file is the quick mechanical record.

Rows T1–T10 are a backfill of the live tests run before the harness
existed (M5 P1–P3, bridge commands 030–049); dates and outcomes are
exact, run details live in `docs/instruction-log.md` under the cited
R-numbers.

| Test | Run | Date | Title | Kind | Status | Result |
|---|---|---|---|---|---|---|
| T1 | 1 | 2026-07-29 | Skill-id capture, F1–F6 cycle | human calibration | PASS | All 7 ids captured incl. PD2's Blood Warp 367, Desecrate 83 (R52-A) |
| T2 | 1 | 2026-07-29 | Bone Armor cast-and-diff | human calibration | PASS | Stats 132/133 confirmed, fixed-point, 866 at max (R52-B) |
| T3 | 1 | 2026-07-29 | Potion shuffle, container classification | human calibration | PASS | mode/loc/node consistent at every hop; cursor items leave the chain (R52-C) |
| T4 | 1 | 2026-07-29 | Belt kinds by column | perception | PASS | PD2 renumbered potions; ids captured (R52/R53) |
| T5 | 1 | 2026-07-29 | NPC identification walk | human calibration | PASS | Akara 148 appeared on approach; 5 NPC ids verified (R52-D) |
| T6 | 1 | 2026-07-29 | Potion-type proof (drain + key 1) | human calibration | PASS | 610/611 mana, 606 healing, 530/531 rejuv — proven by effect (R54) |
| T7 | 1 | 2026-07-30 | P2 four-phase input drill | bot control | PASS | Panel slots calibrated; verified switch; first autonomous cast + drink; refusals correct (R55) |
| T8 | 1 | 2026-07-30 | Hover calibration, five targets | human calibration | FAILED | Tool defect: no re-arm, capture 2 fired on the resting cursor (R57) |
| T9 | 1 | 2026-07-30 | Anchor calibration (max-cell anchors) | human calibration | ABORTED | Cancelled pre-run: charm inventory would have skewed the anchors (R59) |
| T10 | 1 | 2026-07-30 | Four-corner inventory calibration | human calibration | PASS | Usable grid 10x4; origin (0.5257, 0.4404), pitch 42.0x40.3 px, worst residual 3.5 px; charm space = same container, y>=4 (R60) |
| T11 | 1 | 2026-07-29 17:31 | Snake-sweep inventory calibration | human calibration | PASS | 39 cells, 78 samples; origin (0.5301, 0.4385), cell (0.0268, 0.0461); worst per-cell residual 11.5 px; origin delta vs T10 (+6.8, -1.6) px |
| T12 | 1 | 2026-07-30 14:59 | Heal at Akara | bot control | FAILED | TownError: Akara not in perception range — walk the preamble closer first |
| T13 | 1 | 2026-07-30 15:00 | Stash deposit with verification | bot control | FAILED | NavigationError: input stayed refused for 10.0s: a blocking panel is open (stash) — a click would land on the panel, not the world |
| T14 | 1 | 2026-07-30 15:00 | Belt refill from inventory | bot control | PASS | moved 3; belt columns now {0: 2, 1: 1, 2: 4, 3: 1}; rejuvs 1; belt: 3 moved, minimums hold |
| T12 | 2 | 2026-07-30 15:08 | Heal at Akara | bot control | FAILED | NavigationError: input stayed refused for 10.0s: a blocking panel is open (npc_menu) — a click would land on the panel, not the world |
| T13 | 2 | 2026-07-30 15:14 | Stash deposit with verification | bot control | FAILED | StashFull: deposit failed after 2 attempts |
| T17 | 1 | 2026-07-30 15:19 | Identify town NPCs by proximity | human calibration | PASS | AKARA=148@(5922, 5714); KASHYA=150@(5877, 5743); CHARSI=154@(5824, 5724); GHEED=147@(5828, 5782) |
| T12 | 3 | 2026-07-30 15:23 | Heal at Akara | bot control | PASS | 1265/1265 hp, 207/378 mana -> 1265/1265 hp, 378/378 mana; heal: vitals read full |
| T13 | 3 | 2026-07-30 15:23 | Stash deposit with verification | bot control | FAILED | TownError: stash object not in perception range |
| T13 | 4 | 2026-07-30 15:32 | Stash deposit with verification | bot control | PASS | deposited 7 of 8; 1 junk left in grid; charm space untouched at 24 items; stash: skipped 1 unmovable (cube/quest); stash: 7 deposited |
| T18 | 1 | 2026-07-30 15:33 | Repair UI calibration at Charsi | human calibration | PASS | trade row (0.5879, 0.2072); repair-all (0.4707, 0.7523); 7 repairable items, 0 worn, 0 durability missing; lowest 100% |
| T19 | 1 | 2026-07-30 15:33 | Bot repairs at Charsi | bot control | ABORTED | nothing is worn — go take some durability damage and re-run (a repair with nothing to repair proves nothing) |
| T15 | 1 | 2026-07-30 15:34 | Materials tab: find the state signal, calibrate the X button | human calibration | PASS | 4 tab transitions seen; signal = stash_items; X button fraction (0.2188, 0.8426); first transition: stash item ids: 18 -> 0 (18 gone, 0 new); storage bytes: [(7, 1)] -> [] |
| T16 | 1 | 2026-07-30 15:34 | Materials tab: bot toggles and verifies | bot control | PASS | toggled twice via (336, 728); switch OK, switch back OK |
| T22 | 1 | 2026-07-30 16:22 | Find a reliable stash-tab signal | perception | PASS | 6 toggles; channels moving every time: store array, stash items, location bytes |
| T19 | 2 | 2026-07-30 16:25 | Bot repairs at Charsi | bot control | FAILED | TownError: Charsi's dialog never opened |
| T20 | 1 | 2026-07-30 16:26 | Merc resurrect row calibration (dead-merc state only) | human calibration | PASS | resurrect row (0.5423, 0.2963); merc dead; 986442 gold available |
| T21 | 1 | 2026-07-30 16:32 | Bot resurrects the mercenary | bot control | ABORTED | the merc is alive again — T20's row position belongs to the dead-merc menu and must not be clicked in this state (R56) |
| T19 | 3 | 2026-07-30 16:36 | Bot repairs at Charsi | bot control | FAILED | TownError: the trade/repair screen never opened — the dialog row may have moved (NPC menus are state-dependent, R56) |
| T20 | 2 | 2026-07-30 16:38 | Merc resurrect row calibration (dead-merc state only) | human calibration | PASS | resurrect row (0.5716, 0.2569); merc dead; 937504 gold available |
