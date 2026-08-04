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
    GiveMercPotion,
    MoveTo,
    PickUpItem,
)
from pd2bot.behavior.execute import (
    CastInFlight,
    ExecutionError,
    GameActionExecutor,
    RecordingExecutor,
)
from pd2bot.input import VK_1, VK_3, VK_F1, VK_F5
from pd2bot.player import ActiveSkills, Player

HOME = (1000, 1000)


class FakeGated:
    """Records every send, with its modifiers, exactly as issued."""

    BASE = (500, 400)  # where project_world puts every target

    def __init__(self):
        self.pressed = []
        self.world_clicks = []
        self.hovers = []
        self.screen_clicks = []

    def press_key(self, vk):
        self.pressed.append(vk)

    def press_key_with_shift(self, vk):
        self.pressed.append(("shift", vk))

    def click_world(self, wx, wy, button="left", *, stand_still=False):
        self.world_clicks.append(((wx, wy), button, stand_still))
        return (0, 0)

    def project_world(self, wx, wy):
        return self.BASE

    def hover_screen(self, sx, sy):
        self.hovers.append((sx, sy))

    def click_screen(self, sx, sy, button="left", *, stand_still=False):
        self.screen_clicks.append(((sx, sy), button, stand_still))


def player_at(pos=HOME, mode=1):
    return Player(
        name="N", level=91, act=1, position=pos, mode=mode,
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
        # The cast settle is real time in the game and must be no time
        # here — every cast test would otherwise pay 0.4 s.
        sleep=lambda seconds: None,
    )
    return executor, gated, walked, state


# -- review 002: the cast settle waits on the EFFECT, and only clicks wait ------


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def casting(monkeypatch):
    """An executor over a game whose player mode the test drives.

    `reads` counts how often the player was read, which is the other half
    of the fix: the mode is asked for only after one of our own casts, not
    once per action forever (the cost review 003 is about).
    """
    world = {"mode": 1, "reads": 0}

    def fake_press(session, gated, skill_id, *, hotkeys=None, **kw):
        gated.press_key(hotkeys[skill_id])

    def fake_read(session):
        world["reads"] += 1
        return player_at(mode=world["mode"])

    monkeypatch.setattr("pd2bot.behavior.execute.ensure_right_skill", fake_press)
    monkeypatch.setattr("pd2bot.behavior.execute.read_player", fake_read)
    clock = Clock()
    gated = FakeGated()
    executor = GameActionExecutor(
        session=None,
        gated=gated,
        walk_to=lambda target: None,
        hotkeys={offsets.SKILL_BONE_ARMOR: VK_F1, offsets.SKILL_DESECRATE: VK_F5},
        clock=clock,
    )
    return executor, gated, clock, world


def test_a_click_waits_out_the_cast_animation(monkeypatch):
    """T48: a cast holds `PLAYER_MODE_CASTING` for 610-640 ms.

    A command sent inside that window spends the cast without landing the
    buff, which from the bot's side looks like a recast loop (stage B run
    9). The next click has to wait — asked of the game, not slept for.
    """
    executor, gated, _, world = casting(monkeypatch)
    executor.execute(CastSelf(offsets.SKILL_BONE_ARMOR))
    world["mode"] = offsets.PLAYER_MODE_CASTING
    with pytest.raises(CastInFlight):
        executor.execute(CastAtPoint(offsets.SKILL_DESECRATE, (1010, 1002)))
    assert gated.world_clicks == [(HOME, "right", False)]  # only the first cast


def test_a_potion_never_waits_for_a_cast(monkeypatch):
    """The point of not sleeping: survival keeps its fastest response.

    T48 pressed a hotkey 110 ms INTO an animation and it registered within
    62 ms, so a drink — which is a keypress — has no reason to queue. The
    0.4 s sleep this replaces stopped every rung for the whole animation.
    """
    executor, gated, _, world = casting(monkeypatch)
    executor.execute(CastSelf(offsets.SKILL_BONE_ARMOR))
    world["mode"] = offsets.PLAYER_MODE_CASTING
    executor.execute(DrinkPotion(0, "mana"))
    assert VK_1 in gated.pressed


def test_the_click_lands_once_the_animation_is_over(monkeypatch):
    executor, gated, _, world = casting(monkeypatch)
    executor.execute(CastSelf(offsets.SKILL_BONE_ARMOR))
    world["mode"] = 1  # back to idle: the cast resolved
    executor.execute(CastAtPoint(offsets.SKILL_DESECRATE, (1010, 1002)))
    assert gated.world_clicks[-1] == ((1010, 1002), "right", False)


def test_a_mode_that_never_clears_costs_one_action_not_the_run(monkeypatch):
    # The cap is why the read is safe to trust: a client state nobody
    # anticipated must not be able to hold every click forever.
    executor, gated, clock, world = casting(monkeypatch)
    executor.execute(CastSelf(offsets.SKILL_BONE_ARMOR))
    world["mode"] = offsets.PLAYER_MODE_CASTING
    clock.advance(2.0)  # past cast_wait_cap_s 1.5
    executor.execute(CastAtPoint(offsets.SKILL_DESECRATE, (1010, 1002)))
    assert gated.world_clicks[-1] == ((1010, 1002), "right", False)


def test_nothing_is_read_until_we_have_actually_cast(monkeypatch):
    # An attack before any cast must not pay a stat read to ask about an
    # animation that cannot be playing.
    executor, _, _, world = casting(monkeypatch)
    executor.execute(AttackUnit(1, (1002, 1000)))
    assert world["reads"] == 0


def test_drink_presses_the_column_key(monkeypatch):
    executor, gated, _, _ = make(monkeypatch)
    executor.execute(DrinkPotion(0, "mana"))
    assert gated.pressed == [VK_1]
    assert "key 1" in executor.trace[0].detail


def test_give_merc_potion_presses_the_shift_chord(monkeypatch):
    executor, gated, _, _ = make(monkeypatch)
    executor.execute(GiveMercPotion(2))
    assert gated.pressed == [("shift", VK_3)]
    assert "shift+key 3" in executor.trace[0].detail


def test_merc_feed_never_waits_for_a_cast(monkeypatch):
    # Same T48 reasoning as the drink: a keypress lands mid-animation, so
    # the merc's potion must not queue behind our own cast.
    executor, gated, _, world = casting(monkeypatch)
    executor.execute(CastSelf(offsets.SKILL_BONE_ARMOR))
    world["mode"] = offsets.PLAYER_MODE_CASTING
    executor.execute(GiveMercPotion(2))
    assert ("shift", VK_3) in gated.pressed


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
    assert len(gated.screen_clicks) == 1
    (_, button, stand_still) = gated.screen_clicks[0]
    assert button == "left" and stand_still is False
    assert gated.world_clicks == []


def test_pickup_aims_at_the_sprite_not_the_tile(monkeypatch):
    # T63: the clickable sprite draws ABOVE the projected ground tile —
    # attempt 0 clicks the schedule's first measured offset, not the tile.
    from pd2bot.behavior.execute import _PICKUP_OFFSETS

    executor, gated, _, _ = make(monkeypatch)
    executor.execute(PickUpItem(7, (1002, 1000)))
    base = gated.BASE
    dx, dy = _PICKUP_OFFSETS[0]
    assert gated.screen_clicks[0][0] == (base[0] + dx, base[1] + dy)
    assert "sprite click" in executor.trace[-1].detail


def test_pickup_retries_aim_at_different_points(monkeypatch):
    # A retry that cannot differ from the attempt it retries is not a
    # retry: each attempt index selects the next offset of the schedule.
    from pd2bot.behavior.execute import _PICKUP_OFFSETS

    executor, gated, _, _ = make(monkeypatch)
    for attempt in range(3):
        executor.execute(PickUpItem(7, (1002, 1000), attempt=attempt))
    base = gated.BASE
    expected = [
        (base[0] + dx, base[1] + dy) for dx, dy in _PICKUP_OFFSETS[:3]
    ]
    assert [point for point, _, _ in gated.screen_clicks] == expected
    assert len(set(expected)) == 3  # genuinely different aims


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
