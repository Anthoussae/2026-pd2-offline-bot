---
kind: plan
size: md
depth: implementation
status: active
repo: 2026-pd2-offline-bot
created: 2026-08-13
adr: possible
---

# clear_radius locomotion speed pass

Approved R257 (2026-08-13). Branch: `combat-logistics` (unmerged; this
detour rides it like the previous two).

## Goal

Remove the bot's long idle periods and time-consuming navigation
difficulties in Cold Plains clearance. The operator's from-the-chair
list, all undesirable: small movement bursts, walking back and forth,
retracing steps, dithering, wandering, backtracking, standing still.

**Acceptance (R256 QB, operator-set): Cold Plains segment < 180 s,
zero ticks over 4 s, idle < 45 s** — measured by
`python -m pd2bot.runlog.compare` and the new locomotion report,
against BOTH standing benchmarks:

- bot baseline `logs/runs/20260813-083614-cold-plains` (454 s CP,
  178 s idle, 6.0 st/s)
- human benchmark `logs/runs/20260813-192249-human-coldplains`
  (53 s CP, 16 s idle, 16.5 st/s — same character/build/gear)

## Why md

Three independent fix families (pathfinding bound, posture default,
leg pacing), each individually small, plus a live acceptance battery
that needs the operator present — natural phase boundaries, one review
gate (P4's numbers).

## Discovery summary (full record: notes.md)

- **The 47 s stall is `pathing.astar` unbounded**: reproduced offline —
  the baseline's failing 8-subtile query answers NO PATH in **20.15 s**
  on the atlas alone (healthy control: 3 ms). The cells are walkable
  but in different connected components of the atlas; unknown ground is
  blocked by design; the two-strike no-route rule doubles the cost.
- **Stop-start bursts**: one MoveTo per tick, legs capped at 8 st
  (combat dash) / 12 st (patrol), character stands during each tick's
  decision. Effective 6.0 st/s vs the character's real 16.5.
- **Back-and-forth**: the cautious skirmish beat retreats 12 subtiles
  after EVERY strike then dashes back in 8s — dominant cost (combat
  exposure 388 s of 454). Operator RULED (R256 QA): **berserk becomes
  the default posture henceforth**; skirmish stays defined, unused.
- The repo's standing warning applies to every change here: the last
  four confident navigation fixes were wrong — measure before AND
  after, no exceptions.

## Phases

| Phase | File | Summary | Gate |
|---|---|---|---|
| P1 | 01-telemetry-and-report.md | `nav.plan` events + offline locomotion report; re-price the existing logs | none |
| P2 | 02-bounded-astar.md | Distance-scaled node budget in A*; regression test; live replay probe | none |
| P3 | 03-berserk-default-and-legs.md | `default_posture` knob (= berserk) + `patrol_step` 12→20 | none |
| P4 | 04-live-acceptance-battery.md | 3 live Cold Plains runs vs both benchmarks; QB targets | **operator verifies numbers + impression** |
| P5 | 05-closeout.md | Docs, performance-notes re-price, ADR decision, cleanup | none |

P1–P3 are offline and may be implemented back-to-back in one session;
P4 needs the operator at the machine (standing mandate: confirm
presence before any launch; bridge + guarded-run as always).

## Files/modules expected to change

`pd2bot/nav/pathing.py`, `pd2bot/nav/navigate.py`, `pd2bot/wiring.py`,
`pd2bot/runlog/` (new `locomotion.py`), `pd2bot/behavior/combat.py`,
`pd2bot/behavior/necro.py`, `pd2bot/behavior/steps/services.py`,
`config/necro.toml`, tests throughout.

## Documentation expected to change

`docs/architecture/navigation.md` (the search budget),
`docs/architecture/behavior.md` (default posture),
`docs/plans/2026-08-03-m6-countess/performance-notes.md` (re-priced),
`docs/architecture/run-log.md` (the `nav.plan` event kind).

## Decisions already made (do not relitigate)

- Budget-exhausted A* answers None = the EXISTING no-route semantics;
  write-off expiry-on-movement is the honesty mechanism (R256 Q1).
- Berserk is the default posture by operator ruling, applied at module
  construction so every run inherits it without run-file edits; run
  steps that name a posture still override per step (R256 QA).
- Safety invariants are untouched: the reflex ladder owns berserk's
  survival (R241); `GatedInput`'s guard, the death latch, the
  unstarvable-monitor rule, and the 2 s walk budget all stay.

## ADR

`possible` — one candidate: bounded pathfinding ("no path found within
budget" as an honest fast answer). Decide in P5 by the CLAUDE.md ADR
bar; the posture default is config, not architecture.

## Validation strategy

Full suite + ruff after every phase (1315 green at plan time). P1's
report re-prices the two existing logs (no live run). P2 has a hard
regression bound (<100 ms on the replayed no-path case). P4 is the
live gate with the QB numbers. Every live run: operator present,
watchdog, abort channel.
