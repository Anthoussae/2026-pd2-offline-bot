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

### Post-milestone housekeeping

| ID | Type | Title | Asked | Outcome |
|---|---|---|---|---|
| R26 | decision | Relocate agent-toolkit to `C:\dev\agent-toolkit`? | Move the cross-project toolkit out of the pd2 workspace folder, or leave it | **Move it.** Moved; repo intact; `install.sh` verified from the new home; path pointers updated in `~/.claude/CLAUDE.md` and memory. Same conversation also established: Windows-only development (Mac framing removed from project docs), toolkit = single source of truth with pull-first editing, and the multi-machine update model documented in the toolkit README (`287f82a`). |
| R18 | decision | Commit M3? | Approve the single conventional commit of the milestone (repo) and a separate commit of the agent-toolkit protocol changes | **Yes to both.** Project: `fa81028` on main (43 files, +6002/−89). agent-toolkit: `d585250`. Both worktrees clean; neither pushed. |

## M4 — game cycle

### Planning discovery

| ID | Type | Title | Asked | Outcome |
|---|---|---|---|---|
| R27 | decision | M4 planning confirmations (Q1–Q8) | Batched table: OOG perception via D2Win control list, separate MenuInput guard, chicken scope, merc chicken deferral, door deferral, corpse retrieval, difficulty-from-memory, focus-loss policy | Q1–Q5, Q8 **yes**. Q6 **no — scope change**: on death the bot stops completely and awaits a human; corpse retrieval/recovery deferred (low priority). Q7 **no** (Hell-only project), with caveat: blind-fallback path adds a difficulty sanity read. User also supplied the survival toolkit (blood warp, potions, bone shield ≥75%, ESC-exit, walk-away, 3 revives) → designed as M5's survival layer; robustness-before-live-runs is a standing M5 constraint. |
| R28 | decision | How to live-test death handling | Choose: throwaway low-level char in Normal / accept one deliberate Hell death on MaqiuDoubing / simulation only | **Withdrawn** — superseded by R27/Q6: death→full-stop has no recovery sequence to live-test; simulation covers detection→halt. |
| R29 | decision | Approve the M4 phase table | Five phases: OOG perception / menu input / game-cycle FSM / safety monitor / docs+teach | **Approved** (`lgtm`), with one amendment: user convinced by the map-poisoning argument — the post-join difficulty read becomes an **unconditional** guard on every game entry (was: only if the blind fallback landed). |

### M4 live-session setup

| ID | Type | Title | Asked | Outcome |
|---|---|---|---|---|
| R30 | execute | Open an elevated terminal, verify attach | Run-as-administrator PowerShell; `cd` to repo; `python -m pd2bot.dump` against client at char select | First run failed on an **agent error**: bare `python` resolves to a stale system 3.8 without pymem — the canonical env is the venv at `~\.venvs\pd2bot` (documented in README; agent should have checked before writing the command). Corrected command reissued with the venv's full path. Superseded before re-run: user proposed giving the agent direct elevated access instead (→ R31), exactly the reduction this log's observations predicted. |
| R31 | decision | Choose the agent's elevated-access mechanism | Options: (A) elevated command-runner bridge the agent drives, (B) resume session in an elevated `claude` CLI, (C) run the desktop app itself as administrator | **A — the bridge** (agent recommendation accepted). Trust trade acknowledged: agent commands execute elevated without per-command human review while the loop runs. Script: `tools/elevated-bridge.ps1`; queue at `%LOCALAPPDATA%\pd2bot-bridge`. |
| R32 | execute | Start the elevated bridge | One command in the existing elevated window; leave it running for the whole session | **Up.** Elevation check through the bridge: True, correct user/cwd, PS 5.1. Found one defect: exit codes never populated (Start-Process + timed WaitForExit quirk) — fixed in the script, restart needed (→ R33). |
| R33 | execute | Restart the bridge (exit-code fix) | Ctrl+C in the bridge window, re-run the same start command | **Done** (needed a re-ask — the first "restart" turned out to be the old instance still running; the fresh banner is the tell). First fix (extra WaitForExit) was insufficient (local repro); real fix: exit code in-band via wrapper shell + sidecar file. Verified through the bridge: probe `exit: 7`; then `pd2bot.dump` → `exit: 0`, attached pid 24996, correctly reported not-in-a-game at char select. **R30's original goal achieved agent-side; the elevated round-trip era ends here** — from R34 on, live checks are agent-driven and user requests should drop to game-side actions only (be at the machine, keep the game foreground, judge by eye). |

### M4 implementation — P1 (OOG perception)

Bridge era: commands run agent-side (bridge ids in parentheses); user
requests cover game-side actions only. First live dump (006, char
select) passed outright: screen classified, 26 controls, button texts
clean, kolbot-table coordinates exact, state semantics confirmed
(disabled CONVERT TO reads state 4). Control-list strategy confirmed —
no fallback needed.

| ID | Type | Title | Asked | Outcome |
|---|---|---|---|---|
| R34 | execute | Walk the menu screens for the OOG watcher | With the transition watcher running (bridge 007/009/010/011): save-and-exit → menu screens → re-enter a Hell game | **PASS** (4th attempt; the loop working as designed). Attempt 1: agent defect (script run from %TEMP%, PYTHONPATH fix). Attempt 2: instructions read as gameplay, user played instead — bonus: `in_game` stayed rock-stable through waypoint travel and combat. Attempt 3: user called away, window expired. Attempt 4 (011): **every transition classified, zero unknowns** — in_game→loading→main_menu→char_select→difficulty→char_select→main_menu→char_select→difficulty→in_game(2). **User-found discovery: save-and-exit lands at MAIN MENU in offline SP**, not char select as kolbot's (multiplayer-lore) flow implies — P3's leave sequence updated to expect it. Alt-tabbing irrelevant to memory reads, confirmed. ERROR_POPUP not safely triggerable live; covered by kolbot fingerprint + unit test only. One-shot 008 verified difficulty=2 (Hell) in-game. |

### M4 implementation — P2 (menu input)

Complement-guard refusal verified live agent-side (bridge 013): in a
game, no ESC menu → `REFUSED … GatedInput's job`. (Bridge 012 was lost
to PowerShell quote-mangling of inline `python -c`; bridge commands now
always write a temp .py first.)

| ID | Type | Title | Asked | Outcome |
|---|---|---|---|---|
| R35 | execute | ESC-menu probe, then hands-off click test | Bridge 014–017 across three reruns: probe the ESC menu's control visibility; hands-off click test at char select | Took three rounds — attempts 1–2 lost to probe windows racing the user's reading speed (fixed: single long-window state-driven scripts). Results: **ESC menu is NOT in the control list** (P3 needs calibrated fixed coordinates); first bot menu click **missed 140 px right** of OK — naive stretch model wrong. |
| R36 | execute+verify | Hover the OK button to confirm the corrected projection | Steady 2 s hover on OK's center; probe compares against the pillarbox model and only clicks if within 6 px | **PASS** — client 1536×864; menus are aspect-fit 1.44× with 192 px pillarbars (the config's mysterious 1.44 from M3, now explained: it is the MENU scale, not the world scale). Hover delta (−1, +2). Auto click test: OK clicked at (1187,799), difficulty popup appeared, bot's own ESC returned to char_select. User confirmed visually. |

### M4 implementation — P3 (game cycle)

| ID | Type | Title | Asked | Outcome |
|---|---|---|---|---|
| R37 | execute | Hover "Save and Exit Game" for calibration | Enter game, ESC, steady 2 s hover on the button, don't click (bridge 020) | **Done** — (751, 366) at 1536×864 → client-rect fractions (0.4889, 0.4236); stored in CycleConfig (ESC menu is not a readable control, R35). |
| R38 | execute | Hands off for the first autonomous cycle | Focus the game, hands off; bot does ESC → Save and Exit → menus → OK → HELL (bridge 021 expired unused while user away; rerun 022) | **PASS** — leave → main_menu → create → difficulty 2, fresh seed. First fully autonomous game cycle; user watched it live ("worked perfectly to my eye"). |
| R39 | execute | Acceptance run: 3 unattended cycles | Focus the game, hands off ~3 min; `python -m pd2bot.cycle --games 3 --dwell 10` (bridge 023) | **PASS 3/3** — `[CVRL]` × 3: created, Hell-verified, dwelled as MaqiuDoubing, left cleanly. No retries, no focus interventions. M4 acceptance criterion #1 met. |

| R40 | decision | P3 review gate | Approve the cycle (3/3 acceptance, one skipped live test: deliberate wrong-difficulty entry judged all-risk-no-information) and proceed to P4 | **Approved** (`ok`). |

### M4 implementation — P4 (safety monitor) + chat channel

Mid-milestone addition at user request (before R41 ran): an in-game
chat channel (`pd2bot/chat.py`) so live-test instructions appear in the
game instead of requiring alt-tabs. Guard: nothing is typed until the
chat console (UI panel 0x05) is verified open — an unopened console
would turn text into hotkey presses; re-verified per character.

| ID | Type | Title | Asked | Outcome |
|---|---|---|---|---|
| R41 | execute | Chicken demo + inert run (pre-chat version) | Focus game, cast until mana dips; then hands off for 2 normal cycles (bridge 024/025) | **Superseded** before running (windows expired during the chat-channel detour) — reissued as R43 with in-game chat instructions. |
| R42 | execute | Chat probe | Enter a Hell game, focus, hands off; bot posts a message to the in-game chat (bridge 026) | **PASS** — message posted; the alt-tab-free instruction channel exists. |
| R43 | execute | Chicken demo with in-game instructions, then inert run | Bot chats the instructions; user casts until mana dips; bot flees on its own; then 2 hands-off default-threshold cycles (bridge 027–029) | **PASS both.** Chicken: tripped at `mana 340/378 (90%) <= 99%`, announced in chat, left the game autonomously — full chicken pipeline live at zero risk. Inert: 2/2 `[CVRL]`, monitor silent at defaults. (One focus-timeout rerun in between; the chat channel removed the alt-tab problem it was built for.) User flagged the 90%-vs-99% gap; diagnosis: not a defect — 0.4 s sampling + burst mana costs (and possibly a sub-100% start) mean the first at-or-below observation can sit well past the threshold. That floor-trigger semantic is the production behavior we want for life chicken (a hard hit crosses 50% mid-frame; the monitor reacts to the crossing within one tick). |

### M4 closeout

| ID | Type | Title | Asked | Outcome |
|---|---|---|---|---|
| R45 | inform | Carried-vitals chicken loop risk | User flagged post-acceptance: PD2 does not heal between games, so below-threshold vitals at entry → chicken → new game → chicken, ad infinitum; also explains the demo's "instant" trip (mana spent in the *previous* game carried in) | **Confirmed real** (M4's dwell loop was safe only via town suppression; M5's real runs were exposed). Fixed before commit: `max_consecutive_chickens` backstop (default 2) halts the loop loudly, streak resets on any clean run; +2 tests (195 total). Durable fix assigned to M5: town-heal preamble (healer NPC before leaving town, kolbot-style) — recorded in `_DONE.md` follow-ups and game-cycle.md. |
| R44 | decision | Commit M4? | Approve one conventional commit of the milestone (code + docs + archived plan; now 195 tests green incl. the R45 backstop) | *Open.* |

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
