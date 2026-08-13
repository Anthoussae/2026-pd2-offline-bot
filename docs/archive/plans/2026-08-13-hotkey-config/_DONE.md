---
kind: implementation-log
status: done
repo: 2026-pd2-offline-bot
plan: plan.md
completed: 2026-08-13
commit: see per-phase commits d32d2c4 / 5550032 / 9d0b59f / 53099c7 (+ closeout)
adrs:
  - docs/adr/2026-08-13-keybindings-from-the-client.md
---

# DONE — the bot reads the real hotkey config (R247)

## Outcome

All four phases complete, same session as the plan, under the
operator's pre-authorization. The client's per-character `.key` file is
now the source of truth for bindings; the class config is verified
against it at every game build; every keybinding the code knows lives
in `pd2bot/input/keys.py`; a rebound client refuses loudly at build
time instead of failing silently mid-run.

## Completed work

- **P1** (`d32d2c4`): `input/keyfile.py` — self-validating parser for
  both observed framings; labels pinned live (inventory=1, skills
  14..21, belt 23..26, Show Items 37 in PD2's list vs 63 in
  vanilla's — the divergence is documented in the module); 6 tests.
- **P2** (`5550032`): `input/keys.py` — VK codes (provenance comments
  moved intact), fixed UI keys declared once, `KeyBindings` +
  `default_bindings()` + `load_bindings()` with the required-functions
  refusal and the Show Items ALT fallback-with-note. gated.py
  re-exports; chat/menu/window dedupe (chat's VK_ESCAPE turned out to
  be dead code and is gone); 8 tests.
- **P3** (`9d0b59f`): consumers press the resolved layout — belt
  drink/merc chord, inventory toggle (town layer holder attribute,
  runlog-style), Show Items in the executor; `discover_keyfile` (exe
  path via QueryFullProcessImageNameW) + `resolve_bindings` +
  `verify_skill_hotkeys` in keys.py; wiring loads/verifies PER GAME;
  `BotPaths.keyfile` override; 6 tests.
- **P4** (`53099c7` + closeout): T89 demonstration drill, ADR, input
  README rows.

## Validation

- Offline: 1275 tests green, ruff clean (full suite after every phase).
- Live T89 (bridge, 05:0x): discovery found
  `Save\ProjectD2\MaqiuDoubing.key`; table printed the operator's real
  layout (I/B, F1..F8, 1..4, Alt + a PD2 extended secondary 0x101);
  toml verification 6/6 OK; **6/6 configured hotkeys effect-verified in
  a live game**. Registered in the drill log.
- Live trip: one t87-black-marsh game on the refactored launch path —
  clean (cycles 1/1, waypoint+done, no key-attributable refusals).

## Deviations

- chat.py's local VK_ESCAPE was deleted rather than deduped (it was
  never used — found by the linter during P2).
- The executor's drink/merc trace lines now name the actual key
  (`key 1` → `key <name>`), a small honesty upgrade over the plan.

## Documentation

- `pd2bot/input/README.md` — keys.py/keyfile.py rows.
- ADR accepted: `docs/adr/2026-08-13-keybindings-from-the-client.md`.
- The teach explainer folds into the combat-logistics cycle's closeout
  (P6) per the plan — this detour's concepts (the .key contract,
  self-validating parsing, declare-vs-verify config) go in that pass.

## Follow-ups (out of scope)

- Reading skill→slot assignments from client memory (would make
  `[hotkeys]` fully automatic).
- BH overlay hotkeys (`BH.json`) — unused by the bot today.
