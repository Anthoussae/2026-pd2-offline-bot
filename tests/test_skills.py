"""Verified skill switching: no cast on an unverified skill, ever.

The fakes model the one thing that matters — the gap between pressing a
hotkey and the game's right-skill slot actually changing. A press is a
request; only the read-back is truth.
"""

import pytest

from pd2bot import offsets
from pd2bot.input import VK_1, VK_4, VK_F5
from pd2bot.player import ActiveSkills
from pd2bot.skills import SkillSwitchFailed, belt_drink, ensure_right_skill


class FakeGated:
    """Records presses; the test script decides what the game 'heard'."""

    def __init__(self) -> None:
        self.pressed: list[int] = []

    def press_key(self, vk: int) -> None:
        self.pressed.append(vk)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def script_reads(monkeypatch, responses):
    """read_active_skills returns each response in turn, then repeats the last."""
    state = {"i": 0}

    def fake_read(session):
        index = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[index]

    monkeypatch.setattr("pd2bot.skills.read_active_skills", fake_read)


def right(skill_id):
    return ActiveSkills(left_id=offsets.SKILL_POISON_STRIKE, right_id=skill_id)


def test_already_active_sends_nothing(monkeypatch):
    script_reads(monkeypatch, [right(offsets.SKILL_DESECRATE)])
    gated = FakeGated()
    ensure_right_skill(None, gated, offsets.SKILL_DESECRATE)
    assert gated.pressed == []


def test_switch_verifies_after_one_press(monkeypatch):
    clock = FakeClock()
    # First read: wrong skill -> press; then the game catches up.
    script_reads(
        monkeypatch,
        [right(offsets.SKILL_BONE_ARMOR), right(offsets.SKILL_DESECRATE)],
    )
    gated = FakeGated()
    ensure_right_skill(
        None, gated, offsets.SKILL_DESECRATE, clock=clock, sleep=clock.sleep
    )
    assert gated.pressed == [VK_F5]


def test_switch_represses_when_the_first_press_is_swallowed(monkeypatch):
    clock = FakeClock()
    # Wrong skill for the whole first verify window; right after re-press.
    swallowed = [right(offsets.SKILL_BONE_ARMOR)] * 20
    script_reads(
        monkeypatch, swallowed + [right(offsets.SKILL_DESECRATE)]
    )
    gated = FakeGated()
    ensure_right_skill(
        None, gated, offsets.SKILL_DESECRATE, clock=clock, sleep=clock.sleep
    )
    assert gated.pressed == [VK_F5, VK_F5]


def test_switch_that_never_takes_raises_and_names_the_state(monkeypatch):
    clock = FakeClock()
    script_reads(monkeypatch, [right(offsets.SKILL_BONE_ARMOR)])
    gated = FakeGated()
    with pytest.raises(SkillSwitchFailed, match="no cast will be sent"):
        ensure_right_skill(
            None, gated, offsets.SKILL_DESECRATE, clock=clock, sleep=clock.sleep
        )
    assert gated.pressed == [VK_F5, VK_F5, VK_F5]  # bounded, then gave up


def test_unreadable_skills_never_count_as_verified(monkeypatch):
    """None (loading / torn read) must not satisfy the verify — an unknown
    right skill is exactly the state we refuse to cast in."""
    clock = FakeClock()
    script_reads(monkeypatch, [None])
    gated = FakeGated()
    with pytest.raises(SkillSwitchFailed):
        ensure_right_skill(
            None, gated, offsets.SKILL_DESECRATE, clock=clock, sleep=clock.sleep
        )


def test_skill_without_a_hotkey_fails_before_pressing_anything(monkeypatch):
    script_reads(monkeypatch, [right(offsets.SKILL_BONE_ARMOR)])
    gated = FakeGated()
    with pytest.raises(SkillSwitchFailed, match="no hotkey"):
        ensure_right_skill(None, gated, 9999)
    assert gated.pressed == []


def test_caller_supplied_hotkey_table_wins(monkeypatch):
    clock = FakeClock()
    script_reads(monkeypatch, [right(0), right(42)])
    gated = FakeGated()
    ensure_right_skill(
        None, gated, 42, hotkeys={42: 0x99}, clock=clock, sleep=clock.sleep
    )
    assert gated.pressed == [0x99]


def test_belt_drink_maps_columns_to_keys():
    gated = FakeGated()
    belt_drink(gated, 0)
    belt_drink(gated, 3)
    assert gated.pressed == [VK_1, VK_4]


def test_belt_drink_rejects_bad_columns():
    with pytest.raises(ValueError):
        belt_drink(FakeGated(), 4)
