"""The acquisition seam: the pickup mechanism is swappable behind `collect`.

The item-acquisition plan's P1 win, checked two ways: the default
`ClickActuator` still emits exactly the `PickUpItem` the old inline code
did, and a *substitute* actuator receives the same calls — which is the
whole point, because P4 drops a command-by-GID actuator in here without
touching `collect`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot.acquire import AcquireOutcome, Actuator, ClickActuator  # noqa: E402
from pd2bot.behavior.actions import PickUpItem  # noqa: E402
from pd2bot.units import GroundItem  # noqa: E402


class _RecordingCtx:
    """Just enough EngineContext to catch what the actuator executes."""

    def __init__(self):
        self.executed = []

    @property
    def executor(self):
        return self

    def execute(self, action):
        self.executed.append(action)


def item(uid=1, kind=606, pos=(100, 100)):
    return GroundItem(unit_id=uid, kind=kind, position=pos, quality=2)


def test_click_actuator_emits_the_pickupitem_the_inline_code_did():
    ctx = _RecordingCtx()
    out = ClickActuator().actuate(ctx, item(uid=7, kind=606, pos=(120, 130)), 3)
    assert len(ctx.executed) == 1
    action = ctx.executed[0]
    assert isinstance(action, PickUpItem)
    assert action.unit_id == 7
    assert action.position == (120, 130)
    assert action.attempt == 3      # indexes the sprite-aim schedule
    assert action.kind == 606
    assert out == AcquireOutcome(sent=True, reason="click")


def test_click_actuator_satisfies_the_protocol():
    # runtime_checkable: the type system and P4's substitute agree on shape.
    assert isinstance(ClickActuator(), Actuator)


def test_collect_routes_through_the_services_actuator():
    """A substitute actuator sees the collect call — so P4's command
    mechanism needs no change to `collect`, only a different `actuator`."""
    from tests.test_behavior_steps import (
        Clock,
        context,
        make_step,
        services,
        snap,
    )

    class SpyActuator:
        def __init__(self):
            self.calls = []

        def actuate(self, ctx, itm, attempt):
            self.calls.append((itm.unit_id, attempt))
            return AcquireOutcome(sent=True, reason="spy")

    clock = Clock()
    spy = SpyActuator()
    svc = services(clock, actuator=spy)
    step = make_step("pickup", svc)
    ctx = context()
    target = item(uid=42, kind=606, pos=(1000, 1000))  # HOME in that suite
    # In reach, no prior attempts -> collect should actuate once.
    step.collect(snap(pos=(1000, 1000), items=[target]), ctx, target)

    assert spy.calls == [(42, 0)], "collect did not route through the actuator"
    # And nothing was executed directly on the ctx — the mechanism owns it.


def test_default_services_actuator_is_a_click_actuator():
    from tests.test_behavior_steps import Clock, services

    svc = services(Clock())
    assert isinstance(svc.actuator, ClickActuator)
