"""The player character's own state."""

from __future__ import annotations

from dataclasses import dataclass

from pd2bot import offsets
from pd2bot.memory import GameSession
from pd2bot.units import player_unit, read_stats, unit_position


@dataclass(frozen=True)
class ActiveSkills:
    """What the two mouse buttons would cast right now.

    Read fresh before every cast decision: the whole point (M5) is verifying
    that a hotkey switch actually took before any click trusts it — the
    difficulty-guard pattern applied to skills. `None` in a slot means the
    chain was unreadable mid-transition, not "no skill".
    """

    left_id: int | None
    right_id: int | None


def _skill_id(session: GameSession, skill_slot_addr: int) -> int | None:
    """Follow Skill* -> SkillsTxt -> wSkillId; None if any link is null."""
    skill = session.ptr(skill_slot_addr)
    if skill is None:
        return None
    txt = session.ptr(skill + offsets.SKILL_TXT)
    if txt is None:
        return None
    return session.u16(txt + offsets.SKILLTXT_ID)


def read_active_skills(session: GameSession) -> ActiveSkills | None:
    """The player's active left/right skill ids, or None when not in a game.

    Also None mid-transition, when the unit exists but the Info chain does
    not yet — the same poll-through-it posture as `read_player`.
    """
    try:
        unit = player_unit(session)
        if unit is None:
            return None
        info = session.ptr(unit + offsets.UNIT_INFO)
        if info is None:
            return None
        return ActiveSkills(
            left_id=_skill_id(session, info + offsets.INFO_LEFT_SKILL),
            right_id=_skill_id(session, info + offsets.INFO_RIGHT_SKILL),
        )
    except Exception:
        return None  # a torn chain mid-load is a normal state, not an error


@dataclass(frozen=True)
class Player:
    name: str
    level: int
    act: int  # 1-5 as players count them, not the 0-based value in memory
    position: tuple[int, int]
    mode: int  # UNIT_MODE: animation state; 0/17 mean dead (offsets.PLAYER_MODE_*)
    hp: int
    max_hp: int
    mana: int
    max_mana: int
    stamina: int
    max_stamina: int
    experience: int
    gold: int
    gold_stash: int
    strength: int
    dexterity: int
    vitality: int
    energy: int

    @property
    def hp_fraction(self) -> float | None:
        return self.hp / self.max_hp if self.max_hp else None

    @property
    def mana_fraction(self) -> float | None:
        return self.mana / self.max_mana if self.max_mana else None


def read_player(session: GameSession) -> Player | None:
    """Read the player's state, or None when not in a game.

    Also returns None mid-transition (loading screens), when the unit exists but
    its position or data pointers do not yet — a normal state to poll through,
    not an error.
    """
    unit = player_unit(session)
    if unit is None:
        return None

    position = unit_position(session, unit, offsets.UNIT_TYPE_PLAYER)
    data = session.ptr(unit + offsets.UNIT_DATA)
    if position is None or data is None:
        return None

    stats = read_stats(session, unit)
    return Player(
        name=session.cstring(data + offsets.PLAYER_NAME, offsets.PLAYER_NAME_LEN),
        level=stats.get(offsets.STAT_LEVEL, 0),
        act=session.u32(unit + offsets.UNIT_ACT_NO) + 1,
        position=position,
        mode=session.u32(unit + offsets.UNIT_MODE),
        hp=stats.get(offsets.STAT_HP, 0),
        max_hp=stats.get(offsets.STAT_MAX_HP, 0),
        mana=stats.get(offsets.STAT_MANA, 0),
        max_mana=stats.get(offsets.STAT_MAX_MANA, 0),
        stamina=stats.get(offsets.STAT_STAMINA, 0),
        max_stamina=stats.get(offsets.STAT_MAX_STAMINA, 0),
        experience=stats.get(offsets.STAT_EXPERIENCE, 0),
        gold=stats.get(offsets.STAT_GOLD, 0),
        gold_stash=stats.get(offsets.STAT_GOLD_BANK, 0),
        strength=stats.get(offsets.STAT_STRENGTH, 0),
        dexterity=stats.get(offsets.STAT_DEXTERITY, 0),
        vitality=stats.get(offsets.STAT_VITALITY, 0),
        energy=stats.get(offsets.STAT_ENERGY, 0),
    )
