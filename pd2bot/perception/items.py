"""Carried items: what the character holds — belt, inventory, stash, body.

Ground items are `units.GroundItem`; this module covers everything with an
owner. Enumeration walks the player's own Inventory chain (UnitAny.pInventory
-> pFirstItem -> ItemData.pNextInvItem), which lists exactly the items the
character owns — no locality filtering, no guessing about whose stash a
stored item belongs to.

Classification leans on the unit MODE first (the field proven live in R17/R19
when the ItemData location byte lied), with GameLocation telling the storage
containers apart and NodePage read alongside as the cross-check BH's own
header calls "the most reliable by far". The M5 P1 potion-shuffle drill
verifies all three against the screen before anything downstream trusts this
module.

Belt geometry: a belt item's path x is its slot index; column = slot % 4.
Column meaning is the user's layout (R47.6): 1 healing, 2 rejuvenation,
3 mana, 4 healing — but that mapping lives in config, not here; this module
reports raw columns.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace

from pd2bot import offsets
from pd2bot.perception.memory import GameSession
from pd2bot.perception.units import player_unit, read_socket_count

# The bound exists so a torn chain cannot loop forever — it must sit far
# ABOVE any legitimate total, because the walk hitting it truncates the
# read. The original 512 assumed "a character can own at most ~200 items";
# PD2's expanded stash rides the same chain and falsified that on
# 2026-08-13: the stash had grown past 512, the walk silently dropped
# everything after it — the belt, the worn gear, most of the inventory —
# and the restock station bought ~30 potions against a hallucinated-empty
# belt (`repair: 0 worn item(s) checked` was the same lie). A read that
# hits this bound now says so (`CarriedItems.truncated`), and the town
# preamble refuses to run on one.
MAX_CARRIED_ITEMS = 4096


@dataclass(frozen=True)
class CarriedItem:
    unit_id: int
    kind: int  # dwTxtFileNo — which item type
    quality: int
    mode: int  # ITEM_MODE_*: storage/equipped/belt/cursor
    game_location: int  # STORAGE_*: which container, for stored items
    node_page: int  # NODE_*: the cross-check byte
    position: tuple[int, int]  # grid cell for stored items, (slot, 0) in belt
    item_level: int
    # Sockets, for main-inventory items only and only when the caller asked
    # (`read_carried_items(with_sockets=True)`); None everywhere else means
    # "not read", never "none". The inventory cleanse needs it: without it a
    # socket-conditioned keep rule cannot be evaluated against a CARRIED
    # item, and the cleanse evaluates permissively — so every necro head and
    # archon plate was kept and stashed regardless of its sockets (R132).
    sockets: int | None = None

    @property
    def container(self) -> str:
        """Where this item lives, as behavior code should reason about it."""
        if self.mode == offsets.ITEM_MODE_IN_BELT:
            return "belt"
        if self.mode == offsets.ITEM_MODE_EQUIPPED:
            return "equipped"
        if self.mode == offsets.ITEM_MODE_ON_CURSOR:
            return "cursor"
        if self.mode == offsets.ITEM_MODE_SOCKETED:
            return "socketed"
        if self.mode == offsets.ITEM_MODE_IN_STORAGE:
            return offsets.STORAGE_NAMES.get(self.game_location, f"storage_{self.game_location}")
        return f"mode_{self.mode}"

    @property
    def belt_slot(self) -> int | None:
        """Slot index 0..15 while in the belt, else None."""
        return self.position[0] if self.mode == offsets.ITEM_MODE_IN_BELT else None

    @property
    def in_charm_inventory(self) -> bool:
        """Sitting in PD2's charm space — same container, off limits to us.

        Charm slots are indistinguishable from ordinary inventory in every
        byte we read (R60): only the cell coordinate tells them apart.
        """
        return (
            self.container == "inventory"
            and self.position[1] >= offsets.INVENTORY_ROWS
        )

    @property
    def in_main_inventory(self) -> bool:
        """In the usable grid — the only inventory the bot may touch."""
        x, y = self.position
        return (
            self.container == "inventory"
            and 0 <= x < offsets.INVENTORY_COLS
            and 0 <= y < offsets.INVENTORY_ROWS
        )

    @property
    def belt_column(self) -> int | None:
        """Column 0..3 (the 1..4 drink keys, zero-based) while in the belt."""
        slot = self.belt_slot
        return slot % offsets.BELT_COLUMNS if slot is not None else None

    @property
    def is_movable(self) -> bool:
        """False for items the transfer gesture does not work on — the
        Horadric Cube above all, whose right-click opens it instead."""
        return self.kind not in offsets.UNMOVABLE_KINDS

    @property
    def potion_name(self) -> str | None:
        return offsets.POTION_KINDS.get(self.kind)

    @property
    def is_healing_potion(self) -> bool:
        return self.kind in offsets.HEALING_POTION_KINDS

    @property
    def is_mana_potion(self) -> bool:
        return self.kind in offsets.MANA_POTION_KINDS

    @property
    def is_rejuv_potion(self) -> bool:
        return self.kind in offsets.REJUV_POTION_KINDS

    @property
    def potion_type(self) -> str | None:
        """"healing" / "mana" / "rejuv", or None for everything else —
        including FOREIGN potions (antidote, thawing, stamina), which can
        sit in the belt and block a column but serve no rung."""
        if self.is_healing_potion:
            return "healing"
        if self.is_mana_potion:
            return "mana"
        if self.is_rejuv_potion:
            return "rejuv"
        return None


@dataclass(frozen=True)
class CarriedItems:
    """One coherent read of everything the character owns."""

    items: tuple[CarriedItem, ...]
    skipped: int  # chain entries that could not be read; nonzero is notable
    # The walk hit MAX_CARRIED_ITEMS and stopped: everything past the cap
    # is MISSING from `items`, so "absent" answers from this read are
    # untrustworthy. Consumers that act on absence (the restock, the
    # deposit, the cleanse) must refuse a truncated read.
    truncated: bool = False

    def in_container(self, name: str) -> tuple[CarriedItem, ...]:
        return tuple(i for i in self.items if i.container == name)

    @property
    def belt(self) -> tuple[CarriedItem, ...]:
        return self.in_container("belt")

    @property
    def inventory(self) -> tuple[CarriedItem, ...]:
        """Everything in the inventory container — INCLUDING charm space.

        Behaviour code almost always wants `main_inventory` instead; this
        stays whole so diagnostics can see the real container.
        """
        return self.in_container("inventory")

    @property
    def main_inventory(self) -> tuple[CarriedItem, ...]:
        """The usable grid only. What deposits, refills and pickups act on."""
        return tuple(i for i in self.items if i.in_main_inventory)

    @property
    def charm_inventory(self) -> tuple[CarriedItem, ...]:
        """PD2's locked charm space. Visible, never touched."""
        return tuple(i for i in self.items if i.in_charm_inventory)

    @property
    def stash(self) -> tuple[CarriedItem, ...]:
        return self.in_container("stash")

    @property
    def cursor_item(self) -> CarriedItem | None:
        held = self.in_container("cursor")
        return held[0] if held else None

    def belt_count(self, column: int) -> int:
        """How many potions sit in one belt column (0..3)."""
        return sum(1 for i in self.belt if i.belt_column == column)

    @property
    def belt_rejuv_count(self) -> int:
        return sum(1 for i in self.belt if i.is_rejuv_potion)


def _iter_inventory_units(session: GameSession, owner: int) -> Iterator[int]:
    """Walk ANY unit's inventory chain, bounded against torn reads.

    The player's items and a vendor's stock live in the same structure
    hung off the owning unit — the player for the inventory/belt, an NPC
    for its shop (R241). `_iter_carried_units` is this pointed at the
    player; `read_vendor_stock` points it at the NPC.
    """
    inventory = session.ptr(owner + offsets.UNIT_INVENTORY)
    if inventory is None:
        return
    try:
        unit = session.ptr(inventory + offsets.INVENTORY_FIRST_ITEM)
    except Exception:
        return
    seen = 0
    while unit is not None and seen < MAX_CARRIED_ITEMS:
        yield unit
        seen += 1
        try:
            data = session.ptr(unit + offsets.UNIT_DATA)
            unit = session.ptr(data + offsets.ITEM_NEXT_INV) if data else None
        except Exception:
            return  # a freed item mid-walk ends the walk, same as units.py


def _iter_carried_units(session: GameSession) -> Iterator[int]:
    """The player's own inventory chain (the common case)."""
    player = player_unit(session)
    if player is None:
        return
    yield from _iter_inventory_units(session, player)


def _read_carried(session: GameSession, unit: int) -> CarriedItem | None:
    data = session.ptr(unit + offsets.UNIT_DATA)
    path = session.ptr(unit + offsets.UNIT_PATH)
    if data is None or path is None:
        return None
    return CarriedItem(
        unit_id=session.u32(unit + offsets.UNIT_ID),
        kind=session.u32(unit + offsets.UNIT_TXT_FILE_NO),
        quality=session.u32(data + offsets.ITEM_QUALITY),
        mode=session.u32(unit + offsets.UNIT_MODE),
        game_location=session.u8(data + offsets.ITEM_GAME_LOCATION),
        node_page=session.u8(data + offsets.ITEM_NODE_PAGE),
        position=(
            session.u32(path + offsets.ITEM_PATH_X),
            session.u32(path + offsets.ITEM_PATH_Y),
        ),
        item_level=session.u32(data + offsets.ITEM_LEVEL),
    )


@dataclass(frozen=True)
class Durability:
    """One worn item's wear. `missing` is what a repair would restore."""

    unit_id: int
    kind: int
    current: int
    maximum: int

    @property
    def missing(self) -> int:
        return max(0, self.maximum - self.current)

    @property
    def fraction(self) -> float:
        return self.current / self.maximum if self.maximum else 1.0


def read_equipped_durability(session: GameSession) -> tuple[Durability, ...]:
    """Wear on every worn item that can wear.

    Separate from `read_carried_items` on purpose: durability lives in each
    item's stat list, and this character carries 400+ items, so folding a
    stat read into the general enumeration would tax every snapshot to
    serve one step that runs once a game. Items with no maximum (rings,
    amulets, charms) are omitted — absence of the stat means indestructible
    or not applicable, never broken.
    """
    from pd2bot.perception.units import read_stats  # local: units imports nothing here

    worn: list[Durability] = []
    for unit in _iter_carried_units(session):
        try:
            if session.u32(unit + offsets.UNIT_MODE) != offsets.ITEM_MODE_EQUIPPED:
                continue
            stats = read_stats(session, unit)
            maximum = stats.get(offsets.STAT_MAX_DURABILITY, 0)
            if maximum <= 0:
                continue
            worn.append(
                Durability(
                    unit_id=session.u32(unit + offsets.UNIT_ID),
                    kind=session.u32(unit + offsets.UNIT_TXT_FILE_NO),
                    current=stats.get(offsets.STAT_DURABILITY, 0),
                    maximum=maximum,
                )
            )
        except Exception:
            continue  # a torn item mid-read is not worth failing a repair over
    return tuple(worn)


def _cursor_unit(session: GameSession) -> int | None:
    """The item held on the cursor, which is NOT in the inventory chain.

    Live fact (R52 drill C): mid-drag an item vanishes from the pFirstItem
    chain entirely and is reachable only through Inventory.pCursorItem.
    Missing it would make a mid-drag read claim the item ceased to exist.
    """
    player = player_unit(session)
    if player is None:
        return None
    inventory = session.ptr(player + offsets.UNIT_INVENTORY)
    if inventory is None:
        return None
    try:
        return session.ptr(inventory + offsets.INVENTORY_CURSOR_ITEM)
    except Exception:
        return None


def read_carried_items(
    session: GameSession, *, with_sockets: bool = True
) -> CarriedItems:
    """Everything the character owns, or an empty read outside a game.

    `with_sockets` adds one stat read per MAIN-INVENTORY item (never the
    stash, the belt or worn gear), which is what the cleanse needs to judge
    a socket-conditioned rule. It defaults to True because the failure it
    prevents is silent: a caller who forgets it gets items whose sockets
    read None, and None is "keep" to the permissive whitelist. The bound is
    the grid — 40 items — but that is still 40 reads, so a tick-rate caller
    that only wants the belt (the reflex ladder) should pass False and say
    why at the wiring site.
    """
    items: list[CarriedItem] = []
    skipped = 0
    walked = 0
    seen: set[int] = set()
    for unit in _iter_carried_units(session):
        walked += 1
        try:
            item = _read_carried(session, unit)
        except Exception:
            item = None
        if item is not None and with_sockets and item.in_main_inventory:
            # Its OWN try: a socket read that fails means one unknown field,
            # not a missing item. Folding it into the read above would let a
            # torn stat list delete an item from the inventory entirely —
            # and this list is what the deposit and the cleanse iterate, so
            # an item that vanishes from it is an item nothing handles.
            try:
                item = replace(item, sockets=read_socket_count(session, unit))
            except Exception:
                pass
        if item is None:
            skipped += 1
            continue
        seen.add(item.unit_id)
        items.append(item)

    cursor = _cursor_unit(session)
    if cursor is not None:
        try:
            held = _read_carried(session, cursor)
        except Exception:
            held = None
        if held is not None and held.unit_id not in seen:
            items.append(held)
        elif held is None:
            skipped += 1

    return CarriedItems(
        items=tuple(items),
        skipped=skipped,
        # At the cap, the chain may continue past where the walk stopped
        # (a cycle also lands here — indistinguishable, equally untrusted).
        truncated=walked >= MAX_CARRIED_ITEMS,
    )


# Deliberately absent: free_inventory_cells. Computing true grid occupancy
# needs each item's width/height, which live in the ItemsTxt data table —
# a D2COMMON structure this module has no verified offsets for. P3's stash
# guardrail verifies deposits by watching this list shrink instead
# (plan: docs/archive/plans/2026-07-29-m5-trial-run/01-perception-extensions.md).


@dataclass(frozen=True)
class VendorPotion:
    """One potion a vendor is selling: its type and its grid cell.

    Cell is READ FRESH each visit (R241 Q4 — the user's point): the
    shop's layout is not assumed stable, so the buy chore must aim at
    where this potion actually is on this occasion. The cell is the
    click's INPUT; the panel's grid geometry (origin + cell size) is the
    one thing calibrated, in T85.
    """

    unit_id: int
    kind: int
    potion_type: str  # "healing" / "mana" / "rejuv"
    cell: tuple[int, int]  # (column, row) within the shop grid


def read_vendor_stock(session: GameSession, npc_unit: int) -> list[VendorPotion]:
    """The potions a vendor NPC currently sells, with their grid cells.

    Reads the NPC's own inventory chain (the same structure the player's
    items hang off). Non-potions are ignored — this chore only buys
    potions. Best-effort per item: a torn read drops that one, never the
    whole stock.
    """
    from pd2bot.pickit import potion_type_of

    stock: list[VendorPotion] = []
    for unit in _iter_inventory_units(session, npc_unit):
        try:
            item = _read_carried(session, unit)
        except Exception:
            item = None
        if item is None:
            continue
        ptype = potion_type_of(item)
        if ptype is None:
            continue
        stock.append(
            VendorPotion(
                unit_id=item.unit_id,
                kind=item.kind,
                potion_type=ptype,
                cell=item.position,  # grid (col, row) for a stored item
            )
        )
    return stock
