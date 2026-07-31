# 005 — Minor cleanups

Severity: **P3**

Small things worth a sweep, none urgent.

**Dead parameter.** `pickit.Rule._kinds_match(self, kind, permissive)`
accepts `permissive` and never reads it; the caller applies the
permissive rule itself afterwards. Either use it or drop it — a
parameter that does nothing invites a future reader to believe it does.

**Unbounded per-session state.** Three collections grow for as long as
the bot runs and are never trimmed:

- `NecroCombat._last_strike` — one entry per monster ever struck
- `GameActionExecutor.trace` / `RecordingExecutor.trace` — every action
- `RunServices.attempts` / `last_try` / `stuck` — per game, so bounded,
  but only if a fresh `RunServices` is built per game (P6 must)

An overnight session is hours of monsters. Cap the trace (a deque) and
drop strike records older than `restrike_s`.

**The cleanse forgets too much.** `steps.maybe_cleanse` clears the whole
`services.stuck` set after any successful cleanse, including items stuck
for reasons that have nothing to do with inventory space. Re-trying them
is cheap and bounded, so this is defensible — but it is worth saying so
in the comment, since today it reads as if space were the only reason an
item can be stuck.

**P6 wiring checklist** (not defects, but easy to forget):
`cleanse_keep(pickit)` → `TownLayer.keep_item`; the startup baseline →
`protected_ids` (see issue 001); `RunServices.cleanse`; the class
config's belt capacity → `Pickit.belt_capacity`; `chicken_life_pct` →
`SafetyConfig`.

## Resolution — the P6 wiring checklist (2026-07-31)

Every checklist item is wired, in a new module that exists precisely
because nothing owned this before: `pd2bot/wiring.py`. The review's own
diagnosis was that "the code is correct when assembled correctly; what is
missing is the refusal to be assembled incorrectly", and the assembling
had no home.

| Checklist item | Where |
|---|---|
| `cleanse_keep(pickit)` -> `TownLayer.keep_item` | `build_bot` |
| session baseline -> `protected_ids` | `SessionBaseline` |
| `RunServices.cleanse` | `LiveBot.engine_factory` |
| belt capacity -> `Pickit.belt_capacity` | `belt_capacity()`, derived from `[belt] columns` |
| `chicken_life_pct` -> `SafetyConfig` | `build_bot`, with a stage override |
| (R132) ladder's `carried` -> `with_sockets=False` | `LiveBot.engine_factory` |

Three things the wiring decided that the checklist did not name:

- **The `SafetyMonitor` is session-scoped**, because the death latch is
  instance state. Building it per game would clear it, and its own comment
  forbids exactly that ("a re-created game must not resurrect the bot's
  confidence"). The `TownLayer` is session-scoped too, so the cleanse
  baseline is genuinely session-wide.
- **Everything with per-run bookkeeping is per-game**: the combat module,
  the ladder, the executor trace and `RunServices`. That is what bounds
  the three unbounded collections this issue lists — a session lifetime
  was the problem, so a game lifetime is the fix.
- **`SessionBaseline` refuses to capture outside a game.** The inventory
  reads empty there, and an empty baseline protects nothing rather than
  everything — issue 001's silent worst case, reachable through the very
  parameter 001 added.

Also here: `walkability(navigator)`, the `is_walkable` predicate the ladder
and combat module take. It re-fetches the grid per call (the atlas grows as
rooms load) and checks `is_known` before `is_walkable`, so a blood warp is
never aimed into ground nobody has read.

Verified live through the bridge — `python -m pd2bot.wiring --dry-run`
assembles against the running client and prints what resolved:

```
class      necromancer (necro.toml)
run        cold-plains.toml: town_preamble, waypoint, clear_radius, pickup, done
pickit     16 rules, 0 pending name(s)
cleanse    ENABLED
belt       ('mana', 'rejuv', 'healing', 'healing') -> capacity {'healing': 8, 'mana': 4, 'rejuv': 4}
minimums   healing 4, mana 2, rejuv 0
chicken    35% life
idle bail  10s, refusal limit 50
```

The dry-run builds a throwaway engine on purpose: constructing it is what
proves the run file and step registry assemble, and without that the first
thing to discover a missing step factory would be a created Hell game with
the character standing in it. 14 tests in `tests/test_wiring.py` cover the
resolution logic — the review noted that no test constructed the production
wiring, which is why 001 and 004 were invisible to the suite.

Still open from this issue: the dead `permissive` parameter in
`Rule._kinds_match`, and the comment on `steps.maybe_cleanse` clearing the
whole `stuck` set.
