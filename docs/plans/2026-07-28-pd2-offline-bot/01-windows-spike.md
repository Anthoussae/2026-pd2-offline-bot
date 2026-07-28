# M1 — Windows validation spike: kolbot ↔ PD2 offline

**Work item:** M1 · **Size:** sm · **Depends on:** nothing ·
**Runs on:** the user's Windows machine (the one with PD2 installed).

## Purpose

Answer the plan's existential question as cheaply as possible: **can
kolbot's injected core (D2BS.dll) run inside Project Diablo 2's modified
1.13c client in offline single-player?** Everything later (configuration,
manual, docs) is wasted if this fails, so it goes first. The deliverable is
*knowledge*, captured in a spike log — not polished code or config.

## Scope

- Get the stock kolbot toolchain attempting injection into the PD2 client.
- Determine the outcome tier reached (see Success tiers).
- Write `spike-log.md` in this planning directory: every step taken, every
  error hit, exact paths/settings that worked.

## Out of scope

- Any character/build/pickit configuration beyond the minimum to test.
- Editing kolbot core files (throwaway experiments allowed; revert after).
- Writing the manual (the spike log seeds it later — M3).
- Anything touching online play. **Offline single-player only.**

## Preconditions (verify before starting)

1. PD2 installed and working: user can launch via PD2Launcher and play a
   single-player character for a minute. Note the install path — you need
   the folder containing PD2's `Game.exe` (typically the `ProjectD2`
   subfolder of the Diablo II install).
2. This repo cloned; `kolbot/` present. If missing (it is gitignored):
   `git clone --depth 1 https://github.com/blizzhackers/kolbot kolbot`
3. Kolbot dependencies: Microsoft VC++ 2010 Redistributable **x86** and
   .NET Framework 4.0+ (check installed programs before installing).
4. Run `kolbot/setup.bat` (required; copies config templates, inits
   submodules).

## Steps

Work from kolbot's own docs rather than guessing UI details — the
authoritative guides are linked from `kolbot/README.md`:
manager setup and single-player/manual-play guides live in
https://github.com/blizzhackers/documentation. Adapt as the real UI
dictates; **record what you actually did in the spike log as you go, not
after.**

1. Baseline sanity (optional but cheap): if a vanilla D2 1.13c install
   exists, confirm kolbot works against it first, to separate
   "kolbot is misconfigured" from "PD2 is incompatible". If no vanilla
   install, skip — don't spend the spike on it.
2. Launch `D2Bot.exe`, create a profile pointed at the **PD2** `Game.exe`
   path; single-player mode (no realm); entry script: kolbot's default or
   manual-play to start.
3. Attempt launch/injection. Triage what happens against the tiers below.
4. Key question at every step: **is the PD2 mod actually loaded?** D2Bot#
   launches Game.exe its own way, bypassing PD2Launcher — PD2's dlls may or
   may not get loaded. Verify in-game (PD2 UI differences, e.g. loot filter
   settings, season/PD2 branding, changed skills on the character). A
   vanilla-looking game means the launch path needs fixing (e.g. loader
   arguments, launching via PD2Launcher then attaching, or command-line
   flags — investigate and document).
5. If injection crashes or D2BS stays silent: capture exact symptoms,
   `exceptions.log` / `kolbot/logs/` / `d2bs/kolbot/logs/` contents, and
   any version-check messages. Search blizzhackers forum/discord archives
   for the specific error before concluding.
6. Time-box: ~half a day of focused effort. If blocked past that, stop and
   write up the diagnosis — that is a *successful spike outcome*, not a
   failure to complete the task.

## Success tiers (record which was reached)

- **T0** — D2Bot# launches PD2's Game.exe at all.
- **T1** — game runs **with PD2 mod confirmed loaded** and D2BS injected
  (in-game D2BS console responds / script output appears).
- **T2** — a trivial script works: enter a single-player game, read + print
  character name/level, leave the game.
- **T3** — a stock run script (e.g. Countess) limps through a game
  end-to-end, however roughly configured.

T2 = spike passes; T3 = bonus. Below T2 = gather diagnosis, stop.

## Review gate: END OF M1 — mandatory stop

Do not proceed to M2. Report to the user: tier reached, spike log path,
recommendation (proceed to M2 planning / try fallback X / reassess). The
proceed-or-fallback decision is the user's, made with the main planning
discussion.

## Agent reminders

- Do not commit unless the user asks.
- Do not expand scope; resist configuring the "real" character now.
- Do not edit anything under `kolbot/` durably; revert experiments.
- Offline single-player only — never configure realm/battle.net anything.
- Stop and report if blocked by ambiguity or an unexpected design issue.
- Report what was done, what was validated, and any deviations — in
  `spike-log.md` plus a chat summary.

## Definition of done

`spike-log.md` exists in this planning directory with: steps taken, exact
working configuration (or exact failure + diagnosis), tier reached, and a
recommendation. Review gate conversation held with the user.
