"""Reading a vendor's stock (R241): the potions an NPC sells, with the
grid cell each sits at RIGHT NOW — the read the buy chore aims by.
"""

from pd2bot import offsets
from pd2bot.perception.items import read_vendor_stock
from tests.conftest import FakeMemory, FakeSession, u32
from tests.perception.test_items import add_carried

NPC = 0x0D000000
NPC_INVENTORY = 0x0D000F00


def vendor_world(*items):
    """An NPC unit owning `items` — (unit_id, kind, cell) tuples."""
    mem = FakeMemory()
    mem.write_fields(NPC, {offsets.UNIT_INVENTORY: u32(NPC_INVENTORY)})
    mem.write_fields(NPC_INVENTORY, {offsets.INVENTORY_FIRST_ITEM: u32(0)})
    addrs = []
    for i, (uid, kind, cell) in enumerate(items):
        addr = 0x0D010000 + i * 0x10000
        add_carried(
            mem, addr, uid, kind,
            mode=offsets.ITEM_MODE_IN_STORAGE,
            game_location=offsets.STORAGE_TRADE, pos=cell,
        )
        addrs.append(addr)
    # Chain them off the NPC's inventory head.
    if addrs:
        mem.regions[NPC_INVENTORY][
            offsets.INVENTORY_FIRST_ITEM : offsets.INVENTORY_FIRST_ITEM + 4
        ] = u32(addrs[0])
        for cur, nxt in zip(addrs, addrs[1:], strict=False):
            data = cur + 0x200
            mem.regions[data][
                offsets.ITEM_NEXT_INV : offsets.ITEM_NEXT_INV + 4
            ] = u32(nxt)
    return mem


HP = next(iter(offsets.HEALING_POTION_KINDS))
MP = next(iter(offsets.MANA_POTION_KINDS))


def test_reads_potions_with_their_cells():
    mem = vendor_world((1, HP, (0, 0)), (2, MP, (2, 1)))
    stock = read_vendor_stock(FakeSession(mem), NPC)
    assert {(p.potion_type, p.cell) for p in stock} == {
        ("healing", (0, 0)),
        ("mana", (2, 1)),
    }


def test_non_potions_are_ignored():
    mem = vendor_world((1, HP, (0, 0)), (2, 999, (1, 0)))  # 999 = some gear
    stock = read_vendor_stock(FakeSession(mem), NPC)
    assert [p.potion_type for p in stock] == ["healing"]


def test_an_empty_vendor_reads_empty_not_a_crash():
    assert read_vendor_stock(FakeSession(vendor_world()), NPC) == []


def test_cells_are_read_fresh_the_q4_property():
    # The same potions at different cells read as different cells — the
    # stock is followed, never assumed.
    a = read_vendor_stock(FakeSession(vendor_world((1, HP, (0, 0)))), NPC)
    b = read_vendor_stock(FakeSession(vendor_world((1, HP, (3, 2)))), NPC)
    assert a[0].cell == (0, 0) and b[0].cell == (3, 2)
