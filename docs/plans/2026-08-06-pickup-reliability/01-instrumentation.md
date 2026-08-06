# P1 — Instrumentation: make pickup failure answerable

Part of [plan.md](plan.md). Size: `sm`. **Needs no game.** No
dependencies. Review gate: none.

## Why this is first

Answering "were any whitelisted items not picked up" on 2026-08-06
required hand-correlating `action.pickup_attempt` against
`item.collected` by unit id in a throwaway script, because **11 of the
13 misses emitted no event at all**. The project's own method note says
to add the instrument rather than reason around it. This phase makes
the baseline a query, so P5 can prove the fix worked.

## Scope

Three instruments and one report.

### 1. A click-budget write-off must emit `item.abandoned`

`_PickupMixin.collect` in `pd2bot/behavior/steps.py`: the walk-budget
path already emits `item.abandoned` ("walks kept arriving short"). The
**click**-budget path (`attempts >= pickup_click_attempts`) adds the
item to `services.stuck` and returns without an event, in all three of
its branches (potion-with-belt-room, belt-full, non-potion).

Emit one event in every branch, carrying what a diagnosis needs:

| field | value |
|---|---|
| `unit_id`, `item`, `item_kind` | as elsewhere |
| `reason` | `"clicks did not land"` / `"belt full for <type>"` / `"inventory full"` |
| `clicks` | attempts spent |
| `aim_points` | the offsets actually tried, in order |
| `position` | three-frame, via `mapframe.describe` |
| `neighbours` | count of other ground items within 2 subtiles |

`neighbours` is deliberate: the density correlation is the leading
hypothesis, so the log should carry the number rather than force
another correlation script.

The **belt-full vs click-missed reasoning must not change** — only its
reporting. That logic is load-bearing (T56's starvation loop) and its
comments record why.

### 2. A swallowed `NavigationError` must emit an event

`_PickupMixin.send` catches `NavigationError`, logs to
`services.log`, and returns False. In T71 run 4 that hid four ticks of
25–35 s each. Emit `nav.failed` with `where` (the step name), `target`
(three-frame), `detail` (the exception text) — the error carries the
navigator's own trail — and the elapsed time of the attempt if
available.

Keep the absorb behaviour exactly as it is; this is reporting only.

### 3. `runlog --pickup`: the report

Add a mode to `pd2bot/runlog.py` (which already has `--kind`,
`--since`, `--raw`, `--no-collapse`) that prints the pickup census:

```
PICKUP  18/31 collected (58%)
  by floor
    Tower Cellar Level 1   6/10
    ...
  MISSED
    nef_rune       (12544, 11084)  Cellar 5  3 clicks  1 neighbour  -> clicks did not land
    flawless_emerald (12644, 5146) Cellar 1  8 clicks  0 neighbours -> clicks did not land
  attempts histogram: 1:4 2:9 3:2 6:2 8:11 16:1
```

It must work on **existing logs** — `logs/runs/20260806-025952-countess`
is the baseline and predates the new events, so the report derives what
it can from `action.pickup_attempt` + `item.collected` and degrades
honestly where the newer fields are absent (`honest absence`, the
log's own rule).

## Files

- `pd2bot/behavior/steps.py` — `collect` write-off branches, `send`.
- `pd2bot/runlog.py` — the `--pickup` report.
- `docs/architecture/run-log.md` — document `nav.failed` and the new
  `item.abandoned` fields in the event table.
- `tests/test_behavior_steps.py`, `tests/test_runlog*.py`.

## Implementation notes

- Events never raise and never block (the log's rules). The write-off
  path is already inside a step tick; keep the gathering behind the
  `runlog.enabled` guard where it costs anything.
- `aim_points` needs the schedule the executor used. The executor owns
  `_PICKUP_OFFSETS`; the step knows only the attempt count. Simplest
  honest option: record the count and let the report map it to the
  schedule, OR expose the schedule as a module constant the step can
  read. Prefer the latter only if it does not couple step to executor
  internals — a small accessor is fine, reaching into a private tuple
  is not.
- The baseline number must be reproducible: capture the P1 report's
  output for the T71 run 4 log into this directory as
  `baseline-t71-run4.txt`.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pd2bot.runlog --pickup logs/runs/20260806-025952-countess
```

## Agent reminders

Do not commit unless asked. Do not change the belt-full/inventory-full
decision logic — only what it reports. Do not expand into the aim
schedule; that is P3 and it is gated on a measurement. Stop and report
if the write-off branches turn out to have behaviour the plan missed.

## Definition of done

All three instruments in, tests and ruff green, the report runs against
the pre-existing baseline log and reproduces 18/31, and
`baseline-t71-run4.txt` is captured in this directory.
