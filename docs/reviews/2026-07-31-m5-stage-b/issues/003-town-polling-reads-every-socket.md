# 003 — Town waits re-read every inventory socket, ten times a second

Severity: **P2**

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
