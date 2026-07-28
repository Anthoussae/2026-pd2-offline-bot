---
kind: implementation-log
status: done
repo: 2026-pd2-offline-bot
plan: plan.md
completed: 2026-07-28
commit: f5359ee
adrs:
  - docs/adr/2026-07-28-runtime-offset-discovery.md
---

# Implementation log — M2 perception core

## Outcome

**Done.** `pd2bot/` reads the live PD2 client and produces a correct,
coherent snapshot: player, current area, map seed, nearby monsters and
ground items, and UI state with a trustworthy "may we act" answer. All
five phases complete; 49 tests pass; live verification done against the
running Season 13 client while the user played.

Two caveats, both recorded honestly below: **ruff could not be installed**
(environment, not code), and **ground-item enumeration is untested live**
because no items happened to be on the floor during observation.

## Completed work

- **P1** package skeleton, `GameSession` (attach, elevation error, module
  base, typed reads), `offsets.py` with every constant cited to its BH
  source line.
- **P2** UI-state discovery by parsing the client's own machine code, plus
  `is_in_game` / `ui_state` / `can_act`.
- **P3** player state (identity, level, act, position, stats, gold,
  experience), current area, map seed.
- **P4** monster and ground-item enumeration by room traversal, bounded
  against torn reads.
- **P5** `GameSnapshot` + `Perception`, the `pd2bot.dump` CLI,
  `docs/architecture/perception.md`, README, teach explainer + glossary.

## Validation commands and results

- `python -m pytest -q` → **49 passed**.
- Stopgap lint (unused imports, line length) → clean. See caveat.
- `python -m pd2bot.dump -v` against the live client, several runs:
  correct name/level/act/position/stats/gold/seed; monsters enumerated
  with positions, health and class flags; `can_act` correct after the UI
  fix.
- UI calibration run with the user toggling panels: inventory, character,
  **esc menu (0x09)** and automap (0x0A) all confirmed to toggle exactly
  with their panels.

## What live verification caught that tests could not

Three real bugs, none of which a test suite would have found, because each
was about *meaning* rather than logic:

1. **Tile vs subtile.** Levels are measured in tiles, units in subtiles,
   five to a tile. `Area.contains()` compared them directly — wrong by 5x
   while looking entirely plausible.
2. **The UI array is not a row of booleans.** Several slots are always on
   (`UI_GAME` means "in a game"; `0x06`, `0x13`, `0x23` are internal; one
   is *inversely* tied to the esc menu). Treating every nonzero slot as an
   open panel made `can_act()` report NO during ordinary play.
3. **A torn-read hole in the traversal** (found while writing tests): the
   room-walk generator's own pointer read sat outside the caller's
   exception handling, so a dangling pointer would have propagated — the
   exact case the design claimed to survive.

Together with M1's base-vs-full stat bug, that is four semantic errors
caught by looking at reality and zero caught by type checking. The
"compare every field against what the game displays" rule earned its place
in the plan.

## Deviations from the plan

1. **No editable install; venv outside the repo.** `pip install -e .`
   crawls the repo (OneDrive + the large gitignored `kolbot/` clone) and
   hung for over ten minutes. The package is imported from the repo root
   via pytest's `pythonpath`; the venv lives at `~/.venvs/pd2bot`. Both
   documented in the README and `pyproject.toml`.
2. **ruff not installed** — see caveats.
3. Unit primitives landed in `units.py` (P4's file) rather than being
   duplicated in P3's, since both need them.
4. Area verification covered acts 1/2/5 rather than the two named areas.

## Caveats — what is genuinely not done

- **Real lint has never run.** PyPI's file CDN (`files.pythonhosted.org`)
  times out repeatedly on ruff's 11.9 MB wheel; pypi.org itself responds,
  and other large downloads on this machine have been failing too. A
  stopgap AST check covering unused imports and line length was written
  and is clean, but it is not ruff. **Run `ruff check .` and
  `ruff format --check .` when the network allows.**
- **Ground-item enumeration is not live-verified.** Covered by tests
  including the carried-vs-on-the-floor distinction, but no item was on
  the floor during observation. To close: drop an item, run the dump,
  pick it up.

## Documentation updated

`docs/architecture/perception.md` (new — the first component doc: the
read chains, the stat trap, room traversal, the UI-array discovery, and a
post-patch re-verification procedure), `README.md` (setup, Administrator
requirement, how to run the dump), and the teach artifacts.

## ADRs created

`docs/adr/2026-07-28-runtime-offset-discovery.md` — deriving an address by
reading the game's own instructions instead of hardcoding it.

## Follow-up work outside this milestone

- Run real lint; consider committing a lockfile once the network cooperates.
- Live-verify ground items.
- `CollMap` layout is **not** in BH — M3 must source it elsewhere
  (kolbot's d2bs source, Diablo-II-Address-Table, d2info).
- M3's input layer must gate on `can_act()` **and** window foreground.
- Perception range is the player's room and its neighbours; M3's global
  routing needs generated maps, not a wider read.
