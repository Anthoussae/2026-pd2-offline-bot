# 002 — The walk budget now pre-empts the "hazard beside the goal" verdict

**Severity: P2** — it converts a correct, honest outcome into a stall,
and it feeds the give-up ladder for targets whose only crime is standing
near an NPC. Plausibly a contributor to the two town failures on
2026-08-08.

**Where:** `pd2bot/navigate.py`, `_walk_to` — the `if result.capped or
self._out_of_budget():` block now sits **above** the
`if arrived and self._blocked_by_avoidance(position, goal):` block.

## What is wrong

Before this change the order was: arrived? → blocked by avoidance? →
count a no-progress cycle. The avoidance branch exists to say something
specific and true:

> stopping N short of the goal: a hazard sits beside it and the click
> cannot be aimed closer

and it returns a NON-capped result, because nothing failed — that is as
close as the bot is allowed to get, by design.

The new budget check is evaluated first. Any walk toward a
hazard-adjacent goal that takes longer than 2 s — which is most of them,
since approaching an NPC means crossing town — now returns as **capped**
instead, and:

- `_stall_count` increments, because the character is legitimately not
  getting closer (it is not allowed to);
- five such calls raise `NavigationError: gave up after 5 capped attempts
  without progress`;
- `town._walk_all_the_way` loops on capped returns, so it re-issues the
  walk over and over until either that give-up fires or its own 60 s
  timeout does.

The bot is behaving correctly and being told it failed.

## Why it matters

Every configured NPC approach is a hazard-adjacent goal — Akara, Kashya,
Charsi are avoided as allies in town, and `GOAL_EXEMPT_RADIUS` is 1, so
an NPC pacing three subtiles off her mark is a hazard beside the goal.
The heal step's failure signature on 2026-08-08 was exactly "walked, did
not arrive, no panel involved".

The click-clearance work (commit `75c03b9`) reduces how often clicks land
on sprites, but it does not change this ordering: a goal next to an ally
is still refused by `_safe_click_point`, so the walk still stops short,
and the stop is still reported as a stall.

## Suggested fix

Restore the semantic ordering: ask "is this as close as we are allowed to
get?" before "did we run out of clock?". Concretely, move the
`_blocked_by_avoidance` branch above the budget branch, and let it return
non-capped as it always did.

The budget's purpose — handing the tick loop back — is unaffected: that
branch is reached on the very next call, and the avoidance branch only
triggers when the walk has genuinely finished its waypoints.

If both are true (blocked by avoidance AND out of budget), avoidance is
the more informative answer and should win.

## Validation

- Unit, in `tests/test_navigate.py`: a goal with a hazard beside it and a
  slow world; assert the result is NOT capped, `arrived_at` is the honest
  short position, and `_stall_count` did not increment. Confirm it fails
  with the current ordering.
- Unit: the same scenario repeated six times must not raise
  `NavigationError` — the ladder must stay untouched by a walk that never
  claimed to be stalling.
- Live: the Akara approach in the town preamble, which is the case this
  was found in.
