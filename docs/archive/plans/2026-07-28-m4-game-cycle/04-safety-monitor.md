# P4 — Safety monitor: chicken and the death latch

Part of [M4 game cycle](plan.md). Size: `sm`. Depends on: P3 (the
cycle loop it plugs into and the leave sequence it triggers).

## Scope

`pd2bot/safety.py`: a per-tick monitor over `GameSnapshot`, wired into
the cycle's run path. Two behaviors, decided at R27:

1. **Chicken** (Q3): life/mana percentage thresholds → emergency exit
   from the game. Defaults: life 50% on, mana off (configurable
   dataclass; percentages, kolbot-style).
2. **Death latch** (Q6): player dead → **permanent full stop**. No
   input of any kind after detection — not leave-game, not ESC,
   nothing — plus a loud, unmissable alert. The human takes over a
   game left exactly as it was.

Out of scope (explicit user decisions, notes.md): potion drinking,
merc/golem chicken, corpse retrieval, any death *recovery*, the wider
survival toolkit (bone shield upkeep, revives, blood warp, walk-away)
— all M5, designed there as a reflex ladder; this phase is the ladder's
bottom rung and its dead-stop.

## Detection

- **Death**: `UNIT_MODE` in {0 (Death — dying animation), 17 (Dead)}
  (kolbot `sdk/types/sdk.d.ts:1550`; constants go in `offsets.py` with
  that citation), corroborated by hp == 0. Treat *either* signal as
  dead — false positives are acceptable, false negatives are not.
- **Chicken**: `hp/max_hp` (full stats — M2's stat-trap lesson, the
  `pSetStat` array) at or below threshold, while in a game. Kolbot
  skips chicken in town; implement `in_town` (area id ∈ act towns —
  Act 1 town is area 1; put the town-area set in `offsets.py` or a
  constants home with citation) with a config override
  `chicken_in_town` (default False) — the override exists specifically
  for the zero-risk live test below.

## Order of evaluation (per tick)

Death first, then chicken. A dead player must latch the halt even if
the same snapshot would also satisfy the chicken (it will — hp 0), and
the latch must win: once set, `SafetyMonitor` refuses to evaluate
further and the cycle refuses to send anything, permanently, until the
process is restarted by a human.

## Emergency exit (chicken fires)

Call P3's `leave_game()`. Key fact from notes.md: **ESC pauses the
offline game instantly**, so the exit is effectively safe the moment
the first keypress lands; the subsequent clicks happen in a paused
world. Log the trigger (hp/max, threshold, area, nearest-monster
summary from the snapshot) before acting — kolbot prints exactly this,
and it is the data the user needs to tune thresholds in M5. The cycle
counts a chickened game as a completed-with-chicken cycle and
continues with the next game (chicken is routine, not an error).

## The alert (death)

Loud and local: console output that cannot be missed + a Windows beep
(`winsound.Beep` pattern, stdlib, no new dependency) repeated a few
times. No network, no notifications infrastructure — the operator is
at this machine by definition (elevated live sessions require them).

## Tests (all simulation — per Q6/R28 no live death test)

Scripted snapshots against a fake cycle/input:

- hp below threshold → `leave_game` called exactly once, loop
  continues, report notes the chicken.
- Mana path same (thresholds independent).
- In town + default config → chicken suppressed; `chicken_in_town`
  True → fires.
- Dead snapshot (mode 17, and separately hp 0 with mode alive) →
  latch: no `leave_game`, alert fired, subsequent ticks refuse, cycle
  sends nothing further.
- Death + chicken both true → death wins.

## Live verification — the zero-risk chicken demo

🔶 requests (IDs continue from the instruction log). Dying or getting
hit in Hell is not required or wanted:

1. Set mana threshold to ~99% with `chicken_in_town=True`; in town,
   the user casts any spell (mana dips) → the monitor must trigger the
   emergency exit and land at char select. This exercises the entire
   chicken code path — detection, logging, leave sequence, cycle
   accounting — with zero risk; the life threshold is the same code
   with a different stat.
2. One full `cycle --games 2` with the monitor active and default
   thresholds, confirming the monitor is inert in normal dwelling.

## Conventions

Narrative docstring; config as a frozen dataclass; injected
clock/cycle for tests; `ruff` clean; stat reads via existing
`player.py`/snapshot fields — no new memory reads except the mode/town
constants, cited.

## Agent reminders

- Do not commit unless the user asked.
- Do not expand scope (no potions, no merc, no recovery).
- The death latch is absolute: if any code path could send input after
  death detection, that is a design bug — stop and report.
- Do not suppress warnings or disable tests.
- Report what changed, what was validated, and any deviations.

## Definition of done

Monitor wired into the cycle; mana-chicken live demo passed; inert-run
demo passed; death latch fully simulation-tested (including the
both-true precedence); tests + lint green; instruction log updated.

## Implementation Result

Status: done
Completed: 2026-07-29
Commit: e6dabec

- Changed: `pd2bot/safety.py` (new — SafetyConfig, SafetyMonitor,
  ChickenExit/DeathHalt, latched alert), `pd2bot/cycle.py` (chicken =
  routine cycle outcome; DeathHalt = loop halt with structurally no
  input after; CLI flags --life-chicken/--mana-chicken/
  --chicken-in-town; monitor ticked 2.5×/s during dwell),
  `pd2bot/player.py` (+`mode` field), `pd2bot/offsets.py` (player
  death modes, town areas — kolbot-cited), `tests/test_safety.py`
  (16 tests incl. latch permanence, death-beats-chicken, and the
  no-input-after-death cycle guarantee).
- Also (user-requested mid-phase addition, R41→R42): `pd2bot/chat.py`
  + `tests/test_chat.py` — in-game chat output for live-test
  instructions; typed only after the chat console is verified open
  (per-character re-check) since an unopened console turns text into
  hotkeys. `input.py` gained the `_send_char` unicode primitive
  (guards untouched).
- Validated: 193 tests pass; ruff clean. Live (bridge 026–029): chat
  probe PASS; chicken demo PASS (`mana 340/378 (90%) <= 99%`,
  announced in chat, autonomous exit); inert run 2/2 clean with the
  monitor silent. Death path simulation-only per R27/Q6.
- Deviations: chicken demo ran as a script driving GameCycle +
  SafetyMonitor directly (so instructions could be chatted) rather
  than through the CLI; the CLI's identical wiring was exercised by
  the inert run.
