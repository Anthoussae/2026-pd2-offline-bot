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
