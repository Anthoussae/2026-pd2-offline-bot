# 003 — Town waits re-read every inventory socket, ten times a second

Severity: **P2** — **FIXED** 2026-08-01 (not yet re-measured live)

`pd2bot/town.py` (`_await`, `poll_s`, the injected `carried`),
`pd2bot/items.py` (`read_carried_items(with_sockets=True)` default).

## What is wrong

Two changes made in the same session compound:

1. `read_carried_items` gained `with_sockets`, defaulting to **True**, and
   it performs one extra stat read per main-inventory item (up to 40).
2. `TownLayer`'s `carried` parameter defaults to bare `read_carried_items`,
   so the town layer takes the sockets path everywhere.
3. `poll_s` was halved to 0.1 this session, doubling the poll rate.

The town layer calls `_carried` inside tight verification loops:

```python
self._await(lambda b=before: len(self._carried(self.session).belt) > b,
            self.config.verify_timeout_s)
```

So each belt transfer polls at 10 Hz for up to 3 s, and every poll walks
the whole inventory chain **and** does up to 40 stat reads — to answer a
question about the belt, which never needs sockets at all.

Order of magnitude: ~1200 stat reads per potion moved.

## Why it matters

The user's own report this session was that the bot "dithers for a long
period" on arriving at an NPC or the stash — and the response was to halve
`poll_s`, which doubles this cost rather than reducing it. If the polling
is I/O-bound on memory reads, that change made the symptom worse while
appearing to address it.

The wiring already knows the tick-rate consumer needs the cheap path — it
passes `with_sockets=False` to the reflex ladder with a comment explaining
why. The town layer needs the sockets exactly once (the cleanse whitelist)
and pays for them in every unrelated wait.

## Suggested fix

Give `TownLayer` the cheap reader for polling and the sockets reader only
where the cleanse needs it. Either an explicit second callable, or make
the cleanse ask for sockets at the point of use. Then re-measure the
dithering before touching `poll_s` again.

## Validation

A counter or timing assertion around a belt-fill verification showing the
number of stat reads per poll drops to zero, plus a live re-run of T27 to
see whether the preamble is visibly brisker.

## Resolution (2026-08-01)

`TownLayer` takes two readers instead of one, split along the line the
finding drew: **deciding may be expensive, verifying may not.**

- `carried` is the cheap read (`with_sockets=False`) and is what every
  `_await` loop in the layer polls. That is all of them but one.
- `carried_with_sockets` is used in exactly two places, both of which
  decide something ABOUT an item rather than whether it still exists: the
  cleanse's junk listing (its whitelist is socket-conditioned, R132) and
  `deposit_to_stash`'s initial `keep` filtering. The `_gone` verification
  inside that same deposit stays on the cheap reader.

`read_carried_items` keeps defaulting to sockets-on, deliberately — a
caller who forgets them gets `sockets=None`, which a permissive whitelist
reads as "keep", and that failure is silent. What changed is that the
town layer no longer takes that default for its loops. The wiring names
both readers explicitly rather than relying on either default, since a
silently-defaulted collaborator is the class of bug that module exists to
prevent. A caller who injects only one reader gets it for both, so every
existing test double behaves exactly as before.

`poll_s` is left at 0.1 on purpose. The finding's advice was to re-measure
the dithering before touching it again, and that measurement needs a live
T27 — changing it now would be the same guess in the other direction.

Tests: 3 new — the deposit's expensive read happens exactly once while its
verification polls the cheap one; the cleanse still decides from the
sockets reader; and one injected reader serves both.

**Still owed: the live re-run of T27**, to see whether the preamble is
visibly brisker. Until then this is a measured cost reduction with an
unmeasured effect on the symptom the user actually reported.
