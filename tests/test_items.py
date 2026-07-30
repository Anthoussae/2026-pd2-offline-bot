"""Tests for carried-item enumeration and classification (items.py).

The fakes wire the player's Inventory chain exactly as the client keeps it:
UnitAny.pInventory -> pFirstItem -> ItemData.pNextInvItem. Classification is
mode-first (the field that told the truth in R17 when the location byte did
not), so every fake writes mode, GameLocation and NodePage together the way
the live client pairs them.
"""

from pd2bot import offsets
from pd2bot.items import MAX_CARRIED_ITEMS, read_carried_items
from tests.conftest import CLIENT_BASE, FakeMemory, FakeSession, u32

PLAYER = 0x0C000000
INVENTORY = 0x0C001000


def build_world():
    mem = FakeMemory()
    mem.write(CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(PLAYER))
    mem.write_fields(
        PLAYER,
        {
            offsets.UNIT_TYPE: u32(offsets.UNIT_TYPE_PLAYER),
            offsets.UNIT_INVENTORY: u32(INVENTORY),
        },
    )
    mem.write_fields(
        INVENTORY,
        {
            offsets.INVENTORY_FIRST_ITEM: u32(0),
            offsets.INVENTORY_CURSOR_ITEM: u32(0),
        },
    )
    return mem


def add_carried(
    mem,
    address,
    unit_id,
    kind,
    *,
    mode,
    game_location=0,
    node_page=0,
    pos=(0, 0),
    quality=2,
):
    path, data = address + 0x100, address + 0x200
    mem.write_fields(
        address,
        {
            offsets.UNIT_TYPE: u32(offsets.UNIT_TYPE_ITEM),
            offsets.UNIT_TXT_FILE_NO: u32(kind),
            offsets.UNIT_ID: u32(unit_id),
            offsets.UNIT_MODE: u32(mode),
            offsets.UNIT_DATA: u32(data),
            offsets.UNIT_PATH: u32(path),
        },
    )
    mem.write_fields(
        data,
        {
            offsets.ITEM_QUALITY: u32(quality),
            offsets.ITEM_LEVEL: u32(33),
            offsets.ITEM_GAME_LOCATION: bytes([game_location]),
            offsets.ITEM_NODE_PAGE: bytes([node_page]),
            offsets.ITEM_NEXT_INV: u32(0),
        },
    )
    mem.write_fields(
        path, {offsets.ITEM_PATH_X: u32(pos[0]), offsets.ITEM_PATH_Y: u32(pos[1])}
    )
    return address


def chain(mem, *addresses):
    """Link items through ItemData.pNextInvItem and set the chain head."""
    mem.regions[INVENTORY][
        offsets.INVENTORY_FIRST_ITEM : offsets.INVENTORY_FIRST_ITEM + 4
    ] = u32(addresses[0])
    for current, nxt in zip(addresses, addresses[1:], strict=False):
        data = current + 0x200
        mem.regions[data][offsets.ITEM_NEXT_INV : offsets.ITEM_NEXT_INV + 4] = u32(nxt)


def build_typical():
    """A belt potion, an inventory ring, a stashed rune, an equipped dagger."""
    mem = build_world()
    belt_potion = add_carried(
        mem, 0x0C010000, 1, 610,  # a mana potion (kind proven by effect, R54)
        mode=offsets.ITEM_MODE_IN_BELT, node_page=offsets.NODE_BELT, pos=(6, 0),
    )
    ring = add_carried(
        mem, 0x0C020000, 2, 522,
        mode=offsets.ITEM_MODE_IN_STORAGE,
        game_location=offsets.STORAGE_INVENTORY,
        node_page=offsets.NODE_STORAGE, pos=(5, 0), quality=6,
    )
    rune = add_carried(
        mem, 0x0C030000, 3, 620,
        mode=offsets.ITEM_MODE_IN_STORAGE,
        game_location=offsets.STORAGE_STASH,
        node_page=offsets.NODE_STORAGE, pos=(2, 3),
    )
    dagger = add_carried(
        mem, 0x0C040000, 4, 30,
        mode=offsets.ITEM_MODE_EQUIPPED, node_page=offsets.NODE_EQUIPPED,
    )
    chain(mem, belt_potion, ring, rune, dagger)
    return FakeSession(mem)


def test_walks_the_inventory_chain_and_classifies_containers():
    carried = read_carried_items(build_typical())
    assert len(carried.items) == 4
    by_id = {i.unit_id: i for i in carried.items}
    assert by_id[1].container == "belt"
    assert by_id[2].container == "inventory"
    assert by_id[3].container == "stash"
    assert by_id[4].container == "equipped"
    assert carried.skipped == 0


def test_belt_slot_and_column_from_path_x():
    """Belt slot index lives in the path x; column = slot % 4 (kolbot's
    Town.checkColumns arithmetic). Slot 6 is column 2, row 1."""
    carried = read_carried_items(build_typical())
    potion = next(i for i in carried.items if i.unit_id == 1)
    assert potion.belt_slot == 6
    assert potion.belt_column == 2
    ring = next(i for i in carried.items if i.unit_id == 2)
    assert ring.belt_slot is None  # not in the belt: no slot, no column
    assert ring.belt_column is None


def test_belt_counts_by_column_and_rejuv_total():
    mem = build_world()
    col0 = add_carried(mem, 0x0C010000, 1, 610, mode=2, pos=(0, 0))
    col0b = add_carried(mem, 0x0C020000, 2, 610, mode=2, pos=(4, 0))
    rejuv = add_carried(mem, 0x0C030000, 3, 531, mode=2, pos=(1, 0))
    chain(mem, col0, col0b, rejuv)

    carried = read_carried_items(FakeSession(mem))
    assert carried.belt_count(0) == 2
    assert carried.belt_count(1) == 1
    assert carried.belt_count(2) == 0
    assert carried.belt_rejuv_count == 1


def test_potion_kind_helpers():
    carried = read_carried_items(build_typical())
    potion = next(i for i in carried.items if i.unit_id == 1)
    assert potion.is_mana_potion and not potion.is_rejuv_potion
    assert potion.potion_name == "mana_610"
    ring = next(i for i in carried.items if i.unit_id == 2)
    assert ring.potion_name is None


def test_outside_a_game_reads_empty():
    mem = FakeMemory()
    mem.write(CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(0))
    carried = read_carried_items(FakeSession(mem))
    assert carried.items == () and carried.skipped == 0


def test_an_unreadable_item_is_skipped_and_ends_nothing():
    """A freed item mid-chain must not lose the ones already read."""
    session = build_typical()
    # Corrupt the ring's data pointer: unreadable item, chain continues via
    # the walk only if the *next* link is reachable — it is not (the link
    # lives in the dead data), so the walk ends; the belt potion survives.
    session.memory.write_fields(0x0C020000, {offsets.UNIT_DATA: u32(0xDD000000)})
    carried = read_carried_items(session)
    assert [i.unit_id for i in carried.items] == [1]


def test_a_looped_chain_terminates():
    session = build_typical()
    dagger_data = 0x0C040000 + 0x200
    session.memory.regions[dagger_data][
        offsets.ITEM_NEXT_INV : offsets.ITEM_NEXT_INV + 4
    ] = u32(0x0C010000)  # tail points back at the head
    carried = read_carried_items(session)
    assert len(carried.items) == MAX_CARRIED_ITEMS


def test_cursor_item_is_read_from_its_own_pointer_not_the_chain():
    """An item held on the cursor LEAVES the inventory chain (live fact,
    R52 drill C) — it is reachable only via Inventory.pCursorItem. Stashing
    logic (P3) must see it or a mid-drag read would claim the item vanished."""
    mem = build_world()
    held = add_carried(mem, 0x0C050000, 9, 522, mode=offsets.ITEM_MODE_ON_CURSOR,
                       node_page=offsets.NODE_CURSOR)
    # Deliberately NOT chained: only the cursor pointer knows about it.
    mem.regions[INVENTORY][
        offsets.INVENTORY_CURSOR_ITEM : offsets.INVENTORY_CURSOR_ITEM + 4
    ] = u32(held)
    carried = read_carried_items(FakeSession(mem))
    assert carried.cursor_item is not None
    assert carried.cursor_item.unit_id == 9
    assert carried.cursor_item.container == "cursor"


def test_charm_space_is_separated_from_the_usable_grid():
    """PD2's charm inventory shares the container and every ItemData byte
    with ordinary inventory (live probe, R60) — only the cell coordinate
    tells them apart. A consumer that trusted the container alone would
    walk two dozen untouchable items on this character."""
    mem = build_world()
    usable = add_carried(
        mem, 0x0C060000, 1, 610,
        mode=offsets.ITEM_MODE_IN_STORAGE,
        game_location=offsets.STORAGE_INVENTORY,
        node_page=offsets.NODE_STORAGE, pos=(9, 3),  # last usable cell
    )
    charm = add_carried(
        mem, 0x0C070000, 2, 610,
        mode=offsets.ITEM_MODE_IN_STORAGE,
        game_location=offsets.STORAGE_INVENTORY,
        node_page=offsets.NODE_STORAGE, pos=(0, 4),  # first charm row
    )
    chain(mem, usable, charm)

    carried = read_carried_items(FakeSession(mem))
    assert [i.unit_id for i in carried.main_inventory] == [1]
    assert [i.unit_id for i in carried.charm_inventory] == [2]
    # The raw container view still shows both — diagnostics need the truth.
    assert len(carried.inventory) == 2
    assert carried.items[0].in_main_inventory and not carried.items[0].in_charm_inventory
    assert carried.items[1].in_charm_inventory and not carried.items[1].in_main_inventory


def test_stash_items_are_in_neither_inventory_view():
    mem = build_world()
    stashed = add_carried(
        mem, 0x0C080000, 3, 620,
        mode=offsets.ITEM_MODE_IN_STORAGE,
        game_location=offsets.STORAGE_STASH,
        node_page=offsets.NODE_STORAGE, pos=(0, 0),
    )
    chain(mem, stashed)
    carried = read_carried_items(FakeSession(mem))
    assert carried.main_inventory == () and carried.charm_inventory == ()
    assert len(carried.stash) == 1
