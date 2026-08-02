# Notes — potion overhaul + narrative log (M5 P6, R179)

## Origin

R179 (2026-08-02): the user raised three areas before the R177 patrol
acceptance run; all recommendations approved as proposed.

1. **ALT item names** — 1a (ensure names visible) is a NON-ISSUE:
   perception is memory-read (`units.py` scans the unit table), ALT only
   affects rendering; the bot cannot be blinded by it. Documented, no
   work. 1b (toggle names OFF to shrink the accidental-click surface —
   labels are big click targets, sprites are small) is plausible but
   likely already mooted by the GOAL_EXEMPT_RADIUS fix and drop
   hygiene; DEFERRED pending the run-3 click audit. If misclicks
   persist: a T-drill to verify pickups land label-free + a toggle
   policy, in a later robustness phase.
2. **Potion logic** — this plan's P1/P2.
3. **Narrative bot log** — this plan's P3.

## User rules (verbatim intent, R179)

- The belt should always be full of potions if possible.
- At least one column each of healing / mana / rejuv IF POSSIBLE;
  emptiness is normal, never a crash. Fourth column: don't care.
- Column ORDER must not matter (the bot reads what each column holds).
- If the belt isn't full, pick up potions of the appropriate type;
  keep ~2 spares per type in the inventory (already the pickit's
  behavior — `potion_reserve = 2` per type, R118).
- Merc below 50% hp → give a healing potion (Alt+NUM of the column).
- Explicitly NO vendor purchasing (strikes the earlier future-work
  item; pickups suffice).
- The bot log: broad actions with timestamps; waits must explain
  themselves (the "dawdle at an NPC" is verification polling + settle
  timers, and should say so). A micro-log is not the ask.

## Discovery (verified tonight)

- Belt contents ARE read per column with types:
  `CarriedItem.belt_column`, `is_healing_potion` etc.;
  `ReflexLadder._column_potion` already verifies the actual occupant
  before drinking. Emptiness already falls through, no crash.
- The RIGIDITY is the bug: `ReflexConfig` hardcodes
  mana_column/rejuv_column/heal_columns; the town refill
  (`fill_belt`) routes by the configured layout and the preamble HALTS
  on "belt below minimum after refill" — which fired on a merely-MIXED
  belt (mana potion in a healing column, R178, user diagnosed at 2 AM).
- Merc: `snapshot.merc` property exists (allies with `merc_kind`,
  `hp`/`max_hp` on the Monster shape). Alive-check used by the
  preamble already.
- Alt+NUM: a chord (hold modifier, wait a frame, press, release) —
  the Shift+click race lesson (P3) applies; input.py has modifier
  machinery for shift-clicks to model on.
- Log channels today: `services.log` / `services.alert` (micro, to
  stdout), `PreambleReport.log` (town), engine trace. None is the
  narrative channel; none carries wall-clock timestamps.

## Design decisions

- **Type-based belt** (P1): drink the needed type from whichever
  column holds it (search all four, configured column preferred);
  refill fills gaps by TYPE MINIMUMS (>=1 column-equivalent each of
  healing/mana/rejuv where stock allows), not by layout; the
  halt-for-a-human fires only when a type minimum is unmet AND stock
  exists that could not be loaded (a real mechanical failure) — merely
  missing potions logs loudly and continues (user: emptiness is
  normal).
- **Merc first aid** (P2): an upkeep-tier rung (below the player's own
  survival rungs): merc alive, merc hp < 50%, healing available →
  Alt+<column key> chord; paced like other rungs (on_attempt).
- **Narrative log** (P3): `narrate(text)` on RunServices + TownLayer —
  one line per meaningful act, wall-clock stamped, written to
  `logs/run-<timestamp>.log` (gitignored) and stdout. Waits narrate on
  COMPLETION with duration and what was being verified ("heal:
  verified after 3.8s (vitals read full)"). Coarse by contract: if a
  line would fire more than ~once a second, it belongs in the
  micro-log instead.

## Questions

None open — R179 answered the scope; numbers (50% merc threshold) are
the user's own.

## Future work

- ALT-1b (label-off policy + verification drill) — deferred, evidence
  gate: the run-3 click audit.
