---
kind: plan
size: md
depth: implementation
status: active
repo: 2026-pd2-offline-bot
created: 2026-08-09
adr: expected
---

# Plan — combat & logistics: route leash, fight styles, restock, mandatory pickup

## Size and why

`md`, six phases. Each phase is independently testable offline and
carries at most one live acceptance; P5 is the largest but its phase
file is detailed enough to execute without a separate planning pass.

## Goal

Four capabilities and three config corrections from the user's R241
bundle: (a) runs follow a recorded core line and know when/how far they
have strayed; (b) postures can select fight styles, adding "berserk";
(c) potions come from Akara instead of the ground; (d) whitelisted
drops are pursued to collection by a persistent, safe, instrumented
order. Item 4 (watchdog potions) is explicitly rejected and stays so.

## Acceptance criteria

1. P1 config diffs live in the same session (heal 75; El–Sol runes
   skipped including PD2 `s`-variants; socket rules gone).
2. A line recorded by the operator's walk in ANY area replays as a
   leash: the run reports stray distance/direction per tick and returns
   per posture policy. Cold Plains line recorded and used live.
3. A `berserk` run clears Cold Plains supervised, with reflex rungs
   (armor-below-60 override, potions) firing normally.
4. The restock chore fills the belt at Akara from a cold start, reading
   stock cells fresh per visit; potion pickit rules removed in the same
   commit; a full run sustains itself on bought potions.
5. The mandatory-pickup pilot (flagged, Cold Plains) shows in its run
   census: zero wanted-and-lost items whose unit remained on the floor,
   no livelock (watchdog silent, never-idle silent), budget respected.
6. Suite + ruff green per phase; CI green; ADRs and teach step done.

## Constraints and conventions

- Branch `combat-logistics` off `m6-countess`; commit per phase; the
  live batch runs under the R241 Q8 standing mandate (berserk's
  acceptance stays supervised, Q6).
- Safety stack untouched: no changes to `safety/`, the death latch,
  guard conditions, or the never-idle watchdog. New loops must poll
  safety and stay bounded (the unstarvable rule binds all new code).
- All numbers land in `config/necro.toml` / run TOMLs / `maps/` data —
  never hardcoded. Loaders reject unknown keys loudly.
- Run-event-log instrumentation is part of each feature's definition,
  not an afterthought (R220 Q11 precedent). New event kinds documented
  in docs/architecture/run-log.md.
- Live work goes through the bridge; drills follow the T-numbered
  protocol and log to docs/drill-log.md.

## Phases

| Phase | File | Summary |
|---|---|---|
| P1 | 01-config-trio.md | heal 75; skip runes r01–r12 + r01s–r12s; delete socket rules |
| P2 | 02-route-line-leash.md | recorder drill, per-seed line store in maps/, stray signal, posture-conditioned return |
| P3 | 03-posture-styles-berserk.md | style enum (skirmish/charge), necro charge implementation, berserk posture |
| P4 | 04-akara-restock.md | stock reads from her unit, grid calibration drill, buy chore, pickit potion removal (same commit) |
| P5 | 05-mandatory-pickup.md | persistent orders, thread-back, unstack loop, walk-away cleanse, expiry detection, budget, pilot flag |
| P6 | 06-adr-docs-closeout.md | ADRs (posture-style boundary; R48 buy-half superseded), docs, teach, cleanup grep |

Order: P1 → P2 → (P3 | P4 in either order) → P5 → P6. P5 depends on P2.

## ADR expectations

Two expected, written in P6: `2026-08-09-posture-fight-styles.md`
(crossing "a posture is a manner, not a build" with a bounded enum) and
`2026-08-09-vendor-buying.md` (superseding R48's buy half; selling
stays out). The mandatory-pickup design is recorded in behavior.md, not
an ADR (feature, not boundary).

## Validation strategy

Offline: unit tests per phase against the sim/fakes (1169-test suite
grows; exact counts recorded per phase), ruff, CI per push. Live, under
the standing mandate: the P2 recorded walk + leash run, P3 supervised
berserk run, P4 calibration + restock drill + one self-sustaining run,
P5 pilot run with census review. Read the event log before judging any
live result.

## Discovery summary

See [notes.md](notes.md) — vendor UI already half-exists (Charsi
repair), lines are seed-bound save-data, posture-style is a deliberate
recorded line-crossing, reflex layering gives berserk its survival for
free, T51 expiry shapes the mandatory order's close condition, and the
user's Q4 refinement (read stock cells per visit) is honored in P4's
design.
