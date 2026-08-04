# P1 — Perception extensions (skills, items, objects, corpses)

Part of [plan.md](plan.md) (M5). Size: `sm`. Dependencies: none — first
phase. Everything here is read-only perception plus constants; **no
input is sent in this phase** except by the user during live checks.

## Scope

Give M5's layers everything they need to *see*: the active skills, the
bone-armor absorb, monster corpses, object units (waypoint, stash),
carried items (belt columns, inventory grid), and the id tables that
name NPCs, potions and gold. Extend the dump CLI so every new read is
live-verifiable through the bridge.

Out of scope: any input, any behavior, panel geometry (P2/P3),
navigation changes.

## Context you need

- Read `pd2bot/offsets.py` top-to-bottom first: the citation
  convention (BH file:line, first address in each VARPTR macro is
  1.13c), the "no magic offsets anywhere else" rule, and the existing
  stat/unit constants. Source of truth is Project-Diablo-2/BH @ main
  (fetch from GitHub as needed); non-BH entries need dual independent
  citations (see the CollMap section precedent).
- `pd2bot/units.py`: `read_stats` works on **any** unit (full stat
  array, fixed-point decoded); `iter_units_of_type` is the
  de-duplicated hash-table walk; `scan_units` enforces locality.
- The ItemData location byte **lied live once** (R17: carried item
  read 0xFF and appeared as a ground item at its grid slot). Every
  ItemData-derived field in this phase needs live verification before
  anything downstream trusts it.
- Live checks run through the elevated bridge
  (`tools/elevated-bridge.ps1`, protocol in its header; queue at
  `%LOCALAPPDATA%\pd2bot-bridge`); the user starts it once and is
  present in-game per the request protocol (🔶 R-numbered, continue
  from the instruction log's highest id; log every request as a row).

## Work items

1. **Active skills** (`offsets.py` + new reads in `player.py` or a
   small `skills`-adjacent read in `units.py`): derive
   `UnitAny.pInfo` → Info → left/right `Skill*` → `SkillTxt`/id from
   BH `D2Structs.h` with citations. Expose
   `read_active_skills(session) -> (left_id, right_id) | None`.
   Record the necro's observed skill ids (Poison Strike, Bone Armor,
   Blood Warp, Desecrate, Revive, plus TP tome/bone wall as seen) as
   named constants after live capture — the user cycles F1–F6 while
   the dump reads them (one request covers all).
2. **Bone armor absorb**: derive the stat id(s) empirically by
   cast-and-diff — dump the player's full stat array, user casts Bone
   Armor (F1 + right-click in town), dump again, diff. Expect a
   current and a max id; cross-check against community
   ItemStatCost tables and cite both. Add `STAT_BONE_ARMOR*` to
   `offsets.py`. Fallback (user-approved, R47.5): if the read proves
   unreliable, P5 recasts on being hit instead — but attempt the stat
   read first.
3. **Monster corpses**: add `mode: int` to `Monster` (read
   `UNIT_MODE`, already an offset); determine the dead/dying mode
   values for monsters live (user kills something near the dump — or
   reuse an existing town corpse if any) and add constants. Add
   `Monster.is_corpse`. Keep `monsters`/`allies` semantics unchanged:
   corpses must not appear in `live_monsters`.
4. **Object units**: extend `units.py` to scan
   `UNIT_TYPE_OBJECT` (2). Objects use a static path (coordinates
   layout differs from monsters *and* items — derive from BH
   `D2Structs.h` with citation; expect DWORD x/y like ItemPath).
   New `GameObject` dataclass: `unit_id`, `kind` (TxtFileNo),
   `position`, `mode`. Identify the **Act 1 town waypoint** and the
   **stash chest** kinds live (dump near each; user stands by them)
   and record constants; cross-cite a community object-id table.
   Add objects to `UnitScan`/`GameSnapshot`.
5. **Carried items** (new `pd2bot/items.py`): enumerate item units
   whose owner is the player, classified by container — equipped /
   inventory (grid x, y) / belt (slot index → column = slot % 4, row
   = slot // 4) / stash / cursor. Derive the ItemData fields
   (location enum, body location, grid position, owner) from BH
   `D2Structs.h` ItemData with citations, and **verify live against
   R17's known trap**: user moves a potion between inventory, belt
   and stash while the dump watches; every classification must match
   what the user sees before this module is trusted. Expose:
   `read_carried_items(session) -> CarriedItems` with
   `belt_counts_by_column`, `inventory_items`, `free_inventory_cells`
   (grid occupancy from item sizes — if item dimensions are not
   cheaply derivable, expose occupied cells only and let P3 treat
   "deposit didn't shrink the list" as the guardrail signal instead).
6. **Id tables** (`offsets.py`): potion kinds (healing/mana tiers +
   rejuv small/full — needed for pickit and belt logic), gold kind,
   Act 1 NPC kinds for **Akara** and **Kashya** (verify live: dump
   allies in town, user says who is who by position), waypoint +
   stash object kinds (item 4). Cite community tables; mark each
   "verified live" once confirmed.
7. **Merc & revive counting**: helpers on the snapshot or in
   `units.py` — `merc` (ally with `merc_kind`, hp > 0), and
   `revive_count` = allies that are not the merc, **outside town
   only** (in town, friendly NPCs pollute the count; town is
   detectable via `Area.level_no in TOWN_AREAS`). Note the caveat in
   a comment: bone walls, if ever cast, may appear as allied units —
   F4 is unused in M5.
8. **Dump CLI** (`dump.py`): new sections — active skills, belt/
   inventory summary, nearby objects, corpse count, merc/revives.
   This is the live-verification instrument for everything above.

## Live verification (via bridge + user requests)

One consolidated in-town session covers items 1, 2, 5, 6 (skills
cycle, bone-armor cast-diff, potion shuffle, NPC identification,
waypoint/stash dump); one short out-of-town moment covers 3 and 7
(a corpse and the revive count — the user can do this manually near
the town exit at their own judgment; the bot sends nothing). Batch
the game-side asks into as few requests as possible.

## Conventions and reminders

- Every offset cited; no magic numbers outside `offsets.py`.
- Torn-read posture: bounded walks, skip-don't-raise, per the
  existing `units.py` style. Match comment density and house voice.
- Tests: fakes for all parsing/classification logic (belt slot math,
  container classification, corpse filtering, id tables), following
  `tests/` patterns. No test touches the game.
- Do not commit unless the user asked. Do not expand scope. Do not
  suppress warnings or disable tests. Stop and report if a derivation
  disagrees with live reality — that is signal, not noise (R17).
- Report at the end: what changed, live-verification outcomes,
  deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

Plus the live dump checks above, outcomes logged in
`docs/instruction-log.md`.

## Definition of done

All new reads live-verified against the running client; dump shows
skills/belt/objects/corpses/merc correctly; id constants recorded with
citations + "verified live" marks; tests and lint green; no input was
ever sent by new code. ADR expectation: none for this phase.

## Implementation Result

Status: done
Completed: 2026-07-29
Commit: pending

- Changed: `offsets.py` (skills chain, skill ids, bone-armor stats,
  ItemData location bytes, storage/node enums, monster corpse modes,
  ObjectPath, PD2 potion kinds, NPC/object tables), `units.py`
  (Monster.mode/is_corpse, corpse routing, GameObject + object scan),
  `player.py` (`read_active_skills`), new `items.py` (carried items,
  belt math, cursor-item pointer read), `snapshot.py` (corpses,
  objects, skills, merc/revives/in_town), `dump.py` (skills line,
  objects/corpses/merc sections, `--carried [--watch]`), tests
  (+16, now 211).
- Validated: `pytest -q` 211 passed; `ruff check .` clean; live
  drills bridge 030–035 all PASS (see notes.md "P1 live-verification
  findings" and instruction log R51–R52).
- Deviations: potion id tables rebuilt from live observation after
  discovering PD2 renumbered them (kolbot's classic ids discarded);
  cursor-item read added mid-phase on a live finding; gold kind 523
  demoted to unverified pending a live drop; corpse-kill drill
  skipped as unnecessary (town corpses sufficed). Open: R53 (potion
  tier naming, the 606 column-4 ambiguity); bone-armor falls-when-hit
  confirmation deferred to P6 stage B.
