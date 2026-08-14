"""P3: the consumers actually press what the keyfile says (R247)."""

import pytest

from pd2bot.input import keys
from pd2bot.input.keyfile import KeyfileError
from pd2bot.input.skills import belt_drink, belt_give_merc


class PressLog:
    def __init__(self):
        self.pressed = []
        self.chorded = []

    def press_key(self, vk):
        self.pressed.append(vk)

    def press_key_with_shift(self, vk):
        self.chorded.append(vk)


def rebound():
    return keys.KeyBindings(
        skill_keys=(0x70, 0x71, None, None, None, None, None, None),
        belt=(0x37, 0x38, 0x39, 0x30),  # 7 8 9 0
        inventory=0x59,  # Y
        show_items=0x4C,  # L
        source="keyfile:test",
    )


def test_belt_presses_follow_the_bindings():
    gated = PressLog()
    belt_drink(gated, 2, belt=rebound().belt)
    belt_give_merc(gated, 0, belt=rebound().belt)
    assert gated.pressed == [0x39]
    assert gated.chorded == [0x37]


def test_belt_defaults_are_the_historical_keys():
    gated = PressLog()
    belt_drink(gated, 0)
    assert gated.pressed == [keys.VK_1]


def test_hotkey_drift_refuses_with_all_three_facts():
    """The skill name, the configured key, and what the client holds —
    the message must carry enough to fix EITHER side of the drift."""
    hotkeys = {84: keys.VK_F5}  # a skill configured on F5...
    b = rebound()  # ...but the client only binds F1/F2 to skill slots
    with pytest.raises(KeyfileError) as failure:
        keys.verify_skill_hotkeys(hotkeys, b, skill_names={84: "bone_armor"})
    message = str(failure.value)
    assert "bone_armor" in message
    assert "F5" in message
    assert "slot 1=F1" in message and "keyfile:test" in message


def test_default_bindings_are_never_verified():
    # Nothing to verify against: the defaults ARE the assumption.
    keys.verify_skill_hotkeys({84: keys.VK_F5}, keys.default_bindings())


def test_matching_config_passes_verification():
    keys.verify_skill_hotkeys(
        {84: 0x70, 85: 0x71}, rebound(), skill_names={84: "a", 85: "b"}
    )


def test_the_executor_carries_bindings_with_a_default():
    from pd2bot.behavior.execute import GameActionExecutor

    field = GameActionExecutor.__dataclass_fields__["bindings"]
    assert field.default_factory is keys.default_bindings
