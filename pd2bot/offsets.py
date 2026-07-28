"""Every memory offset and game constant used by the bot, in one place.

Source of truth: Project-Diablo-2/BH @ main (the PD2 team's own open-source
maphack), fetched 2026-07-28. Each entry cites the BH file and line it came
from so it can be re-verified after a season patch.

PD2's client is Diablo II **1.13c**. BH's VARPTR/FUNCPTR macros list offsets
per version with 1.13c first (D2Ptrs.h:82-89), so the *first* address in each
macro is ours.

Do not put a magic offset anywhere else in this codebase. Values marked
"verified live" were confirmed against the running client during M1/M2.
"""

# --- module-relative pointers (add to D2Client.dll's runtime base) ----------

# D2Ptrs.h:235  VARPTR(D2CLIENT, PlayerUnit, UnitAny*, 0x11BBFC, 0x11D050)
# Verified live (M1): NULL in the menus, valid UnitAny* while in a game.
PLAYER_UNIT_PTR = 0x11BBFC

# D2Ptrs.h:156  FUNCPTR(D2CLIENT, GetUiVar_I, ..., 0xBE400, 0x17C50)
# A function, not a variable — P2 parses its code to locate the UI array.
GET_UI_VAR_FN = 0xBE400

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

# --- Path (D2Structs.h:396) — for units that move --------------------------

PATH_X = 0x02  # xPos, WORD (world coords)
PATH_Y = 0x06  # yPos, WORD
PATH_ROOM1 = 0x1C  # Room1*

# --- ItemPath (D2Structs.h:421) — for units that don't ---------------------

ITEM_PATH_X = 0x0C  # dwPosX, DWORD
ITEM_PATH_Y = 0x10  # dwPosY, DWORD

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
STAT_GOLD = 14
STAT_GOLD_BANK = 15

# Only these are stored fixed-point and need `>> 8`. Applying the shift to the
# others (level, attributes, gold, experience) silently zeroes them.
FIXED_POINT_STATS = frozenset(
    {STAT_HP, STAT_MAX_HP, STAT_MANA, STAT_MAX_MANA, STAT_STAMINA, STAT_MAX_STAMINA}
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

# --- Room2 (D2Structs.h:333) — static/preset room layer --------------------

ROOM2_ROOM1 = 0x30
ROOM2_LEVEL = 0x58  # Level*

# --- Level (D2Structs.h:317) -----------------------------------------------

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

# --- ItemData (D2Structs.h:510) --------------------------------------------

ITEM_QUALITY = 0x00  # dwQuality
ITEM_FLAGS = 0x0C  # dwItemFlags
ITEM_LEVEL = 0x2C  # dwItemLevel
ITEM_LOCATION = 0x45  # ItemLocation; 0xFF when not in an inventory slot
ITEM_LOCATION_NONE = 0xFF

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
UI_NPCSHOP = 0x0C
UI_QUEST = 0x0F
UI_QUEST_LOG = 0x11
UI_ESCMENU_EX = 0x13
UI_WPMENU = 0x14
UI_MINIPANEL = 0x15
UI_PARTY = 0x16

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
}
