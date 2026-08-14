# P4 — Closed-loop pickup and honest failure

Part of [plan.md](plan.md). Size: `sm`. **Needs no game.** Largely
independent of P2's answer and **may be pulled forward** when game time
is delayed (the operator's 2026-08-06 constraint). Review gate: none.

## Why

Pickup is open-loop: project a screen point, click, hope, and notice on
a later tick whether the item left the ground. The operator's own
instinct — *"track the coordinates of dropped items, and the
coordinates of the mouse pointer, so that pickup can be reliable"* — is
the right shape even though the pointer half is measured shut (T60/T63,
see notes.md). This phase closes the loop with what we *can* observe.

## Scope

### 1. Attribute what a click actually produced

Today `collect` records `pending_pickup[unit_id]` and a later tick sees
the item gone. When a click picks up the **neighbour** instead — 9 of
13 misses in T71 run 4 — the bot records a success for the neighbour
and keeps burning clicks on the target, learning nothing.

Make the attribution explicit: when an item leaves the ground while a
*different* item was the click target, emit
`item.collected` with `attributed_to` naming the intended target, and
let `collect` treat that as evidence about the pile rather than a
neutral event. The mechanism is already half there — `confirm_pickups`
compares the ground against `pending_pickup`.

This is worth doing regardless of which direction P3 takes, and it is
what makes the "clicked A got B" rate a **standing metric** instead of
a one-off finding.

### 2. Stop spending the whole budget on a hopeless click

If the first N attempts produce no change to the ground *and* a
neighbour is present, the remaining attempts at the same offsets are
very unlikely to differ. Introduce an early, **loud** bail with a
distinct reason, rather than silently grinding to 8. Exact N is a
measured decision — P1's attempts histogram and P2's per-offset data
say where the knee is; do not invent it.

Constraint: this must not reintroduce the eagerness bug pattern (T70's
staircase re-click). A bail is a *write-off with a reason*, not a
shorter retry loop.

### 3. Unconflate the diagnoses

`collect`'s write-off currently reasons: potion + belt has room →
"click misses suspected"; potion + belt full → belt-full; non-potion →
inventory full. The last one is the weak link — **a non-potion that
will not come up is treated as the inventory-full tell**, and T71 run
4's flawless emerald and Nef rune were almost certainly click misses,
not a full inventory. With P1's `neighbours` count and P4's
attribution available, the diagnosis can distinguish:

- ground unchanged across every aim point, no neighbours → **aim
  failure for this item class** (the T65 kind-619 shape)
- ground changed but the wrong item came up → **pile ambiguity**
- clicks land, nothing moves, inventory genuinely full → **inventory
  full** (keep the existing behaviour, including the cleanse queue)

The inventory-full path's existing safeguards (the `cleanse_retried`
guard against the R173 loop) must survive unchanged.

### 4. The operator-facing alert should name the real suspect

The current alert says "click misses suspected" only for potions. Make
the alert carry the diagnosis from (3) for every class, with position
and neighbour count, so a run that leaves a rune behind says so in
words rather than in a correlation script.

## Files

- `pd2bot/behavior/steps.py` — `collect`, `confirm_pickups`.
- `pd2bot/runlog.py` / `docs/architecture/run-log.md` — the
  `attributed_to` field and the new write-off reasons.
- `docs/architecture/behavior.md` — the pickup section.
- `tests/test_behavior_steps.py`.

## Implementation notes

- The T56 lesson is in the code comments and must not be undone: a
  potion that will not come up means belt-full **only while the belt
  count agrees**. Extending the diagnosis must not weaken that check.
- Every new write-off reason needs a test that pins the *reason*, not
  just that a write-off happened — otherwise the diagnosis can rot into
  a constant string and nobody notices.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

## Agent reminders

Do not commit unless asked. Do not change the pickit's rules. Do not
weaken the belt/inventory reasoning. Stop and report if the
attribution turns out to need perception the snapshot does not carry.

## Definition of done

Attribution emitted and tested; the early bail in with a measured
threshold or explicitly deferred to P3's data; the three diagnoses
distinguished and pinned by tests; alerts name the suspect; docs
updated.

## Implementation result (2026-08-06)

- **§1 Attribution** — already landed with P1 (`attributed_to` on
  `item.collected`, surfaced by `runlog --pickup` as CLICKED-THE-NEIGHBOUR).
- **§3 Unconflated diagnoses + §4 alerts** — DONE. The write-off reason
  now names four causes (`_write_off_reason`), and — the real fix — a
  non-potion miss with a neighbour in reach is **pile ambiguity**, not a
  full inventory: it writes the one item off and keeps collecting,
  instead of setting `inventory_full` and abandoning every other
  non-potion item this game for a single missed rune in a pile. The
  no-neighbour case is unchanged (conservative full-grid suppression,
  honestly labelled "aim failure OR full inventory"). The belt-full vs
  click-miss reasoning (T56) is untouched. Alerts name the suspect for
  every class. Tests pin each reason and the pile-ambiguity behaviour.
- **§2 Early bail — DEFERRED, deliberately.** T76/T79 measured the click
  path as noise-dominated: collateral pickups land at *late* offsets
  (T79 saw a neighbour taken at offset 7), so bailing after N attempts
  would sacrifice real pickups for a marginal time saving. With the
  aim-tuning direction (P3) de-scoped and command-by-GID abandoned, the
  saving is not worth reintroducing the eagerness-bug risk (T70). The
  budget stays at the full schedule; the write-off is already loud.

1046 tests, ruff clean.
