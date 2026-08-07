# Item pickup overhaul — planning notes

Discovery log. Trigger (operator, 2026-08-06):

> *"I've definitely seen D2 bots that INSTANTLY pick up items, nearly
> frame-perfectly, and they did so 25 years ago on very slow and crude
> hardware. Such a technology should be within our grasp… Our current
> item pickup algorithm is slow and inaccurate. It may be necessary to
> separate out the 'item detection' problem from the 'item pickup'
> problem too, so that there isn't conceptual bleed."*

The operator is right on every count, and the kolbot source in the repo
proves the mechanism. This is a design analysis, not a tweak.

## The core finding: the fast bots do not click the screen at all

`kolbot/d2bs/kolbot/libs/core/Packet.js::click` is the "instant" pickup
(`Config.FastPick`). In full:

```js
click: function (who, toCursor = false) {
  new PacketBuilder()
    .byte(sdk.packets.send.PickupItem)   // 0x16
    .dword(sdk.unittype.Item)            // 4
    .dword(who.gid)                      // the item's unit id
    .dword(toCursor ? 1 : 0)
    .send();
}
```

**There are no screen coordinates.** The item is addressed by its GID
(unit id) and the game does the pickup. It cannot miss, because there is
no aim — the identity IS the address. Screen clicking (`Misc.click(0, 0,
item)`) exists only as the retry-3 fallback after the packet path fails.
That is the "frame-perfect, 25-year-old-hardware" pickup the operator
remembers: it was never a fast *click*, it was a *command*.

`itemToCursor` (belt/stash moves) is the same shape — `PickupBufferItem`
by GID, looped up to 15× against `me.itemoncursor`. Everything kolbot
does to items is command-by-GID, verified by reading the unit back.

## The two problems, correctly separated (the operator's point)

The current `_PickupMixin` tangles them, and the tangle is why accuracy
work keeps hitting the wrong layer:

| problem | question | our current tool | how good |
|---|---|---|---|
| **Detection** | which items are on the floor, which does the pickit want, where/what/GID | memory reads (`units._read_ground_item`, `pickit.decide`) | **accurate** — we are never wrong about *what* is there |
| **Actuation** | get *this specific known item* off the ground and into inventory | synthetic screen click, projected + sprite-offset-guessed + hit-tested by the game | **the broken half** |

They should be two modules with one interface between them:

- **`ItemScan`** (detection): the floor as data — `(gid, kind, position,
  class, quality, sockets)`. No input, no aim, no notion of clicking.
  Most of this exists inside `units.py` and `_PickupMixin.wanted_items`
  already; it just is not named as its own thing.
- **`Actuator`** (pickup): given a target `(gid, position)`, get it into
  inventory and confirm it left the ground. The *mechanism* lives here
  and behind this seam it is swappable — a screen click today, a command
  tomorrow — without detection knowing or caring.

The accuracy/speed work then targets the Actuator alone, and the
whitelist-accuracy work (T76's original charge) targets detection alone.
No conceptual bleed. This separation is worth doing **regardless of
which actuation mechanism wins**, and it is what makes a command-based
actuator insertable later without a rewrite.

## Why the current actuator cannot be fast or reliable

It is **aim-based**, and aim has a hard ceiling: the game's own
screen-space hit-test. We measured the ceiling directly (T76 run 2,
2026-08-06):

- in a dense pile, **7 of 8 targets could not be picked at all**, each
  spending the full 8-offset schedule;
- the leading offset won **1 of 15** targets; winners scattered across
  four offsets with no stable per-class or per-crowding pattern;
- worst case is **8 attempts × 1.5 s = 12 s of clicking per item**, and
  it still fails.

No reordering of a fixed offset schedule fixes "no offset works." Aim is
the wrong primitive for a problem the game will solve exactly if asked by
GID.

## The architectural fork

The project's actuation is, by ADR (`2026-07-28-python-out-of-process-
perception`), **out-of-process synthetic input** — `SendInput` only. We
have never issued a `WriteProcessMemory`; `memory.py` is read-only
(`u32`, `ptr`, no write). Command-by-GID needs a capability we do not
have, so this is a real decision, not an implementation detail.

### Path A — better aim (stay within the current capability)

Improve the synthetic click: draw-order collection (top sprite first so
it uncovers the next), step-and-reproject instead of 8 clicks from one
spot, read label geometry if a BH.dll structure exposes it (T76's probe
only scanned the item's own unit block, not BH.dll where the loot filter
and the T66 label flag live).

- *Pro*: no new capability, no new risk, no ADR change. Captures real
  wins (draw-order + reproject alone should kill most of the pile
  failures).
- *Con*: the ceiling is still the hit-test. Never frame-perfect. Charms
  and runes (label-only sprites) may stay hard. This is polishing the
  primitive the fast bots abandoned.

### Path B — command-by-GID (a new actuation capability)

Do what kolbot/koolo do: get the game to pick the item by its unit id.
Out-of-process, two known techniques, both needing memory **writes**:

1. **Remote function call** — `CreateRemoteThread` (or a thread-hijack)
   to call D2's own item-pickup handler with our args. This is what
   **koolo** (the Go out-of-process bot our own ADR cites) does — it is
   the existence proof that a *non-injected, out-of-process* bot picks
   frame-perfectly. Needs the function address + calling convention;
   BH is the source, as for every offset.
2. **Packet-into-buffer** — write the 0x16 packet into the client's own
   receive path and let its dispatch process it. In offline SP there is
   no socket, but the client still runs a local packet loop; whether it
   is reachable by an out-of-process write is a spike question.

- *Pro*: frame-perfect, GID-addressed, zero aim, near-instant. Retires
  the entire accuracy problem for pickup, and most of the speed problem.
- *Con*: a genuinely new and **dangerous** capability — a bad remote
  call crashes the client. Reopens the actuation half of the ADR ("input
  is the dangerous half"). Needs a careful, isolated spike with a
  hard go/no-go before any run depends on it. Seasonal maintenance grows
  (a function address, not just a struct offset).

### Recommendation

**Do the separation and Path A unconditionally; spike Path B behind a
gate.** The separation is pure win and unblocks everything. Path A
banks the cheap reliability (draw-order + reproject) with no risk. Path
B is the real answer to "frame-perfect," but it is a capability decision
the operator must make with eyes open — so it is a *spike with a
go/no-go*, not a commitment. If B proves out, the Actuator swaps its
mechanism behind the seam and A's clicks become the fallback, exactly as
kolbot keeps `Misc.click` behind `Packet.click`.

## Prior art to pull, not re-derive

- `kolbot/.../Packet.js` — `click` (0x16 by GID), `itemToCursor`
  (PickupBufferItem loop), the read-back-to-confirm pattern.
- `kolbot/.../Pickit.js` — `pickItems` builds a list, **sorts by
  distance**, picks nearest-first, drops from the list on confirm;
  `pickItem` retries 3× with move-if-far, TK for ranged. Our sort is
  world-distance too, but we click from a standoff rather than moving to
  `minDist: 4`.
- **koolo** (Go, out-of-process) — the precedent that command-by-GID
  works *without injection*. Study how it actuates before designing the
  spike; do not assume its internals.
- Our own `units.hovered_item_id` (player+0xE8) and T58/T60/T61/T63/T66
  — the aim investigation is *done*; T63 settled that clicks resolve on
  cursor position, so writing the hover slot would not help a click. It
  would only matter to a command path, where it is irrelevant anyway.

## Open questions for the operator

1. **The capability decision** — is an out-of-process **memory-write /
   remote-call** actuation on the table at all? It is the only path to
   the frame-perfect pickup, and it reopens the actuation ADR. (Spike
   first, commit later — but the spike itself needs a yes.)
2. Scope: is this a **replacement** for the pickup-reliability plan's P3
   (the aim fix), or does that plan's P3 become Path A inside this one?
   (Recommend: this plan supersedes that plan's P3/P4; P1/P2/P5 of it
   stand — instrumentation, the calibration, the exception registry.)
3. Appetite for the spike's risk: a wrong remote call can crash the
   client mid-run. Acceptable as an isolated, supervised drill?

## Out of scope

- Whitelist/pickit accuracy (a detection problem — its own track).
- Muling, TK pickup (kolbot has both; not our necro's concern yet).
- Speed of the descent generally (M6's separate speed pass).
