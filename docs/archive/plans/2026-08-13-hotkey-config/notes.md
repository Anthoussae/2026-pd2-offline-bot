# Notes — read the real hotkey config (.key file) + keybinding consolidation

Created 2026-08-13, from the operator's fact-finding chain: "is there a
consolidated hotkey location?" (no) → "can we detect my PD2 hotkeys from
the client/config files?" (yes — per-character `.key` file, format
cracked live) → this plan. Implementation pre-authorized: *"unless there
are any questions for me, go ahead and /yona-implement it … I trust
you."* No pressing design decisions found; the calls made are recorded
below and any of them is cheap to reverse.

## Discovery: the .key file format (empirically pinned, 2026-08-13)

- Location: `<D2 root>\Save\ProjectD2\<CharName>.key` (per character;
  the running client's exe is `<D2 root>\ProjectD2\Game.exe`, so the
  save dir is `exe_dir.parent / 'Save' / 'ProjectD2'`). A legacy copy
  sits at `Save\<CharName>.key` and a template at `<root>\default.key`.
- Framing: a small header, then **108 records x 20 bytes**. The header
  differs between files seen live (`default.key` = 8 leading bytes
  `57 53 25 00 …`, the character file = 4 bytes `25 00 00 00`), so the
  parser must NOT hardcode the offset — records are **self-validating**
  (the function index appears twice per record), and the parser anchors
  by scanning for the first valid record and then striding.
- Record: `{u16 pad, u32 index, u16 primary_vk, u32 one, u32 index2,
  u16 secondary_vk, u16 pad}` — `index == index2` validates; `0xffff`
  means unbound; key codes are plain Win32 VKs.
- Function labels pinned from `default.key` (vanilla defaults) and
  cross-checked against the operator's live bindings:
  - entry 0: character screen (secondary C)
  - entry 1: inventory — default I/B, **matches VK_I the bot assumes**
  - entry 7: automap (TAB)
  - entries 14..21: **skill hotkeys 1..8** — defaults F1..F8 with PD2
    QWER-row secondaries; the character file has exactly F1..F6 on
    14..19, matching the R47.1 live capture and necro.toml
  - entries 23..26: **belt 1..4** — defaults '1'..'4', matches BELT_KEYS
  - show-items (ALT) and any other needed function: label in P1 by
    scanning for the known default VK (0x12) in default.key
- The file is written by the client when bindings change; read at
  startup + re-read per game covers mid-session rebinds.

## Discovery: every keybinding site in the bot (the refactor inventory)

| site | what | janky? |
|---|---|---|
| `input/gated.py:55-88` | the VK constant block (SHIFT, CTRL, F1-F6, 1-4, UP/DOWN/RETURN, I, ALT) | codes fine; MEANINGS live in callers |
| `input/skills.py` `DEFAULT_HOTKEYS` | hardcoded skill-id → F-key table "as bound in the live client (R47.1)" | manual capture, goes stale on rebind |
| `input/skills.py` `BELT_KEYS` | keys 1-4 → belt columns | assumes default binding |
| `config/necro.toml [hotkeys]` + `combat.py _HOTKEY_VKS` | skill name → "f1".."f6" config, validated against a hardcoded name→VK map | operator must keep toml in sync with in-game bindings by hand |
| `execute.py` VK_MENU | ALT ground-label toggle | assumes default Show Items binding |
| `town` VK_I (belt.py refill) | inventory toggle | assumes default binding |
| `chat.py` VK_RETURN/VK_ESCAPE, `menu.py` VK_ESCAPE, `window.py` _VK_MENU | locally re-declared constants | duplication (ESC/Enter are FIXED UI keys in D2, not bindable — they stay constants, but declared once) |

## Decisions (made under the operator's pre-authorization)

1. **necro.toml `[hotkeys]` keeps its shape** (skill name → key name).
   The .key file cannot say WHICH skill sits on a hotkey slot (that
   assignment lives in the character save/client memory), so the toml
   remains the skill→key declaration — but the bot now **verifies** it:
   every configured key must appear as some skill-hotkey slot's
   primary/secondary in the character's .key file, else a loud
   ConfigError at build time naming the drift. Effect-verification
   (`ensure_right_skill`) remains the runtime truth, unchanged.
2. **Non-skill bindings come from the .key file directly**: inventory
   toggle, belt 1-4, show-items — replacing the hardcoded assumptions.
   Missing/unbound required function → loud refusal at build, listing
   what to bind.
3. **Fallback**: no .key file readable (drills on another machine, unit
   tests) → the current hardcoded defaults, with a printed notice. No
   behavior change for sims/tests.
4. **Path discovery**: from the running client's exe path (pymem gives
   it) → `../Save/ProjectD2/<char>.key`; character resolved by scanning
   `*.key` (exactly one → use it; several → `BotPaths` override
   required, loud error says so). Re-read at each engine build
   (per game) so mid-session rebinds are honored.
5. **Fixed UI keys** (ESC, Enter, arrows, chat) are not bindable in D2
   and stay constants — consolidated into the new module, imported
   everywhere else (removes the chat/menu/window duplicates).
6. New module `pd2bot/input/keys.py` = the single registry: VK codes,
   the fixed keys, the `KeyBindings` dataclass, the required-functions
   manifest. `pd2bot/input/keyfile.py` = the parser. gated.py keeps its
   send plumbing; its VK block moves to keys.py with re-exports for
   compatibility (existing imports keep working).

## Questions

None issued — the operator pre-authorized proceeding without questions
absent pressing design decisions; none qualified (every call above is
reversible and none touches safety invariants or spends money/time the
operator would want gated).

## Out of scope / future

- Reading skill→slot assignments from client memory (would make
  `[hotkeys]` fully automatic); revisit if the BH fork exposes it.
- PD2's BH overlay hotkeys (`BH.json`) — not used by the bot today.
- Rebinding-aware chat hazards (chat.py's docstring list) — unchanged.
