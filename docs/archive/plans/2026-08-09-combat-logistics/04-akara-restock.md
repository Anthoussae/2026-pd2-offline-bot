# P4 — the Akara restock (and potions leave the pickit)

Size: md. Dependencies: P1. Review gate: none (standing mandate), but
the pickit removal ships ONLY with the live-proven chore (Q5).

## Scope

**A. Vendor stock perception** (`perception/items.py`): read the items
owned by an NPC unit — same item structures as the player's carried
items, filtered to the vendor's unit, each with kind and GRID CELL.
Per the user's Q4 refinement: stock layout is NOT assumed stable; the
chore reads (potion kind → cell) fresh on every visit. New function
`read_vendor_stock(session, npc_unit_id)`; potion typing reuses the
existing code table.

**B. Shop-grid calibration** (drill `drills/t85_shop_grid.py`): with
Akara's shop open, the operator hovers named cells on chat prompts;
the drill records the panel's grid ORIGIN and CELL SIZE in pixels
(fractions of the client rect, the uipoints convention) and
cross-checks: predicted pixel for a stocked cell vs `GetCursorPos` on
hover, ±4 px to pass. Furniture only — which cell holds what is
memory's job (A).

**C. The buy chore** (`behavior/town/services.py` — it is an NPC
service, beside heal/repair): open Akara's dialog (existing
`open_npc_dialog`), select the TRADE row (uipoints entry, the
charsi.trade_repair pattern), then loop: read stock → pick the
needed potion type (belt shortfall calculation already exists in
belt.py) → click its cell (right-click buys one; verify by BELT/GOLD
delta before the next click — command-vs-effect) → until belt full
per `[belt] columns` + minimums, or stock/gold exhausted (loud notice,
not a halt, unless below minimums — then the existing
BeltBelowMinimum path). ESC closes; effect-verified. Gold guard: stop
buying before gold hits a floor (`[town] restock_gold_floor`, default
5000, loader-validated).

**D. Preamble integration**: restock joins the preamble order after
heal, replacing the inventory-only refill as the belt's primary source
(refill-from-inventory stays as the fallback when already stocked —
cheaper than a shop trip). `run_preamble` ordering comment updated.

**E. Pickit removal (same commit as the proven chore)**: delete the
three potion rules; `potion_reserve` plumbing stays (harmless, other
rules may use it someday). Update pickit.toml's header comment.

## Live acceptance (standing mandate)

T85 calibration passes; then one restock drill from a deliberately
depleted belt (operator drinks a few pre-run): belt refills to full at
Akara, gold decreases plausibly, event log carries the new
`town.restock` events (bought counts per type). Then one full
cold-plains run that sustains on bought potions (no potion pickup —
census shows potions no longer wanted).

## Validation

Unit tests: stock read against fake vendor items (cells vary between
"visits" — the Q4 property), buy loop against the sim town (belt fills,
gold floor respected, verify-per-click), preamble ordering. pytest +
ruff; commit `feat: Akara restock chore; potions leave the pickit (R48
buy-half superseded)`.

## Reminders

Selling stays out of scope. No new input paths — PanelInput/points
only. If the shop panel's id or the TRADE row misbehaves live, that is
drill territory (measure, adjust uipoints), not code improvisation.
