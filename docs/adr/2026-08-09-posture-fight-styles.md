# ADR: postures may select a fight style (a bounded enum)

Date: 2026-08-09
Status: accepted
Plan: docs/plans/2026-08-09-combat-logistics/ (R241 Q3)

## Context

Since M6 P3, a posture has been "a manner, not a build": an override
table over the combat NUMBERS, with skills excluded by the loader. The
user asked for **berserk** — always attack the nearest visible enemy,
no skirmish dash-out — which is a different *choreography*, not a
different number. Choreography lives in the class module (layer 2),
which postures could not previously reach.

## Decision

`CombatConfig` gains `style`, a **bounded enum** (`skirmish`,
`charge`) that the class module implements; posture tables may name a
style and may set the (posture-only) `armor_recast_below_pct` override
that the reflex ladder's armor rung consults through a callable. This
is a deliberate, licensed crossing of the manner/build line, bounded
three ways: the enum is closed (an unknown style is a load error), the
class module owns every implementation (a posture can only *select*),
and skills remain excluded entirely.

The reflex ladder's precedence over any style is the safety argument:
berserk keeps its potions, escapes, and armor upkeep not because the
style remembers to, but because the ladder outranks the style by
construction — the layering did not move.

## Alternatives rejected

- **Pluggable combat strategies** — a framework for a one-class bot.
- **More numeric knobs until charge emerges** — "no dash-out" and
  "nearest target" are structural, not tunable-to-zero.
- **A separate berserk module** — duplicates the necro's maintenance
  logic to vary one beat.

## Consequences

New styles must be implemented in the class module and added to the
enum; postures stay data. Berserk's live acceptance is supervised (Q6)
because charge concentrates the exact risk profile of the 2026-08-07
death — its safety case IS the unstarvable ladder, unchanged.
