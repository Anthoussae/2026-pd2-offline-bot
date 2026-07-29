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
# ITEM_LOCATION (0x45, per BH's header) is NOT trusted: the live check
# (2026-07-28, instruction log R17) showed a carried item reading 0xFF
# there — it appeared as a ground item at its inventory grid slot (5, 0).
# On-the-floor detection uses the unit's mode instead; see below.
ITEM_LOCATION = 0x45
ITEM_LOCATION_NONE = 0xFF

# Item unit modes (UNIT_MODE for dwType==4), kolbot sdk `sdk.items.mode`:
# inStorage=0, equipped=1, inBelt=2, onGround=3, onCursor=4, dropping=5,
# socketed=6. "On the floor" = onGround or mid-drop. Verified live (R17/R19):
# mode correctly distinguishes carried from dropped where 0x45 did not.
ITEM_MODE_ON_GROUND = 3
ITEM_MODE_DROPPING = 5

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

# --- Player unit modes and towns (M4 safety monitor) -------------------------

# Player UNIT_MODE values (kolbot sdk/types/sdk.d.ts:1550, sdk.player.mode):
# 0 = Death (the dying animation), 17 = Dead. Either means the character is
# gone; the safety monitor treats both as dead (false positives acceptable,
# false negatives not).
PLAYER_MODE_DEATH = 0
PLAYER_MODE_DEAD = 17

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
