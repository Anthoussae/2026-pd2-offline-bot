# P5 — The item-exception registry: everything with a special click

Part of [plan.md](plan.md). Size: `sm`. **Mostly needs no game** — the
one live piece is T77, a read-only map probe. Independent of P2/P3, so
it can run whenever. Review gate: none.

Folded in at the operator's request (2026-08-06): *"scrolls of identify,
maps, and scrolls of town portal also have unique abilities when clicked
on, that could bug our inventory management/stash/cleanup routines. It
might be wise to add a clause for handling those as well, and perhaps
group all of these exceptions in some sensible manner."*

## Why it belongs in this plan

Same failure family as the pickup work: an item whose click does
something we did not ask for. The cleanse aims a **ctrl+right-click** at
junk and the stash deposit aims a **shift+right-click** at everything;
when a modifier is dropped, the bare right-click fires — and on the
wrong item that arms a cursor or opens a portal that outlives the click
and poisons everything after it. That is R112/R113 and T70 run 2, twice
on the same tome, fifteen days apart.

## The gap, already known and unclosed

`offsets.py` says so itself at the definition of
`RIGHT_CLICK_HAZARD_KINDS`:

> *"Individual TP/ID scrolls belong here too and are not in the
> vocabulary yet; they get added the moment a drill reads one."*

The ids have been sitting in the live-generated code table the whole
time (`config/item_codes.toml`, from T42):

| kind | code | item | today |
|---|---|---|---|
| 533 | `tbk` | Tome of Town Portal | handled |
| 534 | `ibk` | Tome of Identify | handled |
| **544** | **`tsc`** | **Scroll of Town Portal** | **unhandled** |
| **545** | **`isc`** | **Scroll of Identify** | **unhandled** |

A loose **Scroll of Identify is worse than the tome**: it is junk, so the
cleanse will actually aim at it, and a dropped modifier arms the identify
cursor — the R112 failure with a cheaper item and no reason to keep it.

**Maps** are not in the code table under any name (searched: no `map`,
`dun`, `por` entry), so their kind must be READ, never guessed — R144's
whole point, bought by six wrong elite armours and a Wire Fleece picked
up as a Kraken Shell. `drills/t77_map_identity.py` does that: read-only,
diffs the floor before and after the operator drops maps, and answers
the question that decides the fix's shape — **one kind or many?**

There is also a `quest_and_map_items` list (22 entries, R117) in
`config/item_ids.toml`, partly resolved in `item_ids.learned.toml`
(`wss`, `lbox`, `rkey`, `pk1`, `dcso`…). It is currently **only a pickit
keep rule** — it does not protect those items from the drop or transfer
gestures at all.

## The grouping problem

Two overlapping frozensets today, with the tomes hand-listed in both and
~70 lines of reasoning spread around them:

- `UNMOVABLE_KINDS` — never **shift+right-click** (the transfer gesture)
- `RIGHT_CLICK_HAZARD_KINDS` — never **ctrl+right-click** (the drop
  gesture); `POTION_KINDS` plus the tomes

That does not scale to scrolls, maps and quest items, and "which set do
I add this to?" has no principled answer today.

### Proposed shape

One registry keyed by kind, recording *what the bare right-click does*
and therefore which gestures are unsafe — with both existing sets
**derived** from it so no call site changes:

```python
@dataclass(frozen=True)
class ItemException:
    reason: str          # operator-facing: "right-click opens a portal"
    no_transfer: bool    # shift+right-click is unsafe (stash/deposit)
    no_drop: bool        # ctrl+right-click is unsafe (cleanse)
    policy: bool = False # protected by DECISION, not just mechanics
```

`policy` carries the Cube's R172 status — *always* protected whatever
else changes about item handling — which is currently only a comment and
would be lost by a mechanical refactor.

Derive `UNMOVABLE_KINDS` and `RIGHT_CLICK_HAZARD_KINDS` from it, keep
`unmovable_reason()` working, and add the new members: both scrolls, the
maps T77 names, and the resolved quest items.

## Scope boundaries

- **Do not change the gestures themselves**, only which items they are
  aimed at. The modifier settle (`_MODIFIER_SETTLE_S`) stays as is; it
  was the right fix at the wrong layer and removing it is a separate
  decision.
- **Do not** make any currently-kept item droppable, or vice versa,
  except by adding exceptions. Exclusion is the safe direction: an item
  wrongly excluded is left alone, an item wrongly included is used.
- The Cube's policy protection is not to be weakened by the refactor —
  it is a user decision (R172), not an implementation detail.

## Files

- `pd2bot/offsets.py` — the registry and the derived sets.
- `pd2bot/items.py` — `movable` (already reads `UNMOVABLE_KINDS`).
- `pd2bot/town.py` — cleanse and deposit call sites; check they read the
  derived sets rather than re-listing kinds.
- `config/item_ids.learned.toml` — map codes once T77 names them.
- `drills/t77_map_identity.py` — written; needs one live run.
- `docs/architecture/behavior.md` or `perception.md` — wherever item
  handling policy is documented.
- `tests/` — one test per exception member, asserting the *reason*, not
  just membership.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

Plus: T77 run, its output captured here as `t77-map-identity.md`, and
the derived sets asserted equal to today's values plus the new members —
a refactor that silently *dropped* a member would reintroduce R112.

## Agent reminders

Do not commit unless asked. Do not guess a kind id — if T77 has not
named maps yet, add the scrolls (which the code table already knows) and
leave maps as a named gap rather than a numeric guess. Do not expand
into the pickit's rules. Report deviations.

## Definition of done

The registry exists with both sets derived from it; scrolls 544/545 are
members; maps are members or explicitly recorded as unnamed pending T77;
the Cube's policy status survives; every member has a test pinning its
reason; docs updated.
