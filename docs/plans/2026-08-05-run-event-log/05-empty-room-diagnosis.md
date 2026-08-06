# P5 — The empty-room diagnosis

Part of [plan.md](plan.md). Size: `sm`. Dependencies: P1–P4.
**Review gate: YES** — a live run, and the findings, before any fix
lands.

## Scope

Use the new log to find out why the bot cannot cross an empty square
room, then fix that. This is the phase the whole plan exists to enable.

Out of scope: any fix that special-cases the Forgotten Tower.

## The standing constraint (user, 2026-08-05)

> *"We need to make sure that our pathfinder can always swiftly and
> reliably navigate it, not by hard-coding, but by debugging, as it is
> in a sense a template of all spaces. If we can't navigate a square
> box, then our navigation and/or mapping tools are wrong."*

Any fix must be expressed as a general rule about spaces, exits or
clicks. A coordinate special-case, a per-area constant, or a retry
tuned until this one room passes is a **failed** phase.

## What is already known

Proven (do not re-derive — `navigation-diagnosis.md` T71 addendum):

- The atlas holds the Tower as a 19×19-subtile walkable box; arrival
  (10006, 8002) and staircase (10002, 8013) are both known and walkable,
  11 apart; `astar` returns 12 steps simplified to **one leg**; the seed
  matches.
- Routing was never invoked: 11 ≤ `click_range` 18, so `TraverseStep`
  goes straight to clicking.
- The room contains no monsters, ever (user).
- 144 s, ~150 ticks, 5 clicks, 5 log lines.

Dead hypotheses (do not revive without new evidence): "the fight owned
the ticks" and "monsters contested the staircase" — the room is empty.

Live hypotheses, in the order the log will discriminate them:

1. **The click is executing as a walk order.** `InteractObject` clicks
   the raw tile projection with no offset; T63 measured tile clicks
   missing item sprites ~29/30, which is why pickup carries an 8-point
   aim schedule and object clicks do not. A click landing short is a
   walk order to the client. *Log signature:* `action.interact` events
   whose `click_screen` is where the tile projects, followed by `tick`
   events showing the player creeping toward the stairs.
2. **The progress-aware pacing suppresses re-clicks.** `_clicked_at`
   resets on every subtile of progress, so a creeping character starves
   its own retry. *Log signature:* long runs of
   `waiting out the last click` with a slowly falling distance.
3. **The tick is simply slow.** ~0.85 s of work per tick, with
   `read_carried_items` over a large inventory called every tick by the
   M6 P4 traverse-collect as a prime suspect. *Log signature:* the
   `tick.timing` split.
4. Something the log names that nobody listed. Most likely of all —
   that is why the instrument comes first.

These are not mutually exclusive, and (3) plausibly compounds (1) and
(2).

## Procedure

1. **Re-run the Tower live.** Prefer a *short* drill over the full
   flagship: town → Black Marsh → Forgotten Tower → Cellar 1 and stop.
   `runs/m6-traverse-one.toml` already covers the first hop; add the
   second. Cheap to repeat, and it isolates the failure.
2. **Read the log, do not theorize.** Answer, in order, from data:
   - How many ticks in the room, and what did each decide?
   - Where did the time go (`tick.timing`)?
   - Did the player position change after each `action.interact`?
   - Where did the click land on screen versus where the staircase is?
3. **Name the defect** in `notes.md` with the log lines that prove it.
4. **Fix it generally**, with a test that fails without the fix. If the
   fix is an aim schedule for objects, it is the T63 schedule
   generalized — not a Tower constant.
5. **Re-run** and confirm: the room is crossed swiftly (target: a few
   seconds) and repeatably (three consecutive clean crossings).

## Review gate

Stop after step 3 and present to the user:

- The rendered log of the room, with the decisive lines called out.
- The named defect and the evidence for it.
- The proposed general fix and what it changes elsewhere — an aim
  schedule for object clicks touches **every** staircase, door and
  waypoint the bot ever clicks, which is exactly why it needs a human
  look before it lands.

Do not implement the fix before this gate.

## Style and conventions

- The user's protocol for anything they must do: numbered request,
  logged in `docs/instruction-log.md` + `docs/request-index.md`, each
  command in its own fenced block.
- Drill discipline: announce in game chat, launch only when the user is
  tabbed in, abort paths standing, chicken 50 for a cellar drill.

## Docs

`navigation-diagnosis.md` gains the resolution; `notes.md` gains the
evidence; the drill log gains its rows.

## ADR expectation

**Possible.** If the fix changes how the bot clicks world objects in
general (an aim schedule for interactables), that is a lasting
convention with consequences for every future object interaction, and it
earns an ADR of its own.

## Agent reminders

- Do not commit unless asked.
- **Do not guess.** If the log does not answer the question, say so and
  add the missing instrument — that is the whole discipline this plan
  exists to establish. Speculation presented as a finding is what cost
  the T71 investigation two wrong diagnoses.
- Do not special-case the room.
- Do not suppress warnings or disable tests.
- Stop at the review gate.
- Report what changed, what was validated, and any deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

Live: three consecutive clean Tower crossings after the fix.

## Definition of done

The defect is named with log evidence, fixed generally with a regression
test, and the Tower is crossed swiftly three times running. The user has
seen and approved the diagnosis and the proposed fix.
