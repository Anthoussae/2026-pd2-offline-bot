# 002 — A dead critter routes to `corpses`, and so becomes revive fuel

**Severity: P3**

`pd2bot/units.py` — `scan_units`, the classification chain

## What is wrong

The branch order is `is_corpse` → `is_ally` → `not combat_rated` →
monster. Because the corpse test comes first, a dead non-combatant is
filed as a corpse:

```python
if monster.is_corpse:
    corpses.append(monster)      # <- a dead bat lands here
elif monster.is_ally:
    ...
elif not monster.combat_rated:
    critters.append(monster)
```

`corpses` is revive fuel (M5): the necro's upkeep desecrates and revives
from it. So the bot could in principle raise a decorative bat as a
tank — and a revived critter would presumably be as useless in combat
as the living one.

## Why it matters

Low likelihood, low blast radius, which is why this is P3 rather than
P2: critters may never enter a death mode at all (they are scenery, and
the bot cannot damage them). No live evidence of it happening exists —
T73 read `0 corpse` in both censuses.

But the cost of being wrong is a wasted revive slot in the wall the
whole combat design depends on, and the fix is one line. Worth closing
rather than reasoning about.

## Suggested fix

Test combat-ratedness before the corpse test, so a non-combatant is a
critter whether alive or dead:

```python
if not monster.combat_rated:
    critters.append(monster)
elif monster.is_corpse:
    corpses.append(monster)
elif monster.is_ally:
    ...
```

## Validation

A unit test: a `combat_rated=False` monster with
`mode=MONSTER_MODE_DEAD` lands in `critters` and NOT in `corpses`.
