# 003 — the consumed-item announcement is sent with the inventory open

**Severity:** P3

**Where:** `pd2bot/behavior/steps/tagmode.py::_tick_drop` (the
floor-confirm consumed branch).

## What is wrong

The "never hit the floor — consumed by a slipped click" announcement
fires mid-drop-phase, while the inventory panel is open. `Chat`'s
blocking-panel guard (R243) refuses to type with a panel up, so
`_say`'s chat attempt fails and the message lands only on the console
fallback (`alert`). The operator watching the GAME does not see it
until the round's other announcements.

## Why it matters

Cosmetic-plus: the event (`battery.consumed`) is logged either way and
the census self-adjusts, but the operator asked for a chatty battery,
and a silently-eaten potion is exactly the kind of thing they would
want to see in the moment (they diagnosed the first one themselves).

## Suggested fix

Queue the consumed announcement and speak it at the next panels-closed
moment (test_start's round announcement already fires then — prepend
it), or pass `Chat(allow_panels={UI_INVENTORY})` for the battery's
channel the way T85 did for the shop (R243's opt-in exists for this
shape; the inventory panel has no Enter-activated default).

## Validation

A unit test asserting the consumed message reaches `say` (not just
`alert`) when the slip happens with the inventory open.

## Resolution

RESOLVED 2026-08-14 (P6 closeout): the battery chat is `Chat(allow_panels={UI_INVENTORY})` - the R243 opt-in, T85 shape; the inventory grid has no Enter-activated default. The consumed announcement now reaches game chat mid-drop.
