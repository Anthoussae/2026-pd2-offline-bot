"""Every memory offset and game constant used by the bot, in one place.

Source of truth: Project-Diablo-2/BH @ main (the PD2 team's own open-source
maphack), fetched 2026-07-28. Each entry cites the BH file and line it came
from so it can be re-verified after a season patch.

BH is the primary source but not the sole one: the CollMap block below is
absent from BH and is cited from two independent community sources instead
(see that section). Non-BH entries carry their own citations.

PD2's client is Diablo II **1.13c**. BH's VARPTR/FUNCPTR macros list offsets
per version with 1.13c first (D2Ptrs.h:82-89), so the *first* address in each
macro is ours.

Do not put a magic offset anywhere else in this codebase. Values marked
"verified live" were confirmed against the running client during M1/M2.
"""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

# --- module-relative pointers (add to D2Client.dll's runtime base) ----------

# D2Ptrs.h:235  VARPTR(D2CLIENT, PlayerUnit, UnitAny*, 0x11BBFC, 0x11D050)
# Verified live (M1): NULL in the menus, valid UnitAny* while in a game.
PLAYER_UNIT_PTR = 0x11BBFC

# D2Ptrs.h:156  FUNCPTR(D2CLIENT, GetUiVar_I, ..., 0xBE400, 0x17C50)
# A function, not a variable — P2 parses its code to locate the UI array.
GET_UI_VAR_FN = 0xBE400

# D2Ptrs.h:152  FUNCPTR(D2CLIENT, GetDifficulty, BYTE __stdcall, (void), 0x41930, 0x42980)
# BH exposes difficulty only as a function (it runs in-process and can call
# it). Same drill as GetUiVar_I: oog/world parses the function's code to find
# the byte it reads, so a patch that moves the variable is picked up
# automatically. Values: 0 normal, 1 nightmare, 2 hell (kolbot sdk.difficulty).
GET_DIFFICULTY_FN = 0x41930
DIFFICULTY_NORMAL = 0
DIFFICULTY_NIGHTMARE = 1
DIFFICULTY_HELL = 2
DIFFICULTY_NAMES = {0: "normal", 1: "nightmare", 2: "hell"}

# D2Ptrs.h  VARPTR(D2CLIENT, pUnitTable, POINT, 0x10A608, 0x1047B8)
# The client's unit hash table: UNIT_TYPE_COUNT tables of HASH_BUCKETS
# entries, each the head of a chain linked by UNIT_LIST_NEXT.
#
# This is the authoritative way to enumerate units. Walking rooms
# (Room1.pUnitFirst -> pRoomNext) does NOT list them all: with a merc and
# two skeletons out and an item on the floor, room traversal found one
# type-1 unit and zero items (instruction log R20). Rooms remain the right
# structure for collision maps, not for units.
UNIT_TABLE_PTR = 0x10A608
UNIT_HASH_BUCKETS = 128
UNIT_TYPE_COUNT = 6  # player, monster, object, missile, item, tile

# --- UnitAny (D2Structs.h:690) ---------------------------------------------

UNIT_TYPE = 0x00  # dwType: 0=player 1=monster 2=object 3=missile 4=item 5=tile
UNIT_TXT_FILE_NO = 0x04  # dwTxtFileNo: which monster/item type this is
UNIT_ID = 0x0C  # dwUnitId
UNIT_MODE = 0x10  # dwMode (death/idle/walking/...)
UNIT_DATA = 0x14  # union: pPlayerData | pItemData | pMonsterData | pObjectData
UNIT_ACT_NO = 0x18  # dwAct, 0-based
UNIT_ACT = 0x1C  # Act*
UNIT_PATH = 0x2C  # union: pPath | pItemPath | pObjectPath
UNIT_STATS = 0x5C  # StatList*
UNIT_INVENTORY = 0x60  # Inventory*
UNIT_ROOM_NEXT = 0xE4  # pRoomNext: next unit in the same Room1
UNIT_LIST_NEXT = 0xE8  # pListNext

# dwType values (D2 unit types)
UNIT_TYPE_PLAYER = 0
UNIT_TYPE_MONSTER = 1
UNIT_TYPE_OBJECT = 2
UNIT_TYPE_MISSILE = 3
UNIT_TYPE_ITEM = 4
UNIT_TYPE_TILE = 5

# --- PlayerData (D2Structs.h:213) ------------------------------------------

PLAYER_NAME = 0x00  # szName, char[16]
PLAYER_NAME_LEN = 16

# --- Skills: the Info chain (M5) -------------------------------------------
#
# UnitAny.pInfo (D2Structs.h:737, Info* at 0xA8) leads to the unit's skill
# state: Info (D2Structs.h:503-508) holds the known-skill list and, crucially,
# the two *active* slots — pLeftSkill/pRightSkill. Reading the right slot is
# how a hotkey switch is verified before any cast click (the difficulty-guard
# pattern applied to skills: never trust that a keypress took).
#
# Skill.pSkillInfo (D2Structs.h:488-489) points at SkillsTxt, which BH leaves
# opaque; the id offset comes from the second lineage, noah-/d2bs
# D2Structs.h:454-456 (struct SkillInfo { WORD wSkillId; //0x00 }) — the
# engine kolbot's unit.getSkill() ran on. Verified live (R52 drill A,
# 2026-07-29): every F1-F6 press read back a distinct, stable id.

UNIT_INFO = 0xA8  # Info*
INFO_FIRST_SKILL = 0x04  # Skill* — head of the known-skill list
INFO_LEFT_SKILL = 0x08  # Skill* — the active left slot
INFO_RIGHT_SKILL = 0x0C  # Skill* — the active right slot
SKILL_TXT = 0x00  # Skill.pSkillInfo -> SkillsTxt*
SKILL_NEXT = 0x04  # Skill.pNextSkill — walk the known-skill list
SKILLTXT_ID = 0x00  # SkillsTxt.wSkillId, WORD (d2bs lineage)

# The necro kit's skill ids, captured live (R52 drill A: the user pressed
# each hotkey while the right slot was read; left slot observed constant).
# 73/68/78/95 match classic 1.13c necro ids; 367 (Blood Warp) and 83
# (Desecrate) are PD2's own; 220 is the tome-of-town-portal book skill.
SKILL_POISON_STRIKE = 73  # the permanent left skill (classic Poison Dagger slot)
SKILL_BONE_ARMOR = 68  # F1
SKILL_BLOOD_WARP = 367  # F2
SKILL_TP_TOME = 220  # F3 (unused in M5)
SKILL_BONE_WALL = 78  # F4 (unused in M5)
SKILL_DESECRATE = 83  # F5
SKILL_REVIVE = 95  # F6

# --- Path (D2Structs.h:396) — for units that move --------------------------

PATH_X = 0x02  # xPos, WORD (world coords)
PATH_Y = 0x06  # yPos, WORD
PATH_ROOM1 = 0x1C  # Room1*

# --- ItemPath (D2Structs.h:421) — for units that don't ---------------------

ITEM_PATH_X = 0x0C  # dwPosX, DWORD
ITEM_PATH_Y = 0x10  # dwPosY, DWORD

# --- ObjectPath (D2Structs.h:645-651) — waypoints, stash, doors, shrines ----
# Objects are static; their path keeps Room1* at 0x00 and DWORD world
# coordinates at the same 0x0C/0x10 slots ItemPath uses. Kept as separate
# names anyway: the structs are different and only happen to agree today.
OBJECT_PATH_X = 0x0C  # dwPosX, DWORD
OBJECT_PATH_Y = 0x10  # dwPosY, DWORD

# --- StatList (D2Structs.h:435) --------------------------------------------
#
# Two arrays live here, and picking the wrong one is a real trap (M1 read
# hp=961/920 — a current value above the maximum — from the base array):
#   base  pStat    @0x24 / wStatCount1   @0x28  -> stats BEFORE item/skill bonuses
#   full  pSetStat @0x48 / wSetStatCount @0x4C  -> the computed totals  <-- use this
STATLIST_BASE_ARRAY = 0x24
STATLIST_BASE_COUNT = 0x28
STATLIST_FULL_ARRAY = 0x48
STATLIST_FULL_COUNT = 0x4C
STAT_ENTRY_SIZE = 8  # Stat{WORD wSubIndex, WORD wStatIndex, DWORD dwStatValue}

# --- Stat indices (verified live, M1) --------------------------------------

STAT_STRENGTH = 0
STAT_ENERGY = 1
STAT_DEXTERITY = 2
STAT_VITALITY = 3
STAT_HP = 6
STAT_MAX_HP = 7
STAT_MANA = 8
STAT_MAX_MANA = 9
STAT_STAMINA = 10
STAT_MAX_STAMINA = 11
STAT_LEVEL = 12
STAT_EXPERIENCE = 13
# The COMBAT-RATED markers (T74, 2026-08-06). A unit that carries any of
# these is a thing that can fight or be fought; a unit carrying none of
# them is scenery.
#
# Measured, not assumed. T74 read the stat lists of a Fallen (kind 21),
# a Goatman (55), the Rogue merc (271) and the decorative bats the bot
# had been attacking for 173 s (kind 159, MonStats code "B9"):
#
#   Fallen   6, 7, 12, 36, 39, 41, 43, 45, 67, 68, 69, 190, 328
#   Goatman  6, 7, 12, 36, 39, 67, 68, 69, 328
#   merc     6, 7, 12, 39, 41, 43, 45, ... (76 stats)
#   BAT      6, 7, 67, 68, 69           <- hp, max hp, and animation rates
#
# The bat carries exactly enough to draw and move a sprite and nothing
# else: no level, no resistances, no experience.
#
# An OR rather than a single stat, and deliberately: the failure we now
# fear is a PACIFIST bot (T73 caught that fix one step from being
# written), so this is generous about what counts as a combatant and
# strict only about what carries none of it. D2 omits zero-valued stats,
# so a monster with no resistances still answers on its level.
STAT_DAMAGE_RESIST = 36
STAT_FIRE_RESIST = 39
STAT_LIGHT_RESIST = 41
STAT_COLD_RESIST = 43
STAT_POISON_RESIST = 45
COMBAT_RATED_STATS = frozenset(
    {
        STAT_LEVEL,
        STAT_EXPERIENCE,
        STAT_DAMAGE_RESIST,
        STAT_FIRE_RESIST,
        STAT_LIGHT_RESIST,
        STAT_COLD_RESIST,
        STAT_POISON_RESIST,
    }
)
STAT_GOLD = 14
STAT_GOLD_BANK = 15
# Bone Armor's remaining/maximum absorb (the small square by the HP orb).
# kolbot sdk/types/sdk.d.ts:1203-1205 (SkillBoneArmor: 132,
# SkillBoneArmorMax: 133). Verified live (R52 drill B, 2026-07-29): both
# present on the armored character, fixed-point, equal at full
# (raw 221696 = 866 << 8). The remaining check — 132 falling as the armor
# absorbs hits — needs a live hit and is deferred to the first supervised
# combat stage (P6); the <75% upkeep rule is a ratio, unaffected either way.
STAT_BONE_ARMOR = 132
STAT_BONE_ARMOR_MAX = 133
# Socket count on an ITEM unit (kolbot sdk: sdk.stats.NumSockets = 194).
#
# VERIFIED LIVE (T38, 2026-07-31). The user was the oracle and the answer
# arrived as an action, because a plausible number is exactly what cannot
# be trusted here — T18 produced a confident, precise, WRONG calibration
# and nothing downstream could tell (R86). So the drill stated every
# socket count it read (five equipped items: 1/1/5/1/3, plus one
# inventory item) and asked the user to DROP the socketed inventory item
# only if all of them were right. They dropped it.
#
# Both halves of the read are covered: kind 441 read 3 sockets CARRIED and
# 3 again ON THE GROUND — the ground path being the one the pickit
# actually uses, and a different code path from the carried read.
STAT_NUM_SOCKETS = 194
# Item durability (kolbot sdk/types/sdk.d.ts, sdk.stats Durability/MaxDurability).
# Read off ITEM units, not the player. Items with no maximum (rings, charms,
# amulets) simply lack these — absence means "indestructible or not
# applicable", never "broken". Verified live (T18, R72): exactly 7 worn
# items carried a maximum — helm, armour, weapon, shield, boots, gloves,
# belt, with rings/amulet/charms correctly absent — and all read 100%.
STAT_DURABILITY = 72
STAT_MAX_DURABILITY = 73
# Alignment separates friend from foe. D2 has no separate unit type for
# mercenaries, summons or friendly NPCs — they are all dwType 1 ("monster")
# — so this stat is the only thing distinguishing your skeletons from the
# things trying to kill you. kolbot filters on exactly this
# (Prototypes.js:90, :2370; sdk.d.ts:1169 Alignment: 172).
STAT_ALIGNMENT = 172
ALIGNMENT_FRIENDLY = 2

# Mercenary class ids (kolbot sdk.d.ts:2721-2724). Not needed for the
# friend/foe test — alignment covers it — but useful for naming what we see.
MERC_CLASS_IDS = {
    271: "rogue",
    338: "desert_guard",
    359: "iron_wolf",
    561: "barbarian",
}

# NON-PLAYER units carry their CURRENT life on a 0-128 scale in STAT_HP,
# while STAT_MAX_HP holds the real maximum — so hp/max_hp is the wrong
# fraction for them. Probed live 2026-08-02 (T54 run 3's phantom merc
# trigger): the full-health rogue read hp 128 with max_hp 1620, i.e. a
# permanent "8%" that fed her potions all game. kolbot computes merc
# life% as hp*100/128 for the same reason. The player is different:
# player hp/max_hp are both real (chicken depends on it, live-proven).
NONPLAYER_HP_SCALE = 128

# Only these are stored fixed-point and need `>> 8`. Applying the shift to the
# others (level, attributes, gold, experience) silently zeroes them. The bone
# armor pair joined on live evidence: raw 221696 = 866 << 8 with a zero low
# byte, and 221696 absorb is absurd where 866 is exactly right (R52 drill B).
FIXED_POINT_STATS = frozenset(
    {
        STAT_HP,
        STAT_MAX_HP,
        STAT_MANA,
        STAT_MAX_MANA,
        STAT_STAMINA,
        STAT_MAX_STAMINA,
        STAT_BONE_ARMOR,
        STAT_BONE_ARMOR_MAX,
    }
)

# --- Act (D2Structs.h:387) -------------------------------------------------

ACT_MAP_SEED = 0x0C  # dwMapSeed
ACT_ROOM1 = 0x10
ACT_NO = 0x14  # dwAct
ACT_MISC = 0x48  # ActMisc*

# --- Room1 (D2Structs.h:360) — runtime rooms, hold the units ---------------

ROOM1_ROOMS_NEAR = 0x00  # Room1**, adjacent rooms
ROOM1_ROOM2 = 0x10  # Room2*
ROOM1_COLL = 0x20  # CollMap* (M3: layout is NOT in BH, source it elsewhere)
ROOM1_ROOMS_NEAR_COUNT = 0x24  # dwRoomsNear
ROOM1_UNIT_FIRST = 0x74  # pUnitFirst -> walk via UNIT_ROOM_NEXT
ROOM1_ROOM_NEXT = 0x7C

# --- CollMap (NOT in BH — sources corrected against the live client) --------
#
# Room1.Coll (ROOM1_COLL above) points here. BH's D2Structs.h stops at the
# pointer, so the layout came from two separately maintained lineages,
# fetched and diffed 2026-07-28 (they agree field-for-field):
#   (1) noah-/d2bs D2Structs.h (the D2BS engine kolbot ran on), struct CollMap
#   (2) jankowskib/d2server d2warden-pvp/D2Structs_111B.h, struct CollMap
#
# Both end with `WORD* pMapStart; //0x20` and `WORD* pMapEnd; //0x22`, and
# 0x22 cannot be right for a pointer following a pointer at 0x20. Reading
# 0x24 as pMapEnd instead was ALSO wrong, and the live client said so
# (`python -m pd2bot.collision --debug`, 2026-07-28): every room reported
# pMapStart == Coll + 0x24, i.e. the grid is stored **inline right after a
# 0x24-byte header**, and the dword at 0x24 is the first two collision
# cells (observed 0x00010001 = two blocked, 0x00000000 = two open) — not a
# pointer at all. There is no usable pMapEnd; the grid's extent comes from
# the size fields. Treat the community headers as a starting hypothesis for
# this struct, not as truth.
#
# The grid: one WORD of collision flags per subtile, row-major,
# dwSizeGameX wide by dwSizeGameY tall, starting at pMapStart. dwPosGameX/Y
# is the grid's origin in world subtiles.
#
# The room fields give a strong structural check, verified live: game
# (subtile) values are exactly 5x the room (tile) values — observed
# posRoom 1184x1144 -> posGame 5920x5720, sizeRoom 8x8 -> sizeGame 40x40.
# collision.py validates that instead of the bogus pointer arithmetic.

COLLMAP_POS_GAME_X = 0x00  # dwPosGameX — grid origin, world subtiles
COLLMAP_POS_GAME_Y = 0x04
COLLMAP_SIZE_GAME_X = 0x08  # dwSizeGameX — grid width in subtiles
COLLMAP_SIZE_GAME_Y = 0x0C
COLLMAP_POS_ROOM_X = 0x10  # dwPosRoomX — the same origin in tiles
COLLMAP_POS_ROOM_Y = 0x14
COLLMAP_SIZE_ROOM_X = 0x18  # dwSizeRoomX — the same size in tiles
COLLMAP_SIZE_ROOM_Y = 0x1C
COLLMAP_MAP_START = 0x20  # WORD* pMapStart — points at Coll+0x24 (inline)
COLLMAP_HEADER_SIZE = 0x24  # where the inline grid begins

# Collision flag words (kolbot sdk/types/sdk.d.ts:70-95 `sdk.collision`;
# same values in D2 community headers). We only *name* what we use:
COLL_BLOCK_WALL = 0x0001
COLL_RANGED = 0x0004  # blocks walking but not missiles (e.g. water edges)
COLL_PLAYERS = 0x0080
COLL_MONSTERS = 0x0100
COLL_ITEMS = 0x0200
COLL_CLOSED_DOOR = 0x0800
COLL_IS_ON_FLOOR = 0x1000  # something occupies the subtile
COLL_FRIENDLY_NPC = 0x2000
COLL_DEAD_BODIES = 0x8000

# Walkability mask = kolbot's sdk.collision.BlockWalk (0x1805): the mask its
# pathing treats as "you cannot walk here" *right now*. Doors count as
# blocked until M4 learns to open them.
COLL_UNWALKABLE_MASK = (
    COLL_BLOCK_WALL | COLL_RANGED | COLL_CLOSED_DOOR | COLL_IS_ON_FLOOR
)

# Bits that describe *occupancy*, not terrain: they change second to second
# as monsters walk, items drop, and corpses pile up. Live reads want them;
# the persistent atlas (mapstore.py) must strip them, for two reasons found
# during the first survey walk (2026-07-28):
#   1. churn — a monster taking one step rewrote the room's bytes, so a
#      single area re-saved 247 times instead of a few dozen;
#   2. worse, IS_ON_FLOOR is inside the walkability mask, so a corpse or a
#      dropped item present during a survey would be frozen into the atlas
#      as a permanent wall that no later visit could clear.
COLL_TRANSIENT_MASK = (
    COLL_PLAYERS
    | COLL_MONSTERS
    | COLL_ITEMS
    | COLL_IS_ON_FLOOR
    | COLL_FRIENDLY_NPC
    | COLL_DEAD_BODIES
)

# For diagnostics: naming a bit beats printing a bare hex value when asking
# "why did this room change?". Names follow kolbot's sdk.collision.
COLL_FLAG_NAMES = {
    COLL_BLOCK_WALL: "block_wall",
    0x0002: "line_of_sight",
    COLL_RANGED: "ranged",
    0x0008: "player_to_walk",
    0x0010: "dark_area",
    0x0020: "casting",
    0x0040: "unknown_40",
    COLL_PLAYERS: "players",
    COLL_MONSTERS: "monsters",
    COLL_ITEMS: "items",
    0x0400: "objects",
    COLL_CLOSED_DOOR: "closed_door",
    COLL_IS_ON_FLOOR: "is_on_floor",
    COLL_FRIENDLY_NPC: "friendly_npc",
    0x4000: "unknown_4000",
    COLL_DEAD_BODIES: "dead_bodies",
}

# --- Room2 (D2Structs.h:333-356) — static/preset room layer ----------------
# Unlike Room1 (runtime, only the player's neighbourhood loaded), Room2
# spans the WHOLE level once the level is initialized — which is what makes
# area-wide exit enumeration possible from anywhere in the area (M6 P1).
# Layout cross-checked 2026-08-03 against d2mapapi_mod's independent
# lineage (d2structs.h, struct Room2_113): field-for-field agreement.

ROOM2_NEXT = 0x24  # Room2* pRoom2Next — the level-wide chain
ROOM2_ROOM1 = 0x30
ROOM2_POS_X = 0x34  # dwPosX, in TILES (x5 for subtiles)
ROOM2_POS_Y = 0x38  # dwPosY
ROOM2_SIZE_X = 0x3C  # dwSizeX
ROOM2_SIZE_Y = 0x40  # dwSizeY
ROOM2_ROOM_TILES = 0x4C  # RoomTile* — warp connections out of this room
ROOM2_LEVEL = 0x58  # Level*
ROOM2_PRESET = 0x5C  # PresetUnit* — preset npcs/objects/warp tiles

# --- RoomTile (D2Structs.h:159-164) — one warp connection -------------------
# A RoomTile says "this room connects, via warp number *nNum, to pRoom2
# (a room in the DESTINATION level)". Cross-checked against d2mapapi_mod
# struct RoomTile113: agreement.

ROOMTILE_ROOM2 = 0x00  # Room2* — destination-side room
ROOMTILE_NEXT = 0x04  # RoomTile*
ROOMTILE_NUM_PTR = 0x10  # DWORD* nNum — POINTER to the warp number

# --- PresetUnit (D2Structs.h:307-315) — preset placements in a Room2 -------
# Positions are RELATIVE to the room: world subtile = room2 tile pos * 5 +
# preset pos (d2mapapi mapdata.cpp:205-206, the vendored generator's own
# arithmetic). Cross-checked against d2mapapi_mod struct PresetUnit113.

PRESET_TXT_FILE_NO = 0x04  # dwTxtFileNo
PRESET_POS_X = 0x08  # dwPosX, subtiles within the room
PRESET_NEXT = 0x0C  # PresetUnit* pPresetNext
PRESET_TYPE = 0x14  # dwType
PRESET_POS_Y = 0x18  # dwPosY
# dwType values as d2mapapi names them (mapdata.cpp:21-23): 1 npc,
# 2 object, 5 tile. A TILE preset is a warp — a staircase, a doorway —
# and matching its dwTxtFileNo against a RoomTile's *nNum is how the
# generator itself locates level exits (mapdata.cpp:217-232).
PRESET_TYPE_NPC = 1
PRESET_TYPE_OBJECT = 2
PRESET_TYPE_TILE = 5

# --- Level (D2Structs.h:317-331) --------------------------------------------

LEVEL_ROOM2_FIRST = 0x10  # Room2* — the level-wide static room chain
LEVEL_POS_X = 0x1C
LEVEL_POS_Y = 0x20
LEVEL_SIZE_X = 0x24
LEVEL_SIZE_Y = 0x28
LEVEL_NO = 0x1D0  # dwLevelNo — which area this is

# --- MonsterData (D2Structs.h:610) -----------------------------------------

MONSTER_NAME_SEED = 0x14
MONSTER_FLAGS = 0x16  # bitfield: bit1 fNormal, bit2 fChamp, bit3 fBoss, bit4 fMinion
MONSTER_FLAG_NORMAL = 1 << 1
MONSTER_FLAG_CHAMPION = 1 << 2
MONSTER_FLAG_BOSS = 1 << 3
MONSTER_FLAG_MINION = 1 << 4
# Super-unique identity (M6 P1, the Countess). wUniqueNo indexes
# superuniques.txt. wName turned out to hold GARBAGE on live units (T68)
# — kept readable as a diagnostic only, never identity.
MONSTER_UNIQUE_NO = 0x26  # WORD wUniqueNo
MONSTER_NAME = 0x2C  # wchar_t wName[28]
MONSTER_NAME_CHARS = 28
# The Countess herself, live-captured: T68 read kind 734 / unique_no 6
# in Tower Cellar Level 5 (2026-08-05), and the user confirmed her alive
# on screen during that visit (R216). unique_no 6 is superuniques.txt's
# Countess row — two independent facts agreeing, the usual bar.
COUNTESS_KIND = 734
COUNTESS_UNIQUE_NO = 6

# --- ItemData (D2Structs.h:510) --------------------------------------------

ITEM_QUALITY = 0x00  # dwQuality
ITEM_FLAGS = 0x0C  # dwItemFlags
ITEM_LEVEL = 0x2C  # dwItemLevel
# ITEM_LOCATION (0x45, per BH's header) is NOT trusted: the live check
# (2026-07-28, instruction log R17) showed a carried item reading 0xFF
# there — it appeared as a ground item at its inventory grid slot (5, 0).
# On-the-floor detection uses the unit's mode instead; see below.
ITEM_LOCATION = 0x45
ITEM_LOCATION_NONE = 0xFF

# Carried-item classification (M5). Three ItemData bytes describe where an
# item lives; BH's own header comments rank their trustworthiness:
#   BodyLocation 0x44 (D2Structs.h:525) — equip slot, "Not always cleared"
#   ItemLocation 0x45 (D2Structs.h:526) — the byte that lied live (R17)
#   GameLocation 0x68 — unnamed filler in BH (`_11`, D2Structs.h:534); named
#     by the d2bs lineage (D2Structs.h:502) as kolbot's `unit.location`
#   NodePage     0x69 (D2Structs.h:535) — "Actual location, this is the most
#     reliable by far" (BH's comment, same text in d2bs)
# Classification therefore leans on the unit MODE first (proven live, R17/
# R19) with GameLocation distinguishing the storage containers; NodePage is
# read and dumped as the cross-check. Verified live (R52 drill C,
# 2026-07-29): one potion moved inventory -> belt -> stash -> back read
# consistent mode/loc/node triples at every hop ((0,3,1), (2,2,2), (0,7,1)),
# with correct grid coordinates in each container and the belt-column
# cascade confirming slot%4 arithmetic. One surprise: an item HELD ON THE
# CURSOR leaves the inventory chain entirely — it is reachable only through
# Inventory.pCursorItem (INVENTORY_CURSOR_ITEM), which items.py reads
# separately.
ITEM_BODY_LOCATION = 0x44
ITEM_GAME_LOCATION = 0x68
ITEM_NODE_PAGE = 0x69
ITEM_NEXT_INV = 0x64  # ItemData.pNextInvItem (D2Structs.h:533) — inventory chain

# Inventory struct (D2Structs.h:466-478), pointed at by UNIT_INVENTORY.
INVENTORY_FIRST_ITEM = 0x0C  # UnitAny* pFirstItem
INVENTORY_LAST_ITEM = 0x10  # UnitAny* pLastItem
INVENTORY_CURSOR_ITEM = 0x20  # UnitAny* pCursorItem

# The STORE array (D2Structs.h:472-473 pStores/dwStoresCount, and
# InventoryStore at :456-464). Each store is a grid the character can hold
# items in — inventory, stash, cube — with its own width and height.
#
# Why this matters (R75 Q5): the bot must know WHICH stash tab is showing,
# and T15 proved the raw UI array does not move across a tab toggle, so
# there is no panel flag to read. The store array was the next place to
# look, and it answered (T22, R77): the stash store's ITEM-CHAIN HEAD goes
# null exactly while the materials tab is displayed, and returns when the
# regular tab comes back — six toggles, six times, with the grid pointer
# and dimensions untouched throughout.
#
# The same dump identified every store this character has, which is worth
# recording because three of them corroborate findings we reached the hard
# way:
#
#     store 0   13x1    equipment (13 body locations)
#     store 1   16x1    the belt — exactly the 16 slots R47.6 described
#     store 2   10x8    inventory AND charm space in ONE grid: the usable
#                       10x4 sits on top of the charm 10x4, which is why
#                       they share a container and only the cell
#                       coordinate separates them (R60, confirmed here)
#     store 6   10x15   the stash
#     stores 3-5 0x0, store 7 127x127 — unused/garbage past the real end
#
# Also seen: item location byte 8, absent from kolbot's storage table and
# present in BOTH tab states. Unidentified; possibly the materials tab or
# a shared-stash page. Nothing depends on it yet.
INVENTORY_STORES = 0x14  # InventoryStore* [dwStoresCount]
INVENTORY_STORES_COUNT = 0x18
STORE_SIZE = 0x10  # sizeof(InventoryStore)
STORE_FIRST_ITEM = 0x00
STORE_LAST_ITEM = 0x04
STORE_WIDTH = 0x08  # BYTE
STORE_HEIGHT = 0x09  # BYTE
STORE_GRID = 0x0C  # UnitAny* [height][width]
MAX_STORES = 16  # sanity bound; this character reports 8, not all valid
# The stash is found by its shape rather than its index, so a PD2 update
# that reorders the array fails loudly instead of silently reading the
# belt. Measured live (T22).
STASH_STORE_SIZE = (10, 15)

# GameLocation values = kolbot `sdk.storage` (libs/modules/sdk.js:2635-2642).
STORAGE_EQUIPPED = 1
STORAGE_BELT = 2
STORAGE_INVENTORY = 3
STORAGE_TRADE = 5
STORAGE_CUBE = 6
STORAGE_STASH = 7
# PD2's own addition, absent from kolbot's 1.13c list. Spotted in T38 as "a
# large unnamed container" holding 25 socketed items and identified in T45,
# where the live character had **350 items here and zero in STORAGE_STASH** —
# so on a PD2 character this, not location 7, is where the stash lives.
# Anything measuring "how full is the stash" must count both.
#
# NOT the materials tab, which T45 also settled: a gem deposited there left
# the player's inventory chain entirely and never appeared in this container.
# The materials tab is not enumerable at all, which is why T15/T36 could find
# no store for it.
STORAGE_EXPANDED_STASH = 8
STORAGE_NAMES = {
    STORAGE_EQUIPPED: "equipped",
    STORAGE_BELT: "belt",
    STORAGE_INVENTORY: "inventory",
    STORAGE_TRADE: "trade",
    STORAGE_CUBE: "cube",
    STORAGE_STASH: "stash",
    STORAGE_EXPANDED_STASH: "expanded_stash",
}

# NodePage values = kolbot `sdk.node` (libs/modules/sdk.js:2644-2650).
NODE_NOT_ON_PLAYER = 0
NODE_STORAGE = 1
NODE_BELT = 2
NODE_EQUIPPED = 3
NODE_CURSOR = 4

# The belt is 4 columns wide; a belt item's ItemPath x is its slot index,
# column = slot % 4 (kolbot Town.checkColumns uses exactly this). Rows vary
# by belt; this character wears a 4-row belt (16 slots, R47.6).
BELT_COLUMNS = 4
# This character's belt (R47.6). If the worn belt ever changes, the refill's
# capacity accounting reads short or long but never crashes — the halt logic
# it feeds only fires when stock AND room agree a click should have landed.
BELT_ROWS = 4

# The USABLE inventory grid: 10x4, cells (0,0)..(9,3). Measured live by the
# four-corner calibration (R60, 2026-07-30) with the user defining the
# corners.
#
# This rectangle is load-bearing, not cosmetic. PD2 puts a CHARM INVENTORY
# directly below the main grid, and the live probe showed those slots share
# the SAME container and the SAME ItemData bytes as ordinary inventory —
# game_location=3 (STORAGE_INVENTORY), node_page=1, mode=0, identical in
# every field we read. The ONLY thing separating locked charm space from
# usable space is the cell coordinate: y >= INVENTORY_ROWS is charm space.
#
# The character's 24 existing "inventory" items all live at y 4..7, so a
# consumer that trusted the container alone would have walked two dozen
# untouchable items — computing pixels for them, failing every transfer,
# and tripping the full-stash halt over a stash that was never full. The
# user flagged the charm space before it could happen (R56/R60); every
# consumer filters on this rectangle.
INVENTORY_COLS = 10
INVENTORY_ROWS = 4

# Item unit modes (UNIT_MODE for dwType==4), kolbot sdk `sdk.items.mode`
# (sdk/types/sdk.d.ts:2794-2801): inStorage=0, equipped=1, inBelt=2,
# onGround=3, onCursor=4, dropping=5, socketed=6. "On the floor" = onGround
# or mid-drop. Verified live (R17/R19): mode correctly distinguishes carried
# from dropped where 0x45 did not.
ITEM_MODE_IN_STORAGE = 0
ITEM_MODE_EQUIPPED = 1
ITEM_MODE_IN_BELT = 2
ITEM_MODE_ON_GROUND = 3
ITEM_MODE_ON_CURSOR = 4
ITEM_MODE_DROPPING = 5
ITEM_MODE_SOCKETED = 6

# Item quality (D2 standard values)
QUALITY_NAMES = {
    1: "low",
    2: "normal",
    3: "superior",
    4: "magic",
    5: "set",
    6: "rare",
    7: "unique",
    8: "crafted",
}

# --- Item kind tables (dwTxtFileNo values, M5) ------------------------------
#
# PD2 RENUMBERED the potions — kolbot's classic ids (healing 587-591, mana
# 592-596, rejuv 515/516) do not exist on this client. These ids were
# captured from the character's belt (R52 drill C) and the type attribution
# was PROVEN by effect, not layout lore (R54, 2026-07-29): key 1 consumed a
# kind-611 potion and the mana orb refilled 246->378. Belt layout is
# permanent per the user (R53): key 1 mana, key 2 rejuv, keys 3+4 health.
# Tier differences within a type are irrelevant for our purposes (R53), so
# names carry the kind id, nothing more. Only observed tiers are listed —
# extend as more are seen.

HEALING_POTION_KINDS = {
    602: "healing_602",  # hp1 (minor)
    603: "healing_603",  # hp2 (light)
    604: "healing_604",  # hp3
    605: "healing_605",  # hp4 (greater)
    606: "healing_606",  # hp5 (super)
}
MANA_POTION_KINDS = {
    607: "mana_607",  # mp1 (minor)
    608: "mana_608",  # mp2 (light)
    609: "mana_609",  # mp3
    610: "mana_610",  # mp4 (greater)
    611: "mana_611",  # mp5 (super)
}
REJUV_POTION_KINDS = {
    530: "rejuv_530",  # rvs (small)
    531: "rejuv_531",  # rvl (full)
}
# The full tier runs come from config/item_codes.toml — the game's OWN code
# table, read live by T42 (602-606 = hp1-hp5, 607-611 = mp1-mp5). "Only
# observed tiers" (above) turned out to be a trap that starved the belt:
# T56 game 2 chickened at 47% while two kind-605 (hp4) healing potions sat
# in the inventory reported as "no loadable stock", the town refill and
# ground pickup blind to every tier but hp5, and the belt hygiene one drink
# away from clearing real healing potions as "foreign".
POTION_KINDS = {**HEALING_POTION_KINDS, **MANA_POTION_KINDS, **REJUV_POTION_KINDS}

# The hovered-ITEM pointer, PLAYER-UNIT-RELATIVE (T58, 2026-08-03): while
# the cursor rests on a ground item, `player_unit + PLAYER_HOVER_ITEM`
# holds that item's unit address. Found by the T40-style pointer scan — 20
# holders in round A, ONE survivor of the change-away/come-back rounds,
# and that survivor sat at the player unit + 0xE8, which is why no pointer
# chain is needed: the player unit is already found per game. Measured
# caveats from the same drill: the pointer CLEARS over empty ground but
# can RETAIN the last item while the cursor is on a living unit, so a
# consumer must read it fresh after a deliberate cursor move and validate
# the target as an item-type unit (units.hovered_item_id does both).
PLAYER_HOVER_ITEM = 0xE8

# The ground-item LABEL DISPLAY toggle (ALT), found by T66 (2026-08-03):
# 117 modules diffed across four ALT presses, exactly ONE byte alternated
# in lockstep — in BH.dll, which is where PD2's loot-filter QoL lives.
# 1 = labels showing, 0 = hidden (semantics as read at T66's start).
BH_LABEL_MODULE = "BH.dll"
BH_LABEL_DISPLAY = 0x14D2CA

# Both live-verified by the T38 probe (64 and 72 charges respectively), and
# 534 corroborated at R112 where the bot identified an item by accident.
TOME_OF_TOWN_PORTAL = 533
TOME_OF_IDENTIFY = 534

# Gold's kind. kolbot's sdk said 523, and this carried that value with a
# note that it was unverified. It was WRONG: the live code table (T42) says
# kind 523 is `elx`, an elixir, and gold is 538 (`gld`). Settled from data
# rather than by waiting for a gold drop to disagree with us — which is what
# the P6 checklist had been waiting for (R144).
GOLD_KIND = 538

# --- The item-exception registry: everything whose right-click bites --------
#
# Some items DO something when right-clicked — a tome arms a cursor or opens
# a portal, the Cube opens, a scroll is consumed, a map opens its dungeon.
# The bot handles inventory with two MODIFIED right-clicks: the cleanse
# DROPS junk (ctrl+right-click) and the stash deposit TRANSFERS keepers
# (shift+right-click). Either modifier can slip (R112/R113 and T70 run 2:
# the same Tome of Identify used instead of moved, fifteen days apart, even
# with the modifier settle in place) — and a slipped modifier fires the
# bare right-click, whose side effect outlives the click and poisons
# everything after it. A portal opens in the WORLD and an armed identify
# cursor is not a cursor ITEM, so no UI read catches it afterwards: never
# aiming the gesture at these items is the only guardrail that works.
#
# So this is ONE registry keyed by kind, recording what the right-click
# does and therefore which gesture is unsafe, and the two sets the rest of
# the code reads are DERIVED from it (P5 of the pickup-reliability plan).
# Adding a member is one line here, not a hunt across two frozensets.

CUBE_KIND = 564  # the single kind-564 item; right-click OPENS it (T13/R67)
TOME_OF_IDENTIFY_KIND = 534  # R112 + T38 (72 charges)
TOME_OF_TOWN_PORTAL_KIND = 533  # T38 (64 charges)
# The scrolls the old RIGHT_CLICK_HAZARD comment promised "the moment a
# drill reads one" — their codes were in the T42 table the whole time. A
# loose Scroll of Identify is WORSE than the tome: it is junk, so the
# cleanse actually aims its ctrl+right-click at one, and a slipped modifier
# arms the identify cursor. (R112 with a cheaper item and no reason to keep.)
SCROLL_OF_TOWN_PORTAL_KIND = 544  # `tsc` (T42 code table)
SCROLL_OF_IDENTIFY_KIND = 545  # `isc` (T42 code table)


@dataclass(frozen=True)
class ItemException:
    """What an item's bare right-click does, and which gestures it forbids."""

    reason: str          # operator-facing, e.g. "right-click opens a portal"
    no_transfer: bool    # shift+right-click unsafe -> stash deposit skips it
    no_drop: bool        # ctrl+right-click unsafe -> the cleanse never drops it
    # Protected by DECISION, not only mechanics (the Cube, R172): even if a
    # future change made it movable, it must not become droppable/depositable
    # without a fresh user decision. Kept as data so a refactor cannot lose it.
    policy: bool = False


# Dungeon MAPS (PD2). T77 (2026-08-06) read ten off the floor and the code
# table shows the whole family shares the `t<dd>` form (30 kinds, 737-788,
# no non-map collision). Resolved from `config/item_codes.toml` by that
# pattern rather than hardcoded — R144 (kinds renumber per season; the code
# does not) — with kind 810 added explicitly because T77 saw it on the floor
# yet it is absent from the (T42-generated) code table. A map's right-click
# OPENS its dungeon, so both gestures are unsafe.
_MAP_CODE_RE = re.compile(r"^t\d\d$")
MAP_KIND_UNCODED = 810  # observed by T77; predates the current code table


def _load_map_kinds() -> frozenset[int]:
    """Map kinds resolved from the live code table by the `t<dd>` pattern.

    Reads `config/item_codes.toml` directly (stdlib only, no import cycle);
    any failure yields the empty set, so a missing/renamed table leaves maps
    UNPROTECTED rather than breaking every import of this module. Regenerate
    the table with the T42 drill after a season patch.
    """
    try:
        path = Path(__file__).resolve().parent.parent / "config" / "item_codes.toml"
        with open(path, "rb") as fh:
            codes = tomllib.load(fh).get("codes", {})
        return frozenset(
            int(kind) for kind, code in codes.items() if _MAP_CODE_RE.match(code)
        )
    except Exception:  # noqa: BLE001 - never break import over a config read
        return frozenset()


MAP_KINDS: frozenset[int] = _load_map_kinds() | {MAP_KIND_UNCODED}

# The registry. Cube + tomes reproduce today's exact membership (the Cube is
# no_transfer only — the cleanse's `is_movable` check catches it before the
# drop path, so leaving no_drop False keeps the derived hazard set identical
# to what shipped); scrolls and maps are the new members.
ITEM_EXCEPTIONS: dict[int, ItemException] = {
    CUBE_KIND: ItemException(
        "the Horadric Cube — right-click opens it",
        no_transfer=True, no_drop=False, policy=True,
    ),
    TOME_OF_TOWN_PORTAL_KIND: ItemException(
        "a Tome of Town Portal — right-click opens a portal",
        no_transfer=True, no_drop=True,
    ),
    TOME_OF_IDENTIFY_KIND: ItemException(
        "a Tome of Identify — right-click arms the identify cursor",
        no_transfer=True, no_drop=True,
    ),
    SCROLL_OF_TOWN_PORTAL_KIND: ItemException(
        "a Scroll of Town Portal — right-click opens a portal",
        no_transfer=True, no_drop=True,
    ),
    SCROLL_OF_IDENTIFY_KIND: ItemException(
        "a Scroll of Identify — right-click arms the identify cursor",
        no_transfer=True, no_drop=True,
    ),
    **{
        kind: ItemException(
            "a dungeon Map — right-click opens its dungeon",
            no_transfer=True, no_drop=True,
        )
        for kind in MAP_KINDS
    },
}

# The two sets the rest of the code reads, DERIVED so no call site changed.
# `UNMOVABLE_KINDS`: never shift+right-clicked (the stash deposit skips them,
# and `items.CarriedItem.is_movable` reads this). `RIGHT_CLICK_HAZARD_KINDS`:
# never ctrl+right-clicked — POTION_KINDS (a bare right-click drinks one,
# R131) plus every no_drop exception.
UNMOVABLE_KINDS = frozenset(
    kind for kind, exc in ITEM_EXCEPTIONS.items() if exc.no_transfer
)
RIGHT_CLICK_HAZARD_KINDS = frozenset(POTION_KINDS) | frozenset(
    kind for kind, exc in ITEM_EXCEPTIONS.items() if exc.no_drop
)


def unmovable_reason(kind: int) -> str:
    """Why this kind is never transferred, for operator-facing reports."""
    exc = ITEM_EXCEPTIONS.get(kind)
    return exc.reason if exc is not None else f"kind {kind}"

# --- Town NPCs and objects (Act 1, M5) --------------------------------------
#
# NPCs are type-1 units like monsters; kind (dwTxtFileNo) names them.
# kolbot sdk/types/sdk.d.ts:1608-1634 (sdk.npcs).
#
# VERIFIED by the T17 proximity drill (R68, 2026-07-30): the user stood
# beside each named NPC in turn and the nearest non-merc ally was read.
# Akara answered at distance 1 — standing on top of her — and the rest at
# 3-5 subtiles, with every rival candidate 14+ away. Unambiguous.
#
#     Akara 148   Kashya 150   Charsi 154   Gheed 147
#
# Worth keeping the history: R52 had recorded the same table as "verified"
# on much weaker evidence (kind 148 merely entered perception range during
# a walk toward Akara — anyone standing near her gives that signature), and
# when T12 then walked to Kashya it looked like the table's fault. It was
# not; see town.py's `_walk_guarded` for the real cause. The lesson is
# about the evidence, not the ids: a coincidence and a measurement can
# agree and still differ completely in what they license.
#
# Two facts from the same session that also hold:
# Deckard Cain is kind 265, and generic townsfolk (e.g. the kind-149 rogue
# guards) lack the friendly-alignment stat entirely, so they show up in the
# *monster* list in town — one more reason combat logic never runs there.
NPC_AKARA = 148
NPC_KASHYA = 150
NPC_CHARSI = 154  # the smith: repairs (T17-verified)
NPC_KINDS = {
    147: "gheed",
    148: "akara",
    150: "kashya",
    154: "charsi",
    155: "warriv",
    265: "cain",
}

# Objects (dwType==2): kolbot sdk/types/sdk.d.ts:1724 (A1Waypoint: 119),
# :1795 (Stash: 267). Verified live (R52, 2026-07-29): both named and
# positioned correctly in the first town dump.
OBJ_WAYPOINT_A1 = 119
OBJ_STASH = 267

# Objects a travel click must not land on, because clicking them INTERACTS
# (a panel opens and blocks all further input — R68/R111).
#
# An allowlist, not a denylist, and that direction was chosen the hard way.
# The navigator used to avoid EVERY object, which sounds safer and is not:
# most objects are decorative scenery that cannot be clicked at all, and in
# Cold Plains a cluster of 15 of them (kinds 160/161/162, packed into ~12
# subtiles) made the area unnavigable — every nudge off one landed the click
# on another until it came back to where the character already stood. That
# ended stage B's third attempt. Over-avoiding is not the safe direction; it
# is just a different failure, and the one we actually hit.
#
# The residual risk is an interactive object nobody has added here yet: the
# click activates it. In the field that is mostly harmless (a chest opens, a
# shrine fires) and the walk loop re-plans freely. The case worth watching is
# a town PORTAL, which would teleport the character — the bot does not make
# portals yet, and this list gets one before it does.
INTERACTIVE_OBJECT_KINDS = frozenset({OBJ_WAYPOINT_A1, OBJ_STASH})
OBJECT_KINDS = {
    OBJ_WAYPOINT_A1: "waypoint",
    OBJ_STASH: "stash",
}

# --- Area ids (classic D2 level numbering; act 1 surface) -------------------
# The trial run's whole route: town waypoint -> Cold Plains waypoint (R46 Q1).
# Treated as expectations, not facts, until a live read confirms them — the
# waypoint calibration drill reports the area it actually lands in, which is
# the same trust-nothing pattern as the difficulty guard.
AREA_ROGUE_ENCAMPMENT = 1
AREA_COLD_PLAINS = 3
# The Countess route (M6). Ids match the T52 survey's atlas file names
# (maps/<seed>/area-006 … area-025) — strong prior evidence, but still
# expectations until the P2 traversal drill reads each one live (R212 Q1).
AREA_BLACK_MARSH = 6  # live-verified: T69 read it on arrival (2026-08-05)
AREA_FORGOTTEN_TOWER = 20
AREA_TOWER_CELLAR_1 = 21
AREA_TOWER_CELLAR_2 = 22
AREA_TOWER_CELLAR_3 = 23
AREA_TOWER_CELLAR_4 = 24
AREA_TOWER_CELLAR_5 = 25
# The two cross-act calibration destinations (R212 Q2). Halls of Pain
# was READ on arrival in T69 — and note it contradicts classic-D2 area
# tables (which put it near 117), so the live read is the only number
# trusted. Arcane Sanctuary is still classic-lore 74, an EXPECTATION:
# the first bot trip proves or refutes it by arrival (a wrong id fails
# the travel loudly, which is the trust-nothing behavior we want).
AREA_ARCANE_SANCTUARY = 74  # expectation (classic lore); unverified live
AREA_HALLS_OF_PAIN = 123  # live-verified: T69 read it on arrival
AREA_NAMES = {
    AREA_ROGUE_ENCAMPMENT: "Rogue Encampment",
    AREA_COLD_PLAINS: "Cold Plains",
    AREA_BLACK_MARSH: "Black Marsh",
    AREA_FORGOTTEN_TOWER: "Forgotten Tower",
    AREA_TOWER_CELLAR_1: "Tower Cellar Level 1",
    AREA_TOWER_CELLAR_2: "Tower Cellar Level 2",
    AREA_TOWER_CELLAR_3: "Tower Cellar Level 3",
    AREA_TOWER_CELLAR_4: "Tower Cellar Level 4",
    AREA_TOWER_CELLAR_5: "Tower Cellar Level 5",
}

# --- UI state (BH Constants.h:65-89) ---------------------------------------
# P2 discovers the array these index into; the enum itself is stable.
UI_GAME = 0x00
UI_INVENTORY = 0x01
UI_CHARACTER = 0x02
UI_SKILLTREE = 0x04
UI_CHAT_CONSOLE = 0x05
UI_NPCMENU = 0x08
UI_ESCMENU_MAIN = 0x09
UI_AUTOMAP = 0x0A
UI_NPCSHOP = 0x0C  # verified live (T18): the trade/repair screen raises it
UI_QUEST = 0x0F
UI_QUEST_LOG = 0x11
UI_ESCMENU_EX = 0x13
UI_WPMENU = 0x14
UI_MINIPANEL = 0x15
UI_PARTY = 0x16
# kolbot sdk/types/sdk.d.ts:792 (sdk.uiflags.Stash: 0x19). Verified live
# (M5 P2 drill, 2026-07-30): the slot toggled 0->1->0 exactly with the
# stash screen — and raising ONLY itself (the inventory slot stayed 0).
UI_STASH = 0x19

UI_NAMES = {
    UI_GAME: "game",
    UI_INVENTORY: "inventory",
    UI_CHARACTER: "character",
    UI_SKILLTREE: "skilltree",
    UI_CHAT_CONSOLE: "chat_console",
    UI_NPCMENU: "npc_menu",
    UI_ESCMENU_MAIN: "esc_menu",
    UI_AUTOMAP: "automap",
    UI_NPCSHOP: "npc_shop",
    UI_QUEST: "quest",
    UI_QUEST_LOG: "quest_log",
    UI_ESCMENU_EX: "esc_menu_ex",
    UI_WPMENU: "waypoint_menu",
    UI_MINIPANEL: "minipanel",
    UI_PARTY: "party",
    UI_STASH: "stash",
}

# --- The chat line the client last displayed (M5P3 follow-up) ---------------
#
# NOT from BH, and not derivable from code: BH runs in-process and never
# needed to find the chat buffer, so there is no macro to cite and no
# function whose machine code points at it. This address was derived the
# remaining way — a content scan (T40, 2026-07-31, R120): the user typed a
# rare marker, the client's committed memory was searched for it, and the
# round was repeated with a SECOND marker. One module-relative address
# carried both, which is what separates a buffer from a coincidence.
#
# What it holds: the most recent chat line, NUL-terminated. "Most recent" is
# literal — the BOT's own messages land here too, so any listener must ignore
# its own. The bytes after the terminator are stale tail from a longer
# previous line; read to the NUL.
#
# THE ADDRESS IS NOT THE START OF THE LINE. It is a fixed address that
# usually coincides with it, and S1 (2026-07-31, R122) caught it not doing
# so: the bot read its own question back as "laude] or (C) leave it..." —
# the same text, two bytes to the left — and answered itself. D2 writes a
# colour escape (0xFF, then a code) in front of chat strings, and when that
# prefix's length differs, everything read from here shifts with it. The
# same drift explains T41's first run dying on a 0xFF byte at this address.
#
# Consequences for any consumer, all of them live in chatread.py:
#   * a read can be short at the FRONT, so a user's "red" could arrive "ed";
#   * identifying the bot's own voice cannot depend on the prefix sitting at
#     position 0 (chatread matches against what was recently said instead);
#   * this is a WINDOW onto the last line, not a string pointer, and it will
#     stay that way until the real message list is found (T42).
#
# Verified: both markers, same address, one live client. NOT yet verified
# across a client restart — module-relative offsets should survive one, but
# "should" is what this project measures instead of assuming. T41 re-derives
# the address by scan before using it, so a moved buffer fails loudly.
#
# Two siblings found by the same scan, kept for the record and unused:
#   D2Client.dll+0x11EC80  the same text as wchar_t
#   heap 0x19CFA2          the RENDERED line — colour codes and the sender
#                          name included, so it distinguishes speakers — but
#                          a heap address, so not durable without a chain
CHAT_LAST_LINE = 0x1234D3
CHAT_LAST_LINE_WIDE = 0x11EC80
CHAT_LAST_LINE_MAX = 160  # chat.py splits at 100 chars; this is slack, not a limit

# --- Player unit modes and towns (M4 safety monitor) -------------------------

# Player UNIT_MODE values (kolbot sdk/types/sdk.d.ts:1550, sdk.player.mode):
# 0 = Death (the dying animation), 17 = Dead. Either means the character is
# gone; the safety monitor treats both as dead (false positives acceptable,
# false negatives not).
PLAYER_MODE_DEATH = 0
PLAYER_MODE_DEAD = 17
# 10 = SC, the cast-spell animation. Verified live by T48 (2026-08-01) on
# this character: three bone-armor casts in town read 5 (town neutral) ->
# 10 at 110-125 ms after the click -> 5 again at 610-640 ms. That is the
# whole cast, measured, and it is what `GameActionExecutor` waits out
# before sending the next CLICK — by reading this, not by sleeping a
# guessed number (review 002).
PLAYER_MODE_CASTING = 10

# Monster UNIT_MODE values (kolbot sdk/types/sdk.d.ts:1590-1602, npcs.mode —
# "same as monsters"): 0 = Death (dying animation), 12 = Dead. A dead
# monster unit is a *corpse* — desecrate makes them, revive consumes them.
# Mode 12 verified live (R52, 2026-07-29): Rogue Encampment's ambient
# corpses all read mode 12. Mode 0 is a transient animation frame, kept on
# the dual-source citation.
MONSTER_MODE_DEATH = 0
MONSTER_MODE_DEAD = 12

# Town area ids (kolbot sdk/types/sdk.d.ts sdk.areas: RogueEncampment:1,
# LutGholein:40, KurastDocktown:75, PandemoniumFortress:103, Harrogath:109).
# Towns have no hostile monsters; kolbot suppresses chicken there and so do
# we (configurable, for the zero-risk live chicken test).
TOWN_AREAS = frozenset({1, 40, 75, 103, 109})

# --- D2Win: the out-of-game control list (M4) --------------------------------
#
# The menus (main menu, char select, difficulty popup, error popups) are not
# panels in the in-game UI array — they are a linked list of *controls*
# (buttons, textboxes, images) owned by D2Win.dll. Reading that list is how
# the bot knows which menu screen is up and where its buttons are; it is the
# same structure D2BS's getLocation()/clickControl built kolbot's whole
# out-of-game layer on.
#
# Offsets below are relative to D2Win.dll's runtime base (NOT D2Client's).

# D2Ptrs.h:624  VARPTR(D2WIN, FirstControl, Control*, 0x214A0, 0x8DB34)
# 1.13c first, as with every BH macro. Null when no menu is up (in a game).
D2WIN_FIRST_CONTROL = 0x214A0

# Control struct: BH CommonStructs.h:567-585 (primary, PD2's own header) —
# cross-checked against noah-/d2bs D2Structs.h:132-168, which agrees on every
# field we read. Menu coordinates are in the 800x600 menu render space;
# dwPosY is the control's BOTTOM edge (D2BS clicks at y - height/2).
CONTROL_TYPE = 0x00  # dwType, see CONTROL_TYPE_* below
CONTROL_STATE = 0x08  # dwState: 5 enabled, 4 disabled, <4 not visible
CONTROL_POS_X = 0x0C  # dwPosX, left edge
CONTROL_POS_Y = 0x10  # dwPosY, BOTTOM edge
CONTROL_SIZE_X = 0x14  # dwSizeX
CONTROL_SIZE_Y = 0x18  # dwSizeY
CONTROL_NEXT = 0x3C  # Control* pNext

# Button text: BH CommonStructs.h:665 (struct Button : Control, wchar_t
# wText[256] at 0x64). d2bs's union layout lands on the same 0x64 by
# arithmetic (0x5C + two DWORDs), though its inline comment miscounts it as
# 0x6C — the BH subtype math is the one we trust.
CONTROL_BUTTON_TEXT = 0x64
CONTROL_BUTTON_TEXT_CHARS = 256

# Control types, from BH CommonStructs.h's subtype comments
# ("struct EditBox : Control ... CONTROL_EDITBOX: 1", etc.)
CONTROL_TYPE_EDITBOX = 1
CONTROL_TYPE_IMAGE = 2
CONTROL_TYPE_ANIMIMAGE = 3
CONTROL_TYPE_TEXTBOX = 4
CONTROL_TYPE_SCROLLBAR = 5
CONTROL_TYPE_BUTTON = 6
CONTROL_TYPE_LIST = 7

CONTROL_TYPE_NAMES = {
    CONTROL_TYPE_EDITBOX: "editbox",
    CONTROL_TYPE_IMAGE: "image",
    CONTROL_TYPE_ANIMIMAGE: "animimage",
    CONTROL_TYPE_TEXTBOX: "textbox",
    CONTROL_TYPE_SCROLLBAR: "scrollbar",
    CONTROL_TYPE_BUTTON: "button",
    CONTROL_TYPE_LIST: "list",
}

# The menus draw in a fixed 800x600 space regardless of window size (the
# window scale factor is measured live, navdemo-style, before clicks use it).
MENU_WIDTH = 800
MENU_HEIGHT = 600
