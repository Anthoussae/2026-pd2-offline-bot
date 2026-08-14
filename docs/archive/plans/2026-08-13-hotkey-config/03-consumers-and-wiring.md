# P3 — consumers use the registry; wiring loads and verifies

Size sm. Depends on P2. ADR: none here.

## Scope

Every meaning-assumption site switches to `KeyBindings`; `build_bot`
discovers, loads, verifies, and re-reads per game.

## Work

1. **Path discovery** (`input/keys.py` or wiring): the client exe path
   from the pymem process (`GameSession` exposes the process; add a
   small accessor if needed) → `exe.parent.parent / 'Save' /
   'ProjectD2'`; pick `<char>.key` — exactly one `*.key` → use it,
   several → require a `BotPaths.keyfile` override with a loud error
   listing the candidates, none → `default_bindings()` + one printed
   notice. `BotPaths` gains the optional override field.
2. **build_bot**: load bindings once at build; hand them to the
   executor, town layer and skills path. The ENGINE FACTORY re-loads
   per game (cheap file read) so a mid-session rebind is honored —
   same pattern as the town layer's per-run runlog repointing.
3. **skills.py**: `ensure_right_skill(..., hotkeys=...)` keeps its
   signature (skill id → VK); the TABLE now comes from
   `ClassConfig.hotkeys` resolved AGAINST the keyfile: in
   `combat.py`'s loader keep `[hotkeys]` name→key parsing, and add a
   `verify_against(bindings)` step wired in build_bot — every
   configured VK must appear among the keyfile's skill-slot
   primaries/secondaries, else ConfigError naming the skill, the
   configured key, and what the file actually holds. DEFAULT_HOTKEYS
   stays only as the no-config fallback, marked as such.
4. **BELT_KEYS** → `bindings.belt` (executor drink + merc-feed chord +
   town belt code paths).
5. **VK_I** (town inventory toggle) → `bindings.inventory`.
6. **VK_MENU label toggle** (execute.py) → `bindings.show_items`.
   (window.py's focus-ALT stays `keys.VK_MENU` — that is an OS-level
   inert keystroke, not a game binding.)
7. Threading: prefer passing `KeyBindings` explicitly (constructor
   params, like runlog/narrate), not a global.

## Tests

- A fake keyfile with REBOUND keys (e.g. belt on 7/8/9/0, inventory on
  Y): executor presses the rebound keys; town opens inventory with Y.
- toml/keyfile drift → ConfigError with all three facts in the message.
- No keyfile → defaults, and existing behavior tests pass byte-for-byte
  (they already construct without bindings — default plumbing).

## Reminders

Session commit practice; no scope creep; the GatedInput guard contract
is untouchable (M1); stop if the perception accessor for the exe path
needs anything more than reading the process object. Validation: full
suite + ruff.

Done when: no meaning-assumption outside keys.py; suite green.
