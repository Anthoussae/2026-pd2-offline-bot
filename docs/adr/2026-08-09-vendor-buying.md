# ADR: the bot may BUY from vendors (superseding R48's buy half)

Date: 2026-08-09
Status: accepted (implementation live-gated; pickit potion rules leave
only with the proven chore — R241 Q5)
Plan: docs/plans/2026-08-09-combat-logistics/ (R241 Q4)

## Context

R48 (M5) deliberately gave the bot no vendor UI: belt refill was
inventory-only, and running short meant a loud halt for a manual
restock. The cost surfaced twice over: a recurring manual-restock
provision cluster in the instruction log (R178/R180/R204), and potion
pickup being a measured time sink (tiny label-only click targets, the
worst class in T76). Meanwhile the Charsi repair flow had already
proven the dialog-row → shop-screen driving pattern, effect-verified.

## Decision

The bot may **buy** — specifically, potions from Akara, as a town
chore that fills the belt to its configured minimums. Selling remains
excluded (unchanged half of R48). Two principles bind the
implementation:

1. **Stock is perception, geometry is calibration** (the user's Q4
   point): WHICH potion sits in WHICH shop cell is read fresh from the
   vendor's own item chain every visit (`read_vendor_stock`); only the
   panel's fixed furniture — grid origin and cell size — is
   hover-calibrated (T85), and every buy click is effect-verified
   (belt/gold delta) before the next.
2. **Never a gap with neither source**: the potion pickup rules leave
   config/pickit.toml in the SAME commit that lands the live-proven
   chore. The belt-minimum halt stays as the last-resort floor.

## Alternatives rejected

- **Keep manual restocking** — the provision cluster is exactly the
  toil the request log exists to engineer away.
- **Fix potion pickup instead** — aims at the measured worst case of
  the aiming problem; buying sidesteps it entirely.
- **General vendor trading (buy+sell)** — no current need; selling
  reopens inventory-management questions this plan does not owe.

## Consequences

Gold becomes a consumed resource (guarded by a configured floor);
town time grows by one NPC visit when the belt is short; the
inventory-only refill remains as the cheaper first resort when
potions are already carried.
