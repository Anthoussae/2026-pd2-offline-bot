# P4 — The command-by-GID spike (GATED, dangerous)

Part of [plan.md](plan.md). Size: `sm`. **On the isolated branch, and
supervised.** Depends on P1's seam and drill. **Review gate: a hard
go/no-go before anything trusts it.**

This is the phase that reaches for frame-perfect. It also introduces the
first capability that can **crash the client**, so it is deliberately
isolated, off by default, and proven in one supervised drill before any
run depends on it. The operator has licensed it (2026-08-06) *and* asked
to be able to rewind it wholesale — hence the branch.

## The target

kolbot's fast pickup is `PickupItem` (0x16) with `(unittype.Item=4, gid,
toCursor)` and no screen aim. Reproduce that **out-of-process**. Two
candidate mechanisms; the spike's first job is to learn which is
reachable, drawing on **koolo** (Go, out-of-process — our ADR's
precedent that this works without injection) before committing:

1. **Remote function call** — find D2's item-pickup handler (BH is the
   source, as for every offset), then `CreateRemoteThread` / thread-
   hijack to call it with our args. Highest power, highest risk (wrong
   convention → crash).
2. **Packet into the client's dispatch** — write the 0x16 bytes where
   the client's own loop consumes them. In offline SP there is no
   socket; whether the local packet path is reachable by an
   out-of-process write is itself part of the spike.

## Guardrails, non-negotiable

- **A new, isolated write path.** `memory.py` gains a guarded `write`
  (and, if used, a remote-call helper) that is OFF by default and used
  by nothing but the spike drill until this gate passes. The
  SendInput-only contract for the rest of the bot is untouched.
- **The safety stack is unchanged.** The death latch, `can_act`, the
  foreground guard — none of them move. A GID command still only fires
  when the same conditions a click requires are true.
- **Supervised only.** The spike runs as a drill with the operator at
  the machine, hands near ESC, on the isolated branch. Never in an
  unattended cycle, this phase.
- **A crash is a stop-and-report**, with whatever state was captured —
  not a retry. The whole point of the drill is to find the safe form
  *before* trusting it.

## The spike drill

`drills/t80_gid_pickup.py`, reusing P1's junk-item harness:

1. operator drops junk and stands clear;
2. read a GID off the floor;
3. issue the GID pickup command (mechanism under test);
4. confirm by the tight poll from P2 — did *that* unit leave the ground;
5. report: picked / no-effect / refused, latency, and — critically —
   **client still alive** (a follow-up perception read proves the
   process survived).

Escalate carefully: first prove the command is even *received* (does the
item twitch, does anything change) before trusting it to pick cleanly.

## Files (all on the isolated branch)

- `pd2bot/memory.py` — the guarded write / remote-call helper.
- `pd2bot/offsets.py` — the handler address, BH-cited (P4 only).
- `pd2bot/acquire.py` — a `CommandActuator` implementing the same
  interface as `ClickActuator`.
- **New** `drills/t80_gid_pickup.py` + tests for its pure logic.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

Plus the supervised spike drill, output captured as `t80-gid-pickup.md`.

## Review gate — the go/no-go

Present to the operator, with drill evidence:

- Does an out-of-process GID pickup work, and by which mechanism?
- Is it stable across item classes and repeated calls (no crash, no
  drift)?
- **GO** → P5 adopts `CommandActuator` as primary, `ClickActuator` the
  fallback, and the write path graduates from spike-only behind its
  guard.
- **NO-GO** → the branch is abandoned (the rewind contract), Track 1
  (P2/P3) stands as the answer, and the ADR records why command-by-GID
  was not adopted. Either outcome is a real, documented result.

## Agent reminders

Do not commit unless asked. Do not run the spike unattended or off the
isolated branch. Do not wire the write path into any run before the
gate. A crash stops everything and reports. Do not overclaim — "the item
moved once" is not "it works".

## Definition of done

The mechanism is proven working (with class/repeat evidence) or proven
unreachable, in a supervised drill; the go/no-go is put to the operator;
the write path stays isolated until GO.
