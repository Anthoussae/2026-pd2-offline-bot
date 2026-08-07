"""Item acquisition — the actuation of a pickup, separated from detection.

The operator's charge (2026-08-06): *"separate out the 'item detection'
problem from the 'item pickup' problem… so that there isn't conceptual
bleed."* This module owns the **pickup** side. Detection — which items
exist, which the pickit wants, where they are — stays in `steps.py`
(`wanted_items`, the sightings memo) and does not depend on this.

Within acquisition there is one further seam, and it is the whole reason
this module exists as its own thing now: the **mechanism** by which a
known item is caused to be picked up. Today that mechanism is a
synthetic screen click (`ClickActuator`). kolbot's fast path — read from
the clone in this repo — is instead a `PickupItem` command addressed by
the item's unit id, with no screen aim at all, and that is the
frame-perfect pickup the project is reaching for (the item-acquisition
plan, P4). The two are interchangeable behind `Actuator.actuate`: the
budgets, the walk, the retry pacing and the belt/inventory diagnosis in
`_PickupMixin.collect` are all mechanism-independent and do not move.

`ClickActuator` is deliberately stateless — a click needs only the
executor and the item. A command actuator (P4, on the spike branch)
will carry the write path it needs, injected at construction, and
implement the same one method.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pd2bot.behavior.actions import PickUpItem
from pd2bot.behavior.engine import EngineContext
from pd2bot.units import GroundItem


@dataclass(frozen=True)
class AcquireOutcome:
    """The result of one acquisition attempt.

    Richer than the bool `collect` returns today, so a command actuator
    can report *what happened* rather than only *did we send something*.
    `collect` keeps its bool contract for now (P1 is a seam, not a
    behaviour change); this type is what the interface promises and what
    later phases read.
    """

    sent: bool
    reason: str = ""


@runtime_checkable
class Actuator(Protocol):
    """Cause one pickup attempt on a known item. The swappable mechanism.

    The contract is deliberately narrow: given the executor context and
    the item (identity + position + attempt index), make the game try to
    pick it up, once. Everything else — deciding it is worth picking,
    walking into reach, pacing retries, diagnosing failure — belongs to
    the caller and is identical whichever mechanism is in play.
    """

    def actuate(
        self, ctx: EngineContext, item: GroundItem, attempt: int
    ) -> AcquireOutcome: ...


class ClickActuator:
    """Pickup by synthetic screen click — the current, aim-based mechanism.

    Stateless. Emits a `PickUpItem`, whose `attempt` indexes the
    measured sprite-aim schedule (`actions.PICKUP_AIM_POINTS`); the
    executor turns it into a projected click. Its accuracy ceiling is the
    game's screen hit-test, which T76 measured — a dense pile defeats
    every offset. It stays as the permanent fallback behind any command
    mechanism, exactly as kolbot keeps `Misc.click` behind `Packet.click`.

    Behaviour is byte-for-byte the line it replaced in `collect`, so the
    seam changes structure, not conduct.
    """

    def actuate(
        self, ctx: EngineContext, item: GroundItem, attempt: int
    ) -> AcquireOutcome:
        ctx.executor.execute(
            PickUpItem(
                item.unit_id, item.position, attempt=attempt, kind=item.kind
            )
        )
        return AcquireOutcome(sent=True, reason="click")
