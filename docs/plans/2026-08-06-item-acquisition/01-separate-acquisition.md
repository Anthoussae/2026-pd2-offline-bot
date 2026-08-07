# P1 — Separate acquisition from detection

Part of [plan.md](plan.md). Size: `sm`. **No game.** No dependencies.
Review gate: end of phase — the seam is clean.

## The operator's structural charge

> *"separate out the 'item detection' problem from the 'item pickup'
> problem too, so that there isn't conceptual bleed."*

Today `_PickupMixin.collect` fuses three concerns: should we want this
(pickit), can we reach it (walk budget), can we lift it (click schedule
+ belt/inventory diagnosis). Lift failures are mis-attributed to the
others — a non-potion that will not come up is reported as "inventory
full (inferred from persistence)" when T76 says it is almost always a
click miss.

## Scope

Introduce an **Actuator** with a narrow, mechanism-free contract:

```python
@dataclass(frozen=True)
class AcquireOutcome:
    picked: bool
    reason: str          # "picked" | "clicks did not land" | "unreachable" | ...
    clicks: int
    latency_s: float
    attributed_to: int | None = None   # the "clicked A got B" case

class Actuator(Protocol):
    def acquire(self, snap, ctx, target_gid: int, position, budget) -> AcquireOutcome: ...
```

- **Move the existing click machinery** — reach check, walk-to,
  `PICKUP_AIM_POINTS` schedule, the retry pacing, the belt-full vs
  click-missed diagnosis — behind this interface as `ClickActuator`,
  **unchanged in behaviour**. This phase is a refactor, not a fix; P2
  changes behaviour.
- **`_PickupMixin.collect` becomes a thin caller**: it decides *what* to
  go for (still its job — pickit, sightings, ordering) and delegates
  *getting it* to the Actuator. Detection does not import acquisition.
- The pickit decision, `wanted_items`, `log_wanted_drops`,
  `note_wanted_sightings` stay on the detection side untouched.

## The proof the seam is clean

A drill (`drills/t78_acquire.py`, no pickit involved) that:

1. asks the operator to drop **junk** — anything, whitelisted or not;
2. reads the GIDs off the floor (detection surface);
3. calls `acquire(gid, ...)` on each and reports picked/latency/reason.

If acquisition can lift an item the pickit would never keep, the seam is
real: acquisition knows only unit ids and positions, nothing about
wants. Written and unit-tested this phase; **launched later** with the
others (needs game time). This is also the harness P4's spike reuses —
one drill, two actuator implementations behind it.

## Files

- **New** `pd2bot/acquire.py` — the `Actuator` protocol, `AcquireOutcome`,
  `ClickActuator` (the moved machinery).
- `pd2bot/behavior/steps.py` — `_PickupMixin.collect` delegates.
- `pd2bot/behavior/execute.py` — the click path referenced by
  `ClickActuator`.
- **New** `drills/t78_acquire.py` + `tests/test_t78_acquire.py`.
- `docs/architecture/behavior.md` — the detection/acquisition split.

## Implementation notes

- This is the highest-risk-of-regression phase precisely because it
  moves working, hard-won code (T56's belt logic, the R173 cleanse-loop
  guard). Move it **verbatim** behind the seam; do not "improve while
  moving" — that is the shape that cost P3 three live runs. Every
  existing pickup test must stay green with zero edits to its
  assertions; if an assertion has to change, the refactor changed
  behaviour and that is a bug in the refactor.
- Keep `item.dropped` / `item.collected` / `item.abandoned` /
  `nav.failed` emitting exactly as now — the instrumentation is
  detection's and acquisition's shared record, not one side's.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

The whole existing pickup suite green **with unchanged assertions** is
the phase's real test.

## Review gate

Confirm before P2: the Actuator interface is mechanism-free (nothing in
its signature assumes clicking), and the junk drill demonstrates
acquisition with no pickit on the path.

## Agent reminders

Do not commit unless asked. Do not change behaviour — this is a move.
Do not launch the drill without the operator. Stop and report if the
seam cannot be drawn without changing a call site's behaviour.

## Definition of done

`acquire.py` exists; `collect` delegates; every existing test green
unchanged; the junk drill written and unit-tested; behavior.md updated.

## Implementation result (2026-08-06, no game)

Done to the live boundary. The seam drawn is the **mechanism** seam —
`pd2bot/acquire.py` holds `AcquireOutcome`, the `Actuator` protocol, and
`ClickActuator`; `RunServices.actuator` carries it; `collect`'s single
inline `PickUpItem` execute became `self.services.actuator.actuate(...)`,
byte-for-byte the same conduct. **All 1035 pre-existing tests stayed
green with zero assertion changes** — the behaviour-preserving proof the
gate asked for — and `test_acquire.py` proves a substitute actuator
receives the same call (so P4 needs no `collect` change).

Deliberately NOT done: physically relocating `collect` and its ~250
lines of hard-won belt/inventory diagnosis into a separate class. That
move is validate-by-unit-test-only and high-regression; the mechanism
seam already gives P4 its insertion point and gives the operator the
detection↔acquisition split named in code and docs. The
detection/acquisition *class* split remains available as a later tidy if
it earns its risk — the conceptual bleed the operator named (lift
failure mis-read as inventory-full) is dissolved by P4's command path
anyway, since a GID command cannot miss.

`drills/t78_acquire.py` written and unit-tested (`test_t78_acquire.py`),
**not launched** — it acquires junk with no pickit on the path and
reports per-item lift latency through the same `Actuator` seam, and is
the harness P4's spike reuses. Awaiting game time with the others.
