# 004 — The potion reserve is configured twice, in two files

Severity: **P3**

`pd2bot/town.py` (`TownConfig.potion_reserve = 2`) and
`config/pickit.toml` (`potion_reserve = 2` on three rules).

## What is wrong

Two independent numbers express one policy. The town layer drinks down
to `TownConfig.potion_reserve`; the pickit stops collecting at each
rule's `potion_reserve`. Nothing ties them together and nothing notices
if they disagree.

Set the pickit to 4 and the town to 2 and the bot collects potions in
the field specifically so it can drink them in town, every run, forever.
The failure is quiet and looks like normal behaviour.

## Why it matters

Low blast radius — wasted pickups, not lost items — but it is exactly
the "one fact, two homes" shape that the belt layout was deliberately
saved from: the ladder's columns are DERIVED from `[belt] columns` for
this reason (`combat.py`), and the same discipline should apply here.

## Suggested fix

Derive one from the other at wiring time: read the reserve from the
pickit rules (or from the class config) and pass it into `TownConfig`,
so the file the user edits is the only place the number exists. Failing
that, validate they agree at startup and fail loudly.

## Validation

A test that constructs the production wiring and asserts the two
reserves are equal by construction rather than by coincidence.
