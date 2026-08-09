# Request index

One line per user request, newest last, appended when the request is
issued. Scanning and counting only — details and outcomes live in
[instruction-log.md](instruction-log.md).

Backfilled 2026-08-01 from the instruction log; entries before the
format change carry no timestamp and no M/P labels (the log's section
headings, noted in parentheses, say roughly where they fell).

- R1 [decision] Resolve the generator blockage (P3 review gate (map generator blocked))
- R2 [provision] Supply a vanilla 1.13c DLL set (P3 review gate (map generator blocked))
- R3 [execute] Gate test in three states (Live verification (elevated terminal, user at the machine))
- R4 [execute] Click test, first run (Live verification (elevated terminal, user at the machine))
- R5 [execute] Click test, re-run after watch-until-stop fix (Live verification (elevated terminal, user at the machine))
- R6 [execute] Projection calibration (Live verification (elevated terminal, user at the machine))
- R7 [execute] Click test, confirm calibration (Live verification (elevated terminal, user at the machine))
- R8 [execute] Collision dump at a landmark (Live verification (elevated terminal, user at the machine))
- R9 [execute] Collision chain diagnosis (Live verification (elevated terminal, user at the machine))
- R10 [verify] Collision vs eyes (Live verification (elevated terminal, user at the machine))
- R11 [verify] Collision tracks movement (Live verification (elevated terminal, user at the machine))
- R12 [execute] Survey walk, first attempt (Live verification (elevated terminal, user at the machine))
- R13 [execute] Survey walk, post-fix (Live verification (elevated terminal, user at the machine))
- R14 [execute] Atlas persistence checks (Live verification (elevated terminal, user at the machine))
- R15 [execute] Acceptance demo, first attempt (Live verification (elevated terminal, user at the machine))
- R16 [execute] Survey current spot, then demo ×5 (Live verification (elevated terminal, user at the machine))
- R17 [execute] Ground-item live check (M2 leftover) (M3 closeout)
- R18 [decision] Commit M3? (Post-milestone housekeeping)
- R19 [execute] Ground-item re-check after mode filter (M3 closeout)
- R20 [execute] Dump raw item-unit fields (M3 closeout)
- R21 [inform] Mercenary/summons counted as monsters (M3 closeout)
- R22 [verify] Confirm ally split live (M3 closeout)
- R23 [execute] Verify hash-table enumeration (M3 closeout)
- R24 [execute] Verify locality filter; locate the merc (M3 closeout)
- R25 [execute] Confirm de-duplication (M3 closeout)
- R26 [decision] Relocate agent-toolkit to `C:\dev\agent-toolkit`? (Post-milestone housekeeping)
- R27 [decision] M4 planning confirmations (Q1–Q8) (Planning discovery)
- R28 [decision] How to live-test death handling (Planning discovery)
- R29 [decision] Approve the M4 phase table (Planning discovery)
- R30 [execute] Open an elevated terminal, verify attach (M4 live-session setup)
- R31 [decision] Choose the agent's elevated-access mechanism (M4 live-session setup)
- R32 [execute] Start the elevated bridge (M4 live-session setup)
- R33 [execute] Restart the bridge (exit-code fix) (M4 live-session setup)
- R34 [execute] Walk the menu screens for the OOG watcher (M4 implementation — P1 (OOG perception))
- R35 [execute] ESC-menu probe, then hands-off click test (M4 implementation — P2 (menu input))
- R37 [execute] Hover "Save and Exit Game" for calibration (M4 implementation — P3 (game cycle))
- R38 [execute] Hands off for the first autonomous cycle (M4 implementation — P3 (game cycle))
- R39 [execute] Acceptance run: 3 unattended cycles (M4 implementation — P3 (game cycle))
- R40 [decision] P3 review gate (M4 implementation — P3 (game cycle))
- R41 [execute] Chicken demo + inert run (pre-chat version) (M4 implementation — P4 (safety monitor) + chat channel)
- R42 [execute] Chat probe (M4 implementation — P4 (safety monitor) + chat channel)
- R43 [execute] Chicken demo with in-game instructions, then inert run (M4 implementation — P4 (safety monitor) + chat channel)
- R44 [decision] Commit M4? (M4 closeout)
- R45 [inform] Carried-vitals chicken loop risk (M4 closeout)
- R46 [decision] M5 planning confirmations (Q1–Q8) (Planning discovery)
- R47 [inform] Character kit questionnaire (Planning discovery)
- R48 [decision] Belt refill strategy for M5 (Planning discovery)
- R49 [decision] Reflex-ladder thresholds (incl. chicken) (Planning discovery)
- R50 [decision] Approve the M5 phase table (Planning discovery)
- R51 [execute] Start the bridge + enter a Hell town game (M5 implementation — P1 (perception extensions))
- R52 [execute] P1 live-verification drills (in-town) (M5 implementation — P1 (perception extensions))
- R53 [inform] Name the PD2 potion kinds (M5 implementation — P1 (perception extensions))
- R54 [execute] Potion-type proof drill (M5 implementation — P1 (perception extensions))
- R55 [execute] P2 live drills (town, chat-guided) (M5 implementation — P2 (input extensions))
- R56 [inform] Kashya's menu is state-dependent (M5 implementation — P2 (input extensions))
- R57 [execute] P3 hover calibration (5 targets, chat-guided) (M5 implementation — P3 (town layer + waypoint))
- R58 [execute] P3 hover calibration, re-run after the re-arm fix (M5 implementation — P3 (town layer + waypoint))
- R59 [execute] P3 calibration with memory-identified anchors (M5 implementation — P3 (town layer + waypoint))
- R60 [execute] Four-corner inventory calibration (user-designed) (M5 implementation — P3 (town layer + waypoint))
- R61 [execute] Snake-sweep inventory calibration (T11, dense pass) (M5 implementation — P3 (town layer + waypoint))
- R62 [decision] Approve the bot-control town drills (T12-T14) (M5 implementation — P3 (town layer + waypoint))
- R63 [execute] Run the T12-T14 town-step suite (M5 implementation — P3 (town layer + waypoint))
- R64 [inform] PD2 shift+right-click semantics and the materials tab (M5 implementation — P3 (town layer + waypoint))
- R65 [execute] Next battery: T12/T13 re-run + T15/T16 materials tab (M5 implementation — P3 (town layer + waypoint))
- R66 [inform] T12 walked to Kashya, not Akara (M5 implementation — P3 (town layer + waypoint))
- R67 [inform] The Horadric Cube cannot be shift-clicked (M5 implementation — P3 (town layer + waypoint))
- R68 [execute] Battery: T17 NPC identification, then materials tab, then T12/T13 re-run (M5 implementation — P3 (town layer + waypoint))
- R69 [execute] Re-run T12/T13, then the materials tab suite (M5 implementation — P3 (town layer + waypoint))
- R70 [inform] Add repairing to the town chores (M5 implementation — P3 (town layer + waypoint))
- R71 [decision] Repair every game rather than on a durability threshold (M5 implementation — P3 (town layer + waypoint))
- R72 [execute] Pending battery: T13 re-run, T18/T19 repair, T15/T16 materials (M5 implementation — P3 (town layer + waypoint))
- R73 [decision] Merc resurrection drills built (T20/T21) (M5 implementation — P3 (town layer + waypoint))
- R74 [execute] T19 needs worn gear (M5 implementation — P3 (town layer + waypoint))
- R75 [decision] Inventory-management loop design (M5 implementation — P3 (town layer + waypoint))
- R76 [decision] Gold reserve policy (raised by the agent) (M5 implementation — P3 (town layer + waypoint))
- R77 [execute] Two new probes: T22 stash-tab signal, T23 gold deposit (M5 implementation — P3 (town layer + waypoint))
- R78 [inform] T19 never clicked Charsi; T21 looped chatting to Kashya (M5 implementation — P3 (town layer + waypoint))
- R79 [execute] Cancel the running drills (M5 implementation — P3 (town layer + waypoint))
- R80 [inform] T19 still never opened the trade screen; T21 resurrected the merc then looped (M5 implementation — P3 (town layer + waypoint))
- R81 [execute] Restart the bridge (M5 implementation — P3 (town layer + waypoint))
- R82 [execute] Restart the bridge (corrected command) (M5 implementation — P3 (town layer + waypoint))
- R83 [inform] Conversation handoff (M5 implementation — P3 (town layer + waypoint))
- R84 [verify] Window in for T19 (repair) with worn gear (M5 implementation — P3 (town layer + waypoint))
- R85 [inform] Name the test in the in-game failure line; T19's two causes as watched (M5 implementation — P3 (town layer + waypoint))
- R86 [verify] Run the T24 Charsi battery (user's suggestion) (M5 implementation — P3 (town layer + waypoint))
- R87 [decision] Redesign the calibration: full human control, and transferable abstractions (M5 implementation — P3 (town layer + waypoint))
- R88 [verify] Run T25 charsi (M5 implementation — P3 (town layer + waypoint))
- R89 [inform] Chat into an open NPC dialog selects a dialog option (M5 implementation — P3 (town layer + waypoint))
- R90 [decision] Waypoint calibration in Hell Cold Plains: go or hold? (M5 implementation — P3 (town layer + waypoint))
- R91 [execute] Calibrate the resurrect row in the dead-merc window (M5 implementation — P3 (town layer + waypoint))
- R92 [execute] Restart the elevated bridge (M5 implementation — P3 (town layer + waypoint))
- R93 [execute] Stage the world for T27 and run the full routine (M5 implementation — P3 (town layer + waypoint))
- R94 [inform] Announce test conclusions in-game (M5 implementation — P3 (town layer + waypoint))
- R104 [inform] NPC dialogs are keyboard-navigable (M5 implementation — P3 (town layer + waypoint))
- R105 [inform] Read Kashya's dead-merc menu aloud (M5 implementation — P3 (town layer + waypoint))
- R106 [inform] T35 run 2: dialog opened en route killed the stash step (M5 implementation — P3 (town layer + waypoint))
- R107 [inform] T35: the belt did not fill before drinking (M5 implementation — P3 (town layer + waypoint))
- R108 [inform] T35 run 3: 'cannot identify the stash tab' with 29 items in it (M5 implementation — P3 (town layer + waypoint))
- R109 [decision] Detect the stash tab directly rather than by toggling? (M5 implementation — P3 (town layer + waypoint))
- R110 [verify] Two stash reads, one per tab (M5 implementation — P3 (town layer + waypoint))
- R111 [inform] T27: bot stuck in a loop misclicking the waypoint (M5 implementation — P3 (town layer + waypoint))
- R112 [inform] What is the item stuck in the inventory (kind 534)? (M5 implementation — P3 (town layer + waypoint))
- R113 [inform] The shift race (M5 implementation — P3 (town layer + waypoint))
- R114 [decision] The P3 review gate (M5 implementation — P3 (town layer + waypoint))
- R115 [decision] IdleBail wiring at the frozen cycle boundary (M5 implementation — P4 (behavior engine, sim-only))
- R115 [decision] Should `IdleBail` share the cycle's chicken counter? (M5 implementation — P6 stage B review fixes)
- R116 [decision] **The P5 review gate — go/no-go for live** (M5 implementation — P5 (combat + pickit, sim-only))
- R117 [inform] The real pickup spec, the potion-cap town rule, and the inventory cleanse (M5 implementation — P5 (combat + pickit, sim-only))
- R118 [decision] Pickup-spec confirmation batch (Q1–Q5) (M5 implementation — P5 (combat + pickit, sim-only))
- R119 [execute] Run the T38 + T39 discovery drills (bridge) (M5 implementation — P5 (combat + pickit, sim-only))
- R120 [execute] Run T40: two marker rounds in the chat line (M5 implementation — P5 (combat + pickit, sim-only))
- R121 [execute] Run T41: chat call-and-response (3 rounds) (M5 implementation — P5 (combat + pickit, sim-only))
- R122 [execute] Run S1: simulate a Claude coding-session exchange in-game (M5 implementation — P5 (combat + pickit, sim-only))
- R123 [execute] Run S2: the same exchange, solo-project framing, gated on a real submission (M5 implementation — P5 (combat + pickit, sim-only))
- R124 [verify] T38: confirm the socket read, by dropping the item (M5 implementation — P5 (combat + pickit, sim-only))
- R125 [inform] The loot filter is a naming source — mine it (M5 implementation — P5 (combat + pickit, sim-only))
- R126 [verify] T39 run 1 — ABORTED by the user, and worth more than a pass (M5 implementation — P5 (combat + pickit, sim-only))
- R127 [decision] How to resolve the last ~45 names (M5 implementation — P5 (combat + pickit, sim-only))
- R128 [decision] The R127 option-A review table (M5 implementation — P5 (combat + pickit, sim-only))
- R129 [decision] P6 stage A — go (M5 implementation — P5 (combat + pickit, sim-only))
- R130 [decision] GitHub rejected the push: email privacy (M5 implementation — P5 (combat + pickit, sim-only))
- R131 [inform] "We can try again — just make sure to ctrl+right click" (M5 implementation — P5 (combat + pickit, sim-only))
- R132 [decision] Cleanse strictness + fullness handling (M5 implementation — P5 (combat + pickit, sim-only))
- R133 [verify] **P6 stage B — the first supervised fight** (M5 implementation — P5 (combat + pickit, sim-only))
- R134 [decision] The stash tab is unreadable on this character (M5 implementation — P5 (combat + pickit, sim-only))
- R135 [execute] Set up and run T45 (materials auto-route) (M5 implementation — P5 (combat + pickit, sim-only))
- R137 [execute] Enter a game so the waypoint state can be read (M5 implementation — P5 (combat + pickit, sim-only))
- R143 [execute] Enter a game to read the inventory (M5 implementation — P5 (combat + pickit, sim-only))
- R146 [execute] Run T47, the hotkey audit (M5 implementation — P5 (combat + pickit, sim-only))
- R147 [inform] "2 screens in each direction around the waypoint" (M5 implementation — P5 (combat + pickit, sim-only))
- R148 [verify] Stage B runs 6-9, and four behavioural notes (M5 implementation — P5 (combat + pickit, sim-only))
- R149 [execute] Reboot to reshuffle ASLR, and close the stuck `Game.exe` (Out-of-band — the game stopped launching (host environment, not the bot))
- R150 [execute] Start the elevated bridge for this session (M5 implementation — P6 stage B review fixes)
- R151 [verify] Watch T48 — cast animation length, and when input is accepted again (M5 implementation — P6 stage B review fixes)
- R152 [execute] Run T47, the hotkey audit (the offer R146 declined) (M5 implementation — P6 stage B review fixes)
- R153 [verify] Supervised stage-B run, with the three review fixes in it (M5 implementation — P6 stage B review fixes)
- R154 [inform] "We got waypoint locked again" — and the recovery to build in (M5 implementation — P6 stage B review fixes)
- R155 [verify] Re-run stage B with the waypoint fixes (M5 implementation — P6 stage B review fixes)
- R156 [decision] Patrol plan: six confirmation questions (Q1-Q6) (M5 implementation — P6 stage B review fixes)
- R157 [decision] Is the patrol a new step, or does `clear_radius` grow it? (M5 implementation — P6 stage B review fixes)
- R158 [verify] Supervised live run of the patrol clearance (M5 implementation — P6 stage B review fixes)
- R159 [verify] Re-run the patrol after the `_walk_near` fix (M5 implementation — P6 stage B review fixes)
- R160 [verify] Run T49, the waypoint click probe (M5 implementation — P6 stage B review fixes)
- R161 [verify] Re-run the patrol, instrumented (M5 implementation — P6 stage B review fixes)
- R162 [verify] Re-run the patrol with misclick recovery (M5 implementation — P6 stage B review fixes)
- R163 [decision] Combat aggression numbers, after watching the patrol run (M5 implementation — P6 stage B review fixes)
- R164 [execute] Get the character into Cold Plains for T50's field half (M5 implementation — P6 stage B review fixes)
- R165 [execute] Run T51 — the walk-away visibility test (the user's own idea) (M5 implementation — P6 stage B review fixes)
- R166 [decision] Re-run T51 for a clean artifact, or move on? (M5 implementation — P6 stage B review fixes)
- R167 [verify] Supervised live run of the instrumented patrol + sweep (M5 implementation — P6 stage B review fixes)
- R168 [decision] Three follow-ups from the first instrumented patrol run (M5 implementation — P6 stage B review fixes)
- M5 P6 R169 [decision] Workflow overhaul: four confirmation questions Â· 2026-08-01 19:39
- M5 P6 R170 [decision] Q3 clarified: does the done-alert fire on every terminal turn end? Â· 2026-08-01 19:39
- M5 P6 R172 [decision] The two baseline-protected inventory items: hand-clear or policy change? Â· 2026-08-01 20:17
- M5 P6 R173 [decision] Say go for the GOAL_EXEMPT_RADIUS confirmation run Â· 2026-08-01 20:17
- M5 P6 R174 [decision] Eastern dead zone: sanction cluster-level write-off inference? Â· 2026-08-01 20:17
- M5 P6 R175 [decision] Post-confirmation-run fixes and the survey question (Q1-Q3) Â· 2026-08-02 00:43
- M5 P6 R176 [decision] Survey + fixes plan: phase table and Q1-Q4 confirmations Â· 2026-08-02 00:52

- M5 P6 R177 [decision] Say go for the live acceptance runs (survey-town, survey-cold-plains, patrol re-run) · 2026-08-02 01:37
- M5 P6 R178 [execute] Restock healing potions (belt refill 2 short), then say go to relaunch · 2026-08-02 02:01

- M5 P6 R179 [decision] Three pre-run-3 proposals: ALT policy, the potion overhaul, the narrative bot log · 2026-08-02 03:29

- M5 P6 R180 [execute] Restock healing potions again (Tower walk drank them), then go for T53 run 2 · 2026-08-02 03:41

- M5 P6 R181 [decision] Add route-aware legs to the approved plan? · 2026-08-02 03:55

- M5 P6 R182 [decision] Potions + narrative-log cycle: approve commit and say go for live · 2026-08-02 05:13

- M5 P6 R183 [verify] Which chord actually feeds the merc? Test by hand · 2026-08-02 16:37

- M5 P6 R184 [execute] T54 run 4: OK the gates in-game after the run-3 fixes · 2026-08-02 17:00

- M5 P6 R185 [decision] The 854 s clearance: approve the upkeep-churn fixes · 2026-08-02 17:25

- M5 P6 R186 [decision] Dilly-dally review: which of T1-T4 to implement? · 2026-08-02 17:52

- M5 P6 R187 [execute] T55 run 1: OK the gate — the timed patrol · 2026-08-02 18:42

- M5 P6 R188 [execute] T55 run 2: OK the gate — more data after the armor/no-route fixes · 2026-08-02 19:06

- M5 P6 R189 [decision] The border livelock: approve the three fixes; Enter/ESC kill switch design · 2026-08-02 19:40

- M5 P6 R190 [execute] T55 run 3: OK the gate — livelock fixes and kill switch, live · 2026-08-02 20:07

- M5 P6 R191 [execute] T55 run 4: OK the gate — confirm the trend · 2026-08-02 20:29

- M5 P6 R192 [execute] T56 run 1: OK the gate — Stage C, the supervised full run · 2026-08-02 21:10

- M5 P6 R193 [execute] T57 run 1: stage 1 healing potion, OK the gate — the potion supply chain · 2026-08-02 23:19

- M5 P6 R194 [execute] T58: drop a potion, then hover on my marks — the hover-pointer hunt · 2026-08-03 00:09

- M5 P6 R195 [execute] T59: drop 2-3 potions at the character's feet, GO, hands off · 2026-08-03 00:26

- M5 P6 R196 [execute] T60: two rounds — drop one potion a few steps away, GO, hands off · 2026-08-03 00:44

- M5 P6 R197 [execute] T60 run 2: same two rounds, now with REAL mouse-move events · 2026-08-03 01:02

- M5 P6 R198 [execute] T60 run 3: three rounds, transition-click protocol · 2026-08-03 01:14

- M5 P6 R199 [execute] T61: drop TWO potions apart, GO — steering strategies + the far-click question · 2026-08-03 01:33

- M5 P6 R200 [execute] T62: drop ONE potion, GO, hand off — the glide lawnmower · 2026-08-03 01:52

- M5 P6 R201 [execute] T63: two rounds — labels ON then OFF, the click matrix · 2026-08-03 02:14

- M5 P6 R202 [execute] T59 run 2: drop 2-3 potions at the feet, GO — the sprite-aim rematch · 2026-08-03 02:33

- M5 P6 R203 [execute] T59 run 3: drops 3-5 steps out, DIFFERENT directions — the occlusion check · 2026-08-03 02:48

- M5 P6 R204 [execute] Restock healing potions before the Stage C rerun · 2026-08-03 02:58

- M5 P6 R205 [execute] T64 (after Stage C concludes): drop a junk/whitelist mix, GO — pickit accuracy · 2026-08-03 03:15

- M5 P6 R206 [decision] Stage D item 1: chicken back to 35% (user-decided) · 2026-08-03 03:40
- M5 P6 R207 [execute] Autonomous pickup-accuracy campaign (T65+) · 2026-08-03 03:40

- M5 P6 R208 [decision] Stage D threshold review closed — all items keep shipped behavior · 2026-08-03 05:20

- M5 P6 R209 [execute] T66 (autonomous): find the ALT label flag · 2026-08-03 05:40

- M5 P6 R210 [execute] STAGE E: 3 unattended games (user go) · 2026-08-03
- M6 R211 [decision] Approve the M5 closeout commit · 2026-08-03 06:31
- M6 R212 [decision] M6 plan: Q1-Q10 + phase table · 2026-08-03 06:31
- M6 P1 R213 [decision] Merge PR #1 into main? · 2026-08-03 17:12
- M6 P1 R214 [decision] Commit P1 and continue with P3? · 2026-08-03 20:00
- M6 P2 R215 [inform] Hold-left-click moves without interacting · 2026-08-04
- M6 P2 R216 [verify] Confirm the Countess candidate by eye · 2026-08-05 06:20
- M6 P2 R217 [decision] Standing mandate for the P2 live batch · 2026-08-05 06:20
- M6 P2 R218 [execute] Clear stash space (preamble halts) · 2026-08-05 18:40
- M6 P4 R219 [decision] Go/no-go: the countess run (sim + staging) · 2026-08-05 21:21
- M6 P4 R220 [decision] Run-log design confirmations Q1-Q11 · 2026-08-05 22:30
- M6 P4 R221 [execute] Stand in the Forgotten Tower for the hostile census (T73) · 2026-08-06 01:35
- M6 P4 R222 [execute] Second census with real monsters (T73 run 2) · 2026-08-06 01:52
- M6 P4 R223 [verify] Launch the first live Countess run (T71 run 3) + judge the staging approach · 2026-08-06 02:51
- M6 P4 R224 [decision] Approve the pickup-reliability plan: phase table + measure-first gate · 2026-08-06 05:21
- M6 P4 R225 [decision] Re-run T76 after the drill's own defects were fixed · 2026-08-06 19:16
- M6 P4 R226 [execute] Drop ten different PD2 maps for T77 to read · 2026-08-06 19:16
- M6 P4 R226 resolved (T77 PASS) · 2026-08-06 19:28
- M6 P4 R227 [decision] Approve item-acquisition plan + command-by-GID spike (branch) · 2026-08-06 20:36
- M6 P4 R228 [decision] Choose the chicken-starvation fix: interruptible walk_to, watchdog process, or both · 2026-08-07 04:02
- M6 P4 R228 resolved (option b: in-process fix now, watchdog before the battery) · 2026-08-07 04:05
- M6 P4 R229 [decision] Approve the safety-starvation phase table + five design questions · 2026-08-07 04:22
- M6 P4 R229 resolved (all yes; P1+P2 authorized) · 2026-08-07 04:25
- M6 P4 R230 [decision] P2 review gate: Track A done, may the acceptance battery resume? · 2026-08-07 05:04
- M6 P4 R230 resolved (option b: watchdog first, battery waits) · 2026-08-07 05:12
- M6 P4 R231 [verify] Run the two safety canaries: T80 (in-process interrupt) and T81 (watchdog) · 2026-08-07 21:27
- M6 P4 R231 resolved (T80 run 2 + T81 PASS, unattended) · 2026-08-07 22:50
- M6 P4 R232 [inform] What the unattended canary cost, and the production bug it found · 2026-08-07 22:52
- M6 P4 R233 [execute] Launch the P5 Stage A descent run (agent launch path permission-blocked) · 2026-08-08 01:45
- M6 P5 R234 [execute] Re-run the Akara probe to confirm the NPC classification fix · 2026-08-08 04:12
- M6 P5 R234 resolved (self-run via the bridge: classification fixed and proven, allies 1->11; clearance rule measured as the second cause)
- M6 P4 R235 [decision] Fix the cleanse gap before the Countess run, or run first? (numbered at closeout; R234 taken concurrently) · 2026-08-08 03:05
- M6 P4 R235 resolved (a then b: cleanse fixed, Countess attempted twice, not yet successful) · 2026-08-08 05:10
- R236 [decision] CI plan: confirmations Q1–Q5 · 2026-08-09 02:43
- R236 resolved (all yes; plan written, sm) · 2026-08-09 03:05
- R237 [decision] Approve the CI commit + push (the push IS the validation) · 2026-08-09 03:11
- R237 resolved (all yes; CI live, first run green 40s) · 2026-08-09 03:18
- R238 [decision] Dependency-pinning plan: confirmations Q1–Q5 · 2026-08-09 03:35
- R238 resolved (all yes; lockfile + canary live, CI green) · 2026-08-09 03:51
- R239 [decision] Package-restructure plan: timing + confirmations Q1–Q7 · 2026-08-09 04:01
- R239 resolved (now + all yes; 7-phase md plan, branch restructure) · 2026-08-09 05:06
- R240 [execute] Clear the client for the restructure smoke run · 2026-08-09 05:33
- R240 resolved (go; smoke PASSED, restructure merged 410b7b1) · 2026-08-09 06:35
