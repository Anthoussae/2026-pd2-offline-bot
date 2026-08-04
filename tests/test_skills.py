"""Verified skill switching: no cast on an unverified skill, ever.

The fakes model the one thing that matters — the gap between pressing a
hotkey and the game's right-skill slot actually changing. A press is a
request; only the read-back is truth.
"""

import pytest

from pd2bot import offsets
from pd2bot.input import VK_1, VK_4, VK_F5
from pd2bot.player import ActiveSkills, Player
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


def test_the_failure_carries_the_state_that_would_explain_it(monkeypatch):
    """The switch failure has now outlived two theories and three runs.

    T47 proved the bindings and the presses are fine; T48 proved a cast
    does not eat a following press. A blocking panel and a lost foreground
    both raise `InputRefused` instead, so they cannot be it either. What is
    left is only visible from inside the failure, so it carries its own
    evidence — the next occurrence is an answer instead of another
    supervised run.
    """
    clock = FakeClock()
    script_reads(monkeypatch, [right(offsets.SKILL_BONE_ARMOR)])
    monkeypatch.setattr(
        "pd2bot.player.read_player",
        lambda session: Player(
            name="N", level=91, act=1, position=(1, 1), mode=10,
            hp=900, max_hp=1000, mana=300, max_mana=400,
            stamina=0, max_stamina=0, experience=0, gold=0, gold_stash=0,
            strength=0, dexterity=0, vitality=0, energy=0,
        ),
    )
    with pytest.raises(SkillSwitchFailed) as failure:
        ensure_right_skill(
            None, FakeGated(), offsets.SKILL_DESECRATE, clock=clock, sleep=clock.sleep
        )
    message = str(failure.value)
    assert "player mode 10" in message  # the cast animation, if it is that
    assert "waited" in message
    assert "ui " in message or "ui read raised" in message


def test_a_broken_diagnosis_never_replaces_the_failure(monkeypatch):
    # Explaining an exception must not raise one: a torn read while the
    # world is already misbehaving would swap the diagnosis for a traceback
    # about the diagnosis.
    clock = FakeClock()
    script_reads(monkeypatch, [right(offsets.SKILL_BONE_ARMOR)])

    def explode(session):
        raise RuntimeError("memory read failed mid-diagnosis")

    monkeypatch.setattr("pd2bot.player.read_player", explode)
    with pytest.raises(SkillSwitchFailed, match="no cast will be sent"):
        ensure_right_skill(
            None, FakeGated(), offsets.SKILL_DESECRATE, clock=clock, sleep=clock.sleep
        )


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
