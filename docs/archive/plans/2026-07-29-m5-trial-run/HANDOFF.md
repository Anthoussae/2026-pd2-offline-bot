# Handoff — paste this into a fresh conversation

Everything below is self-contained. The repo is clean and pushed at
`f9d4881` on `m5-trial-run`. **731 tests, ruff clean.**

---

> Continuing the PD2 offline bot, milestone M5, phase P6 (staged live
> acceptance). Read `docs/plans/2026-07-29-m5-trial-run/RESUME.md` first,
> then `docs/plans/2026-08-01-patrol-clearance/_DONE.md`.
>
> Last session closed all three open review findings, added a patrol so
> the clearance walks its circle instead of standing in the middle of it,
> and got a clean `[CVRL]` run at radius 96 that actually fought. Six
> live runs, and the failures along the way were town-layer and
> navigation faults rather than combat ones.
>
> **Start with the unreachable-monster write-off.** It is a regression I
> introduced: `ClearRadiusStep` now absorbs `NavigationError` from combat
> sends so one unreachable target no longer ends the run — but nothing
> then writes that monster off, so the clearance retries it every tick
> forever. The user watched it "hesitate at great length when an enemy
> was behind a wall". It needs a `stuck`-style set like the one pickup
> already keeps for items, so the monster stops counting toward
> `in_radius` and the step can finish.
>
> Then the three open items from the same feedback, all diagnosed and
> none fixed:
>
> 1. **The `pickup` sweep does not patrol.** It stands where the
>    clearance left it and collects what perception can see (80 subtiles
>    from the player), so with a 96-radius circle the far side is
>    invisible and a whitelisted Tir rune was left behind. The pickit
>    rules are correct — `[[rule]] name = "all runes"` keeps them. The
>    sweep has exactly the flaw the clearance had before the patrol.
> 2. **Rubbish is accumulating in the inventory.** Two runs sent ZERO
>    deliberate `PickUpItem` actions for anything but potions, so it is
>    travel clicks landing on ground items, not pickit decisions. The
>    navigator already avoids `INTERACTIVE_OBJECT_KINDS` and ground items
>    for travel clicks (`clickable_hazards`, AVOID_RADIUS 4) — so either
>    that is not covering these clicks or the radius is too tight.
>    Measure before changing it.
> 3. **The inventory cleanse cannot be shown to be working.** It runs
>    before the stash deposit (`manage_inventory`), but it logs NOTHING
>    when it drops nothing, so a run where junk reached the stash cannot
>    be told apart from one where the cleanse found nothing to drop.
>    Make it report first, then judge it. The user's rule: only
>    whitelisted items and the Horadric Cube stay in the inventory.
>
> The user also asked whether perception can be raised. It is already 80
> subtiles — over three screens — so the premise was off, but raising it
> would help the sweep see the whole circle. The structural reason it is
> bounded: the client's unit hash table contains every unit it knows
> about, including the stash and other levels, and the radius is what
> makes "nearby" mean anything (R23). A read-only probe comparing 80 /
> 160 / 320 would settle the cost in a minute and sends no input.
>
> Live runs need the elevated bridge; I start it, you drive it. Ask
> before anything that sends input to the game — I need to be at the
> machine watching, hands near the controls.
>
> Instruction-log IDs continue from R164.

---

## Context a new session most needs

**How live work happens.** The user starts the bridge once per session:

```
powershell -ExecutionPolicy Bypass -File "C:\dev\2026-pd2-bot\2026-pd2-offline-bot\tools\elevated-bridge.ps1"
```

The agent then drives it — read-only probes freely, anything that sends
input only with the user watching:

```
powershell -File tools\bridge-run.ps1 -Id 214-something -Command '& "$HOME\.venvs\pd2bot\Scripts\python.exe" -m pd2bot.wiring --games 1 --chicken 50 --run runs/cold-plains-patrol.toml'
```

Long runs should go in the BACKGROUND (they outlast a foreground tool
call). Python is `~/.venvs/pd2bot/Scripts/python.exe` — bare `python` is
a broken 3.8. Validation: `python -m pytest -q` (731) and
`python -m ruff check .` (clean).

Run files: `cold-plains-patrol.toml` (radius 96, patrols — the current
one), `cold-plains.toml` (150, patrols), `cold-plains-stage-b.toml` (50,
no patrol — the fallback rung). `--radius N` overrides any of them
without editing a file, and refuses loudly if the run has no clearance.

## The one lesson worth carrying

Three separate failures last session turned out to be the same thing:

> **A retry that cannot differ from the attempt it retries is not a retry.**

An object click that re-approached the same side and clicked the same
pixel; a patrol budget that counted legs rather than progress; a
navigator that re-planned from the position that had just failed. Each
cost a supervised run. When something is retried, check that the retry
can actually differ.

Corollary from the same session: **measure, do not theorise.** Two of my
diagnoses were wrong and each cost a run. What broke both open was the
user watching the screen — "it hovered but never clicked", "that was
Warriv's dialog" — and instrumentation that recorded what actually
happened (`open_object_panel`'s per-attempt trail, the idle-bail context
block, `ensure_right_skill`'s failure state).

## What is proven live

- The full pipeline `[CVRL]` at radius 96: preamble, waypoint, patrol
  clearance, sweep, clean leave. 128 ticks, 73 walk legs, two kills, two
  potions drunk under pressure.
- **T47**: all six hotkeys select what `config/necro.toml` says. Do not
  edit those bindings.
- **T48**: a cast animation is 610-640 ms (player mode 10), and a hotkey
  press sent 110 ms INTO one still registers within 62 ms — so casts do
  not eat following input, only clicks are worth holding.
- **T49**: the waypoint click path is sound in isolation.
- The run now announces its result in chat before leaving the game —
  except after a death, where the latch means silence.

## Still unexplained

`SkillSwitchFailed` has not recurred in the last six runs, and every
theory for it is dead: bindings are right (T47), presses land (T47),
casts do not eat input (T48), and a blocking panel or lost foreground
would raise `InputRefused` instead. `ensure_right_skill` now attaches the
state at the moment of failure, so the next occurrence is evidence
rather than another supervised run.

## Deliberately not done

- **No PR.** The branch is the whole M5 milestone (40 commits, ~51k
  lines) and P6 is not finished; there is no CI to watch, and the repo
  uses GitHub for durable state rather than review. Open one when M5
  closes.
- The east side of the Cold Plains circle (x≈5313-5331) is unreachable —
  3 of 8 patrol points were skipped there, consistently. Geometry, not a
  bug, but worth a look.
- The `[CV--]` unclean exit on leaving a game. M4's cycle, not the run.
- Review findings 004/005 (both P3, both minor).
