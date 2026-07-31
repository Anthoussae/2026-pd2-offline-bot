"""The executor: the one module that turns decisions into real sends.

The rules it must never break are the ones the game punishes silently — a
cast on a skill the game did not actually switch to, an attack that walks
the character into the pack instead of striking, a pickup that attacks the
ground. Each gets a test.
"""

import pytest

from pd2bot import offsets
from pd2bot.behavior.actions import (
    AttackUnit,
    CastAtPoint,
    CastSelf,
    DrinkPotion,
    MoveTo,
    PickUpItem,
)
from pd2bot.behavior.execute import (
    ExecutionError,
    GameActionExecutor,
    RecordingExecutor,
)
from pd2bot.input import VK_1, VK_F1, VK_F5
from pd2bot.player import ActiveSkills, Player

HOME = (1000, 1000)


class FakeGated:
    """Records every send, with its modifiers, exactly as issued."""

    def __init__(self):
        self.pressed = []
        self.world_clicks = []

    def press_key(self, vk):
        self.pressed.append(vk)

    def click_world(self, wx, wy, button="left", *, stand_still=False):
        self.world_clicks.append(((wx, wy), button, stand_still))
        return (0, 0)


def player_at(pos=HOME):
    return Player(
        name="N", level=91, act=1, position=pos, mode=1,
        hp=1000, max_hp=1000, mana=200, max_mana=400,
        stamina=0, max_stamina=0, experience=0, gold=0, gold_stash=0,
        strength=0, dexterity=0, vitality=0, energy=0,
    )


def make(monkeypatch, *, active_skill=None, player=None, walk=None):
    """An executor over fakes. `active_skill` is what the game reports."""
    state = {"right": active_skill}

    def fake_read_skills(session):
        return ActiveSkills(left_id=offsets.SKILL_POISON_STRIKE,
                            right_id=state["right"])

    def fake_press(session, gated, skill_id, *, hotkeys=None, **kw):
        # Stand in for skills.ensure_right_skill's press-and-verify, keeping
        # the part under test here: that it is CALLED before any click.
        gated.press_key(hotkeys[skill_id])
        state["right"] = skill_id

    monkeypatch.setattr("pd2bot.behavior.execute.ensure_right_skill", fake_press)
    monkeypatch.setattr(
        "pd2bot.behavior.execute.read_player",
        lambda session: player if player is not None else player_at(),
    )
    gated = FakeGated()
    walked = []
    executor = GameActionExecutor(
        session=None,
        gated=gated,
        walk_to=walk if walk is not None else walked.append,
        hotkeys={offsets.SKILL_BONE_ARMOR: VK_F1, offsets.SKILL_DESECRATE: VK_F5},
        clock=lambda: 0.0,
    )
    return executor, gated, walked, state


def test_drink_presses_the_column_key(monkeypatch):
    executor, gated, _, _ = make(monkeypatch)
    executor.execute(DrinkPotion(0, "mana"))
    assert gated.pressed == [VK_1]
    assert "key 1" in executor.trace[0].detail


def test_self_cast_verifies_the_switch_before_clicking(monkeypatch):
    executor, gated, _, state = make(monkeypatch)
    executor.execute(CastSelf(offsets.SKILL_BONE_ARMOR))
    # The hotkey press must come first, and the click must be a right-click
    # at our own feet (off any bystander).
    assert gated.pressed == [VK_F1]
    assert state["right"] == offsets.SKILL_BONE_ARMOR
    assert gated.world_clicks == [(HOME, "right", False)]


def test_cast_at_point_verifies_then_clicks_the_target(monkeypatch):
    executor, gated, _, _ = make(monkeypatch)
    executor.execute(CastAtPoint(offsets.SKILL_DESECRATE, (1010, 1002)))
    assert gated.pressed == [VK_F5]
    assert gated.world_clicks == [((1010, 1002), "right", False)]


def test_an_unverifiable_switch_sends_no_click(monkeypatch):
    # The rule the whole module exists for: SkillSwitchFailed propagates and
    # nothing is clicked on a skill the game may not have selected.
    from pd2bot.skills import SkillSwitchFailed

    def refuse(session, gated, skill_id, *, hotkeys=None, **kw):
        raise SkillSwitchFailed("never read back")

    executor, gated, _, _ = make(monkeypatch)
    monkeypatch.setattr("pd2bot.behavior.execute.ensure_right_skill", refuse)
    with pytest.raises(SkillSwitchFailed):
        executor.execute(CastAtPoint(offsets.SKILL_DESECRATE, (1010, 1002)))
    assert gated.world_clicks == []
    assert executor.trace == []


def test_self_cast_refuses_when_the_player_is_unreadable(monkeypatch):
    executor, gated, _, _ = make(monkeypatch)
    monkeypatch.setattr("pd2bot.behavior.execute.read_player", lambda s: None)
    with pytest.raises(ExecutionError):
        executor.execute(CastSelf(offsets.SKILL_BONE_ARMOR))
    assert gated.world_clicks == []


def test_attack_holds_shift(monkeypatch):
    # Without stand-still, a left-click on a monster out of reach WALKS into
    # the pack — the opposite of the skirmish pattern.
    executor, gated, _, _ = make(monkeypatch)
    executor.execute(AttackUnit(7, (1002, 1000)))
    assert gated.world_clicks == [((1002, 1000), "left", True)]
    assert gated.pressed == []  # offense never switches skills (R47.1)


def test_pickup_does_not_hold_shift(monkeypatch):
    # Shift would attack the ground where the item lies instead of taking it.
    executor, gated, _, _ = make(monkeypatch)
    executor.execute(PickUpItem(7, (1002, 1000)))
    assert gated.world_clicks == [((1002, 1000), "left", False)]


def test_move_goes_through_walk_to(monkeypatch):
    executor, gated, walked, _ = make(monkeypatch)
    executor.execute(MoveTo((1020, 1010)))
    assert walked == [(1020, 1010)]
    assert gated.world_clicks == []  # the navigator owns its own clicks


def test_unknown_action_is_refused(monkeypatch):
    executor, _, _, _ = make(monkeypatch)
    with pytest.raises(ExecutionError):
        executor.execute(object())


def test_trace_records_every_action_in_order(monkeypatch):
    executor, _, _, _ = make(monkeypatch)
    executor.execute(DrinkPotion(0, "mana"))
    executor.execute(AttackUnit(7, (1002, 1000)))
    assert [type(e.action).__name__ for e in executor.trace] == [
        "DrinkPotion", "AttackUnit"
    ]


def test_recording_executor_lets_the_world_react():
    seen = []
    executor = RecordingExecutor(on_execute=seen.append, clock=lambda: 0.0)
    executor.execute(DrinkPotion(1, "rejuv"))
    assert seen == [DrinkPotion(1, "rejuv")]
    assert executor.actions == [DrinkPotion(1, "rejuv")]
