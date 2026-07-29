# Instruction log

Every request the agent has issued to the user, in order, with outcomes —
the raw data for reducing human-in-the-loop load (see the "User request
protocol" in the agent-toolkit skills). Types: `decision` (choose or
approve), `execute` (run what the agent cannot), `verify` (judge reality
by eye), `provision` (supply a resource), `inform` (supply knowledge).

Requests R1–R15 were backfilled on 2026-07-28 when the protocol was
adopted mid-M3; wording is reconstructed, outcomes are exact.

## M1–M2 (pre-protocol, not reconstructed)

M1/M2 requests predate this log. Known shape: review-gate decisions
(plan B reorientation, architecture QA/QB/QC), live-verification
sessions (dump-vs-screen comparisons, UI panel calibration). See those
milestones' planning dirs.

## M3 — navigation

### P3 review gate (map generator blocked)

| ID | Type | Title | Asked | Outcome |
|---|---|---|---|---|
| R1 | decision | Resolve the generator blockage | Choose: supply vanilla 1.13c DLLs / keep stubbing PD2's DLL chain / ship M3 without generated maps | User supplied a better fourth option: SP maps are fixed per character+difficulty, so persist live-read grids instead (explored-map atlas). Generator deferred. |
| R2 | provision | Supply a vanilla 1.13c DLL set | Folder of clean 1.13c game DLLs for the generator | **Withdrawn** — superseded by R1's resolution. |

### Live verification (elevated terminal, user at the machine)

| ID | Type | Title | Asked | Outcome |
|---|---|---|---|---|
| R3 | execute | Gate test in three states | `navdemo gate` with ESC menu open, backgrounded, and `--focus` | PASS 3/3 — refusals correct, allowed state correct. Required a tool fix first (user caught that "game focused + press Enter" was impossible → `--focus` flag added). |
| R4 | execute | Click test, first run | `navdemo click-test --send` in open ground | Undershoot: error (−4, 1). Cause ambiguous (timer vs render scale). |
| R5 | execute | Click test, re-run after watch-until-stop fix | Same command | Same (−4, 1) — not the timer; scale factor confirmed as hypothesis. |
| R6 | execute | Projection calibration | `navdemo calibrate` (12 walks, 8 directions) in open ground | Fitted 20/10 px/subtile (ratio 2.000); bonus discovery: clicks >~320 px complete only 60–70% of distance → waypoint cap justified empirically. |
| R7 | execute | Click test, confirm calibration | `navdemo click-test --send` | PASS — error (0, 1). |
| R8 | execute | Collision dump at a landmark | `collision` beside a map-edge cliff | 0 rooms read — exposed a CollMap layout error (no pMapEnd in this build; grid stored inline at Coll+0x24). |
| R9 | execute | Collision chain diagnosis | `collision --debug` | Field-by-field dump identified the true layout; tile/subtile invariant adopted as the integrity check. |
| R10 | verify | Collision vs eyes | Re-run `collision`; compare walls/cliff against the screen | PASS — cliff reported 1 subtile screen-right, matching reality. |
| R11 | verify | Collision tracks movement | Walk ~20 subtiles, re-run, compare | PASS — terrain fixed in world coords across dumps (cliff at x=5953 in both), view followed player. |
| R12 | execute | Survey walk, first attempt | `navigate --survey` around Cold Plains waypoint | 247 rooms "recorded" — user's monster-collision hypothesis confirmed a churn bug (occupancy bits persisted); transient-mask fix added. |
| R13 | execute | Survey walk, post-fix | Delete `maps/`, re-survey same area | PASS — 34 rooms. |
| R14 | execute | Atlas persistence checks | `--survey` standing still; `Get-ChildItem maps`; save-exit → new game → `--survey` | PASS — 0 standing still; same seed folder after full game cycle; 125 re-records in fresh game were byte-identical churn (file size unchanged), benign, now instrumented. |
| R15 | execute | Acceptance demo, first attempt | `navigate --demo` | FAIL — demo aimed at a fixed offset in unsurveyed ground; demo rewritten to pick known/walkable/reachable targets. |
| R16 | execute | Survey current spot, then demo ×5 | `--survey` loop where standing, then `navigate --demo` five times | **PASS 5/5** (survey read 0 — ground already known from R15's walk). 10 walks of ~60 subtiles, all arrived; 2.9–6.7 s each; re-click ladder fired 7 times incl. absorbing the user touching the mouse mid-demo-1; demo 3 showed a full stuck→re-plan→arrive cycle. M3 acceptance criterion met. |

### M3 closeout

| ID | Type | Title | Asked | Outcome |
|---|---|---|---|---|
| R17 | execute | Ground-item live check (M2 leftover) | Drop an item, `dump -v`, confirm listed, pick up, confirm gone | **Found a real bug** — a *carried* item reported as on the floor "at (5, 0)" (its inventory grid slot), unchanged by pickup. Cause: ItemData's location byte (BH header, 0x45) does not mean what the header says in this build. Filter switched to the unit MODE (onGround=3/dropping=5, kolbot sdk); regression test added. Third header-vs-reality correction of M3. |
| R19 | execute | Ground-item re-check after mode filter | Same procedure: drop, dump, pick up, dump | False positive gone (0 items with nothing dropped) but **false negative**: a dropped potion was not detected. Mode constants verified correct against kolbot sdk, so the cause is elsewhere → raw-field diagnostic added (`dump --items`) rather than a third guess. |
| R20 | execute | Dump raw item-unit fields | `dump --items` with an item on the ground, then after picking it up | *Open.* |
| R21 | inform | Mercenary/summons counted as monsters | User observed the dump reporting their Rogue merc as a monster and predicted summons would too; noted units under player control also do not collide | **Confirmed before testing** — the reported `type 271` is exactly kolbot's `sdk.mercs.Rogue`. D2 files mercs/summons/friendly NPCs as unit type 1; only stat 172 (Alignment==2) separates them. Scans now split `monsters` (hostile) from `allies`; 2 regression tests. Collision point noted: ally bits are outside the walkability mask, so no pathing impact. |
| R22 | verify | Confirm ally split live | Summon skeletons, run `dump -v`, check monsters vs "yours" | Partly — split works, but exposed R23's defects. |
| R23 | execute | Verify hash-table enumeration | `dump -v` and `dump --items` with skeletons out and an item dropped, then after pickup | **Ground items fixed and confirmed**: the same unit reads `mode=3` at world (5274,5725), then `mode=0` at inventory slot (7,3) after pickup. Also revealed why the original filter failed — ground items carry `loc@0x45=247`, not 255, so it rejected real drops while accepting belt potions. **New defect found**: the hash table is global (whole stash, other levels, expired summons), so the ally list showed phantoms (`summon 0`, `summon 6`) and the merc was missing. Added a perception-radius filter (80 subtiles) and a `--monsters` diagnostic. |
| R24 | execute | Verify locality filter; locate the merc | `dump -v` then `dump --monsters` with merc and skeletons out | **PASS** — `yours: 3 (summon, summon, rogue 8%) (+3 dead)`. Merc found. But the raw dump showed heavy duplication (49 rows for ~13 units): units are reachable from several bucket heads, so the iterator now de-duplicates by unit id. |
| R25 | execute | Confirm de-duplication | `dump --monsters` and `dump -v` | **PASS** — 49 → 14 rows, each unit once; merc explicit as `271 … MERC rogue, ally` at 128/1620 hp (7.9%, matching the 8% summary); 6 allies + 8 dead hostiles = 14, fully consistent with the `-v` view. Perception verified end to end. |
| R18 | decision | Commit M3? | Approve the single conventional commit of the milestone (repo) and a separate commit of the agent-toolkit protocol changes | **Yes to both.** Project: `fa81028` on main (43 files, +6002/−89). agent-toolkit: `d585250`. Both worktrees clean; neither pushed. |

## Observations so far (for the reduction analysis)

- 12 of 15 resolved requests are `execute`/`verify`, and all of those
  exist because of one boundary: **live checks need an elevated terminal
  + physical presence**. The single highest-leverage change would be an
  elevated execution path for the agent (e.g. the user launches one
  elevated session the agent can drive), which would collapse R3–R15
  into agent-side work with the user only supervising input-sending
  steps.
- The two `decision` points were both genuine — architecture direction
  and a blocked dependency — and would not benefit from automation.
- Several `execute` rounds were repeats caused by tool defects the run
  itself exposed (R4→R5→R6→R7, R12→R13). That is the loop working as
  designed (reality-testing), but better first-run instrumentation
  (watch-until-stop, per-bit diagnostics) would have halved the round
  trips; both fixes are now permanent tooling.
