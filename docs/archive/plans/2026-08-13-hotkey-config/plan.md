---
kind: plan
size: md
depth: implementation
status: done
repo: 2026-pd2-offline-bot
created: 2026-08-13
completed: 2026-08-13
commit: 53099c7 (phases d32d2c4/5550032/9d0b59f)
adr: expected
---

# Read the real hotkey config, consolidate every keybinding

## Goal

The bot reads the character's actual keybindings from the client's own
per-character `.key` file instead of assuming defaults, verifies the
class config's skill hotkeys against it, and every keybinding the code
knows about lives in one registry. A rebound client produces a loud,
named refusal at build time — never a silently mis-aimed keypress.

Size **md**: three code phases plus closeout — each `sm`, but the
consumer refactor touches input, behavior, town and wiring, and wants
its own validation pass. Implementation pre-authorized by the operator
(see notes.md); no review gates.

## Acceptance criteria

- `pd2bot/input/keyfile.py` parses both observed framings of the .key
  format via self-validating records; unit-tested against byte fixtures
  built from the live files' shapes.
- `pd2bot/input/keys.py` is the single home of: VK codes, fixed UI
  keys, the function-index labels, `KeyBindings`, and the required-
  functions manifest. chat/menu/window/gated duplicates are gone
  (compat re-exports allowed).
- `build_bot` loads the character's bindings (path discovered from the
  client process; `BotPaths` override), re-reads per engine build, and
  REFUSES loudly when a required function is unbound or the toml's
  skill keys are not present in the file.
- skills.py / execute.py / town use the registry: no more
  `DEFAULT_HOTKEYS`-as-truth, `BELT_KEYS`-as-assumption, bare `VK_I`
  or `VK_MENU` meaning-assumptions outside keys.py.
- Fallback: no client/.key reachable → current defaults + notice; sims
  and tests unchanged.
- Full suite + ruff green; live proof: one T87-style trip runs clean on
  the refactored path, and a short T89 demonstration prints the
  detected bindings for the operator.
- ADR recorded (external data contract + config-verification
  semantics). Docs: input/README.md, run-log/architecture touchpoints,
  teach explainer at closeout.

## Discovery summary

See `notes.md` — the format is already empirically pinned (records,
labels, both framings), the refactor inventory is enumerated, and the
design calls are recorded under the operator's pre-authorization.

## Phases

| Phase | Size | Summary | Files/modules | Review gate |
|---|---|---|---|---|
| P1 | sm | `.key` parser + fixtures | `input/keyfile.py`, `tests/input/test_keyfile.py` | none |
| P2 | sm | the registry; dedupe fixed keys | `input/keys.py`, `gated/chat/menu/window` | none |
| P3 | sm | consumers + wiring + verification | `skills/execute/town/combat/wiring` | none |
| P4 | sm | live proof, ADR, docs, cleanup | drill T89, `docs/adr/*`, READMEs | none |

## Validation

- `~\.venvs\pd2bot\Scripts\python.exe -m pytest` (repo root) + `ruff check .`
- Live (bridge): parse the real file and print bindings (T89); one
  `runs/t87-black-marsh-trips.toml` game on the refactored path.
