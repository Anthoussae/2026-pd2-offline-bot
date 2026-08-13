# P1 — offline build (sm)

Everything buildable without the game. Self-contained; read
[plan.md](plan.md) and [notes.md](notes.md) for the why.

## Scope

1. **`tagmode_battery` step** (`pd2bot/behavior/steps/`, new module,
   registered in the registry with params `cycles` (default 5),
   `round_seconds` (default 30), `modes` (default `[1, 2, 3]`)).
   Behavior per cycle, per mode:
   - **Mode set**: read `label_display_on`; press `bindings.show_items`
     only when the read disagrees with the target (parity-safe, the
     T66 policy). For mode 3, press F (VK 0x46) and verify by the
     probe's flag if `offsets` carries one, else `run.say` a chat
     confirm ("mode 3 set — tags should read DEFAULT; 'abort' if
     not") with a short patience window. Announce every switch.
   - **Drop phase**: inventory open, stash closed; enumerate
     `main_inventory`; drop every item that is movable, not in
     `RIGHT_CLICK_HAZARD_KINDS`, via the town layer's `drop_item`
     (its stop-on-first-failure policy stands). Record the manifest:
     unit id at drop time is unreliable across the floor transition
     (id churn is a known fact), so the manifest keys on (kind,
     quality, sockets) multiset + count, and each entry carries the
     pickit verdict (`cleanse_keep`-style, permissive) taken at drop
     time. Close panels.
   - **Test phase**: the engine's real pickup machinery aimed ONLY at
     whitelisted ground items (the pickit's own `wants`), capped at
     `round_seconds`, ending EARLY when no wanted droppable remains
     on the floor. Walk-radius = the drop scatter is at the feet, so
     the existing pickup step's enumeration radius is fine.
   - **Reset phase**: gather EVERY ground item that matches the
     manifest (direct `PickUpItem` actions, no pickit gate), until
     the carried census accounts for the full manifest or nothing
     eligible remains on the floor; discrepancies are announced, and
     a shortfall REFUSES to start the next round (safety property —
     see notes.md item 5).
   - **Events**: emit `battery.round` (mode, cycle, manifest census,
     phase timestamps) through the run-log envelope; the item stream
     (`action.pickup_attempt`, `item.collected`, `item.abandoned`)
     already carries the per-item record. Schema documented in
     `docs/architecture/run-log.md`; envelope keys are inviolable
     (yesterday's clobber lesson — no field named `kind`).
2. **Run file** `runs/t90-tagmode-battery.toml`: steps =
   `tagmode_battery`, `done`. NO `town_preamble` (chores suspended by
   construction). `mandatory_pickup` absent.
3. **Executor knob** (`pd2bot/behavior/execute.py`): the `_pick_up`
   label force-on becomes conditional on an executor/config flag
   (`enforce_label_display`, default True — every existing run
   unchanged, pinned by test). The battery step sets it False for
   mode-1 rounds only.
4. **F-flag probe drill** (`drills/t91_filter_flag.py`): T66's
   protocol verbatim with key F — snapshot BH.dll writable memory,
   4 presses, keep bytes alternating in lockstep; report
   module+offset+values ready for offsets.py. Autonomous, ends on its
   own, standard abort paths. (Confirm free test id against
   `docs/drill-log.md` before wiring: T90 is the battery, T91 the
   probe, per project-state's next-test counter.)
5. **Tabulator**: `python -m pd2bot.runlog <dir> --tagmode` — per
   round: mode, whitelisted dropped/collected, time-to-last-wanted,
   junk collected during test phase, abandonment reasons; per mode:
   means over rounds. Unit-tested against a synthetic events.jsonl.
6. **Tests**: step round/manifest/mode-sequencing logic against the
   test fakes (the envelope-collision-detecting fake from yesterday);
   executor knob default pinned; tabulator; run-file lint passes the
   registry.
7. **Docs**: run-log.md event section, steps README row, this plan
   dir's notes updated with any deviation.

## Out of scope

Live anything; changing the default label policy; pickit rules.

## Conventions

- Bounded waits that poll safety (`_wait` pattern) — nothing may
  starve the monitor (ADR 2026-08-07).
- Step names in run files are API — pick `tagmode_battery` once.
- Run-log rules: never raises, never blocks, honest absence.
- Comment density/idiom: match the neighboring steps (clear.py,
  services.py).

## Validation

```
~\.venvs\pd2bot\Scripts\python.exe -m pytest
```

```
ruff check .
```

## Definition of done

Suite green, ruff clean, run file lints, no live contact. Report
deviations. Do not commit unless asked; do not expand scope; stop on
ambiguity.

## Implementation Result

Status: done
Completed: 2026-08-13
Commit: pending

- Changed: `pd2bot/behavior/steps/tagmode.py` (new — the battery step,
  a per-tick phase machine: begin/set_mode/drop/test/gather/final);
  `pd2bot/behavior/steps/services.py` (+9 wired-closure fields, all
  None-defaulted); `pd2bot/behavior/steps/registry.py` +
  `pd2bot/behavior/run.py` (both registries, mirrored);
  `pd2bot/behavior/steps/__init__.py` (export);
  `pd2bot/behavior/execute.py` (`enforce_label_display`, default True);
  `pd2bot/input/keys.py` (`VK_F` + why it is bound nowhere);
  `pd2bot/wiring.py` (services wired: town drop/open-inventory,
  label flag reader, key presses, executor knob, chat channel);
  `runs/t90-tagmode-battery.toml` (new); `drills/t91_filter_flag.py`
  (new — T66's protocol on key F); `pd2bot/runlog/events.py`
  (`tagmode_report` + `--tagmode`); docs (run-log.md event section,
  steps README row); tests (`tests/behavior/test_tagmode.py` 9 tests
  incl. one full simulated cycle, `tests/runlog/test_tagmode_report.py`
  3 tests, 2 executor-knob tests, registry-vocabulary pin updated,
  shipped-run lint).
- Validated: full suite **1289 passed**, ruff clean.
- Deviations: (1) the gather phase has NO deadline — the plan's
  `gather_seconds` cap was dropped in favor of hold-open-and-nag with
  periodic write-off re-arming, because "never lose an item" outranks
  "finish the battery" and clicking keeps the engine's never-idle
  honest; (2) drops scatter over 4 points (±4 subtiles) so a round is
  small clusters, not one confounding mega-pile; (3) events grew to
  `battery.begin/mode/round/loss/end` (the plan named only
  `battery.round`) so the tabulator needs no side-channel state.
