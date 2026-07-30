"""The town layer: every preamble step verified through scripted perception.

One mutable `Town` world powers all tests: the patched readers consult it,
and the fake input paths mutate it the way the real game would — or don't,
for the failure cases. What is under test is the verify-everything logic:
no step may report success on a click alone.
"""

from types import SimpleNamespace

import pytest

from pd2bot import offsets
from pd2bot.items import CarriedItem, CarriedItems
from pd2bot.player import Player
from pd2bot.snapshot import GameSnapshot
from pd2bot.town import (
    BeltBelowMinimum,
    PreambleReport,
    StashFull,
    TownConfig,
    TownError,
    TownLayer,
    Uncalibrated,
)
from pd2bot.uistate import UIState
from pd2bot.units import GameObject, Monster
from pd2bot.window import ClientRect
from pd2bot.world import Area

RECT = ClientRect(left=0, top=0, width=1536, height=864)

CALIBRATED = TownConfig(
    inventory_origin=(0.60, 0.40),
    inventory_cell=(0.02, 0.03),
    resurrect_row=(0.30, 0.35),
)
UNCALIBRATED = TownConfig(inventory_origin=None, inventory_cell=None)


def cell_pixel(cell):
    """The pixel CALIBRATED's fractions put a grid cell at."""
    return (
        round((0.60 + cell[0] * 0.02) * 1536),
        round((0.40 + cell[1] * 0.03) * 864),
    )

AKARA_POS = (5921, 5711)
KASHYA_POS = (5877, 5743)
CHARSI_POS = (5824, 5724)
STASH_POS = (5856, 5734)


def ally(kind, pos, hp=100):
    return Monster(
        unit_id=kind, kind=kind, position=pos, hp=hp, max_hp=100,
        is_champion=False, is_boss=False, is_minion=False,
        alignment=offsets.ALIGNMENT_FRIENDLY,
    )


def potion(uid, kind, *, belt_slot=None, cell=(0, 0)):
    if belt_slot is not None:
        return CarriedItem(uid, kind, 2, offsets.ITEM_MODE_IN_BELT, 0,
                           offsets.NODE_BELT, (belt_slot, 0), 1)
    return CarriedItem(uid, kind, 2, offsets.ITEM_MODE_IN_STORAGE,
                       offsets.STORAGE_INVENTORY, offsets.NODE_STORAGE, cell, 1)


def loot(uid, cell):
    return CarriedItem(uid, 522, 6, offsets.ITEM_MODE_IN_STORAGE,
                       offsets.STORAGE_INVENTORY, offsets.NODE_STORAGE, cell, 33)


class Town:
    """Scripted town state; fakes mutate it, patched readers consult it."""

    def __init__(self):
        self.hp, self.max_hp = 800, 1265
        self.mana, self.max_mana = 378, 378
        self.gold = 60_000
        self.gold_stash = 732_612
        self.merc_alive = True
        self.panels: set[int] = set()
        self.belt: list[CarriedItem] = []
        self.inventory: list[CarriedItem] = []
        self.akara_present = True
        self.kashya_present = True
        self.charsi_present = True
        self.heal_on_interact = True
        self.deposit_works = True
        self.refill_works = True
        self.resurrect_works = True
        self.world_clicks = []
        self.panel_clicks = []
        self.pressed = []
        self.walked = []
        self.alerts = []
        self._uid = 0

    # -- readers ---------------------------------------------------------------

    def player(self, session=None):
        return Player(
            name="MaqiuDoubing", level=91, act=1, position=(5880, 5720), mode=1,
            hp=self.hp, max_hp=self.max_hp, mana=self.mana, max_mana=self.max_mana,
            stamina=586, max_stamina=586, experience=0, gold=self.gold,
            gold_stash=self.gold_stash, strength=122, dexterity=72,
            vitality=357, energy=31,
        )

    def carried(self, session=None):
        return CarriedItems(items=tuple(self.belt + self.inventory), skipped=0)

    def snapshot(self):
        allies = []
        if self.akara_present:
            allies.append(ally(offsets.NPC_AKARA, AKARA_POS))
        if self.kashya_present:
            allies.append(ally(offsets.NPC_KASHYA, KASHYA_POS))
        if self.charsi_present:
            allies.append(ally(offsets.NPC_CHARSI, CHARSI_POS))
        if self.merc_alive:
            allies.append(ally(271, (5881, 5721)))
        return GameSnapshot(
            in_game=True, taken_at=0.0,
            area=Area(level_no=1, position=(0, 0), size=(500, 500)),
            allies=tuple(allies),
            objects=(GameObject(9, offsets.OBJ_STASH, STASH_POS, 0),),
        )

    def ui_state(self, session=None, ui_array=None):
        return UIState(frozenset(self.panels))

    # -- fake input paths --------------------------------------------------------

    def click_world(self, x, y, **kwargs):
        self.world_clicks.append((x, y))
        if (x, y) == AKARA_POS:
            self.panels.add(offsets.UI_NPCMENU)
            if self.heal_on_interact:
                self.hp, self.mana = self.max_hp, self.max_mana
        elif (x, y) == KASHYA_POS:
            self.panels.add(offsets.UI_NPCMENU)
        elif (x, y) == STASH_POS:
            self.panels.add(offsets.UI_STASH)
        return (0, 0)

    def _item_at_pixel(self, sx, sy):
        """Which inventory item the click landed on — the real game routes
        by position, so the fake must too, or a test can 'succeed' by
        moving an item nobody clicked."""
        for index, item in enumerate(self.inventory):
            if cell_pixel(item.position) == (sx, sy):
                return index, item
        return None, None

    def panel_click(self, panel_id, sx, sy, button="left", shift=False):
        self.panel_clicks.append((panel_id, sx, sy, button, shift))
        if panel_id == offsets.UI_STASH and shift and button == "right":
            index, item = self._item_at_pixel(sx, sy)
            if self.deposit_works and item is not None:
                self.inventory.pop(index)
        elif panel_id == offsets.UI_INVENTORY and shift:
            if self.refill_works:
                index, item = self._item_at_pixel(sx, sy)
                if item is not None and item.potion_name is not None:
                    moved = self.inventory.pop(index)
                    self._uid += 1
                    self.belt.append(
                        potion(900 + self._uid, moved.kind, belt_slot=len(self.belt))
                    )
        elif panel_id == offsets.UI_NPCMENU and self.resurrect_works:
            self.merc_alive = True
            # Paid from the person first, then the stash (R76).
            spend = min(self.gold, 50_000)
            self.gold -= spend
            self.gold_stash -= 50_000 - spend

    def press_key(self, vk):
        self.pressed.append(vk)
        if vk == 0x49:  # VK_I
            self.panels.add(offsets.UI_INVENTORY)

    def press_escape(self):
        for panel_id in (offsets.UI_STASH, offsets.UI_NPCMENU, offsets.UI_INVENTORY):
            if panel_id in self.panels:
                self.panels.discard(panel_id)
                return


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def town(monkeypatch):
    state = Town()
    monkeypatch.setattr("pd2bot.town.uistate.read_ui_state", state.ui_state)
    # Nothing worn by default, so the conditional repair step stays out of
    # the way of tests about other steps; repair tests patch this again.
    monkeypatch.setattr("pd2bot.town.read_equipped_durability", lambda session: ())
    return state


def layer(town_state, config=CALIBRATED):
    clock = FakeClock()
    gated = SimpleNamespace(
        click_world=town_state.click_world, press_key=town_state.press_key
    )
    panel = SimpleNamespace(
        click=town_state.panel_click,
        window=SimpleNamespace(client_rect=lambda: RECT),
        _ui_array=0,
    )
    menu = SimpleNamespace(press_escape=town_state.press_escape)
    return TownLayer(
        session=object(),
        gated=gated,
        panel=panel,
        menu=menu,
        walk_to=lambda pos: town_state.walked.append(pos),
        snapshot=town_state.snapshot,
        config=config,
        carried=town_state.carried,
        read_player_fn=town_state.player,
        alert=town_state.alerts.append,
        clock=clock,
        sleep=clock.sleep,
    )


# -- heal ------------------------------------------------------------------------


def test_heal_short_circuits_at_full_vitals(town):
    town.hp, town.mana = town.max_hp, town.max_mana
    report = PreambleReport()
    layer(town).heal_at_akara(report)
    assert report.healed and town.world_clicks == []


def test_heal_interacts_verifies_and_closes(town):
    report = PreambleReport()
    layer(town).heal_at_akara(report)
    assert report.healed
    assert AKARA_POS in town.world_clicks
    assert offsets.UI_NPCMENU not in town.panels  # closed afterwards
    assert (town.hp, town.mana) == (town.max_hp, town.max_mana)


def test_heal_fails_when_vitals_never_fill(town):
    """And the failure accuses the right thing: a dialog that opens but does
    not heal means the NPC kind table is wrong (T12's live failure), not
    that the clicking missed."""
    town.heal_on_interact = False
    with pytest.raises(TownError, match="does not heal.*kind table is wrong"):
        layer(town).heal_at_akara(PreambleReport())
    # bounded: initial + retries interactions, no infinite clicking
    assert len(town.world_clicks) == 1 + CALIBRATED.interact_retries


# (An earlier test asserted that an out-of-range Akara was a hard error.
# The first live run showed that is simply the normal case — perception
# reaches 80 subtiles and towns are bigger than that — so the behaviour
# changed to walk-then-look; see the R63 regression tests at the bottom.)


# -- stash deposit ------------------------------------------------------------------


def test_deposit_transfers_each_item_and_verifies(town):
    town.inventory = [loot(1, (2, 1)), loot(2, (4, 0))]
    report = PreambleReport()
    layer(town).deposit_to_stash(lambda i: True, report)
    assert report.deposited == 2
    assert town.inventory == []
    assert STASH_POS in town.world_clicks  # chest opened
    stash_clicks = [c for c in town.panel_clicks if c[0] == offsets.UI_STASH]
    assert all(c[3] == "right" and c[4] for c in stash_clicks)  # shift+right
    assert offsets.UI_STASH not in town.panels  # closed afterwards


def test_deposit_respects_the_keep_predicate(town):
    town.inventory = [loot(1, (2, 1)), potion(2, 606, cell=(5, 0))]
    report = PreambleReport()
    layer(town).deposit_to_stash(lambda i: i.potion_name is None, report)
    assert report.deposited == 1
    assert [i.unit_id for i in town.inventory] == [2]  # the potion stayed


def test_deposit_that_never_takes_halts_loudly(town):
    town.inventory = [loot(1, (2, 1))]
    town.deposit_works = False
    with pytest.raises(StashFull):
        layer(town).deposit_to_stash(lambda i: True, PreambleReport())
    assert len(town.alerts) == 1
    attempts = [c for c in town.panel_clicks if c[0] == offsets.UI_STASH]
    assert len(attempts) == CALIBRATED.transfer_attempts  # bounded, no spam


def test_deposit_needs_grid_calibration(town):
    """TownConfig ships the measured fractions (R60), so this explicitly
    strips them: an uncalibrated build must refuse, not guess."""
    town.inventory = [loot(1, (2, 1))]
    with pytest.raises(Uncalibrated):
        layer(town, UNCALIBRATED).deposit_to_stash(lambda i: True, PreambleReport())


def test_deposit_grid_pixel_math(town):
    town.inventory = [loot(1, (2, 1))]
    layer(town).deposit_to_stash(lambda i: True, PreambleReport())
    _, sx, sy, _, _ = town.panel_clicks[0]
    assert (sx, sy) == cell_pixel((2, 1))


# -- belt refill ------------------------------------------------------------------------


def _stock_belt_at_minimums(town):
    town.belt = (
        [potion(10 + n, 606, belt_slot=2 + 4 * (n % 2)) for n in range(4)]
        + [potion(20, 610, belt_slot=0), potion(21, 611, belt_slot=4)]
    )


def test_refill_no_shortfall_sends_nothing(town):
    _stock_belt_at_minimums(town)
    report = PreambleReport()
    layer(town).refill_belt(report)
    assert report.refilled == 0 and town.panel_clicks == []


def test_refill_moves_potions_until_minimums_hold(town):
    town.belt = [potion(20, 610, belt_slot=0)]  # 1 mana, 0 healing
    town.inventory = [potion(30 + n, 606, cell=(n, 1)) for n in range(6)]
    town.inventory += [potion(40, 611, cell=(3, 2))]
    report = PreambleReport()
    layer(town).refill_belt(report)
    assert report.refilled == 5  # 4 healing + 1 mana
    assert 0x49 in town.pressed  # inventory opened via the key
    assert offsets.UI_INVENTORY not in town.panels  # and closed after


def test_refill_below_minimum_halts_loudly(town):
    town.belt = []
    town.inventory = [potion(30, 606, cell=(1, 1))]  # one healing, nothing else
    with pytest.raises(BeltBelowMinimum):
        layer(town).refill_belt(PreambleReport())
    assert len(town.alerts) == 1


def test_refill_closes_the_stash_before_clicking(town):
    """With the stash open the same shift+click would stash the potion —
    the refill must get the stash off screen first."""
    town.panels.add(offsets.UI_STASH)
    town.belt = [potion(20, 610, belt_slot=0), potion(21, 611, belt_slot=4)]
    town.inventory = [potion(30 + n, 606, cell=(n, 1)) for n in range(6)]
    layer(town).refill_belt(PreambleReport())
    inventory_clicks = [c for c in town.panel_clicks if c[0] == offsets.UI_INVENTORY]
    assert inventory_clicks and offsets.UI_STASH not in town.panels


# -- merc resurrect ------------------------------------------------------------------------


def test_merc_alive_needs_nothing(town):
    report = PreambleReport()
    layer(town).resurrect_merc_if_dead(report)
    assert report.merc_action == "not_needed"
    assert town.world_clicks == [] and town.panel_clicks == []


def test_merc_dead_without_gold_anywhere_skips_with_a_log(town):
    town.merc_alive = False
    town.gold = 0
    town.gold_stash = 0
    report = PreambleReport()
    layer(town).resurrect_merc_if_dead(report)
    assert report.merc_action == "skipped_gold"
    assert town.world_clicks == []


def test_stashed_gold_alone_pays_for_the_resurrect(town):
    """PD2 pays for services out of the shared stash regardless of what is
    on the person (R76). The character habitually carries nothing (R52), so
    a carried-only check would have skipped this step forever."""
    town.merc_alive = False
    town.gold = 0
    town.gold_stash = 732_612
    report = PreambleReport()
    layer(town).resurrect_merc_if_dead(report)
    assert report.merc_action == "resurrected"


def test_merc_dead_uncalibrated_halts_for_calibration(town):
    town.merc_alive = False
    config = TownConfig(
        inventory_origin=(0.6, 0.4), inventory_cell=(0.02, 0.03), resurrect_row=None
    )
    with pytest.raises(Uncalibrated):
        layer(town, config).resurrect_merc_if_dead(PreambleReport())
    assert len(town.alerts) == 1 and town.world_clicks == []


def test_merc_resurrect_verified_by_life_and_gold(town):
    town.merc_alive = False
    report = PreambleReport()
    layer(town).resurrect_merc_if_dead(report)
    assert report.merc_action == "resurrected"
    assert town.merc_alive and town.gold == 10_000
    assert offsets.UI_NPCMENU not in town.panels


def test_merc_resurrect_failure_halts_with_diagnostics(town):
    """Bounded retries, then stop and say what was on screen. Retrying is
    safe here despite it being a paid transaction: the effect check runs
    after every click, so a click that worked returns before the next one,
    and a click that did nothing costs nothing."""
    town.merc_alive = False
    town.resurrect_works = False
    with pytest.raises(TownError, match="resurrect row:.*no effect"):
        layer(town).resurrect_merc_if_dead(PreambleReport())
    npc_clicks = [c for c in town.panel_clicks if c[0] == offsets.UI_NPCMENU]
    assert len(npc_clicks) == 1 + TownConfig().panel_click_retries
    assert len(town.alerts) == 1


# -- the preamble ------------------------------------------------------------------------


def test_preamble_runs_in_the_agreed_order(town):
    town.inventory = [loot(1, (2, 1))]
    _stock_belt_at_minimums(town)
    report = layer(town).run_preamble(lambda i: i.potion_name is None)
    assert report.healed and report.deposited == 1
    assert report.merc_action == "not_needed"
    steps = [line.split(":")[0] for line in report.log]
    assert steps == ["heal", "repair", "stash", "belt", "merc"]


def charm(uid, cell):
    """An item in PD2's charm space: same container, same bytes, off limits."""
    return CarriedItem(uid, 522, 6, offsets.ITEM_MODE_IN_STORAGE,
                       offsets.STORAGE_INVENTORY, offsets.NODE_STORAGE, cell, 33)


def test_deposit_never_touches_charm_space(town):
    """The failure this prevents (R60): the live character keeps 24 items in
    charm space, every one indistinguishable from ordinary inventory except
    by cell. Walking them would fail every transfer and halt over a stash
    that was never full."""
    town.inventory = [charm(1, (0, 4)), charm(2, (9, 7)), loot(3, (2, 1))]
    report = PreambleReport()
    layer(town).deposit_to_stash(lambda i: True, report)
    assert report.deposited == 1  # only the usable-grid item
    assert sorted(i.unit_id for i in town.inventory) == [1, 2]
    assert town.alerts == []  # emphatically not a full-stash halt


def test_refill_ignores_potions_sitting_in_charm_space(town):
    town.belt = [potion(20, 610, belt_slot=0), potion(21, 611, belt_slot=4)]
    town.inventory = [
        CarriedItem(50 + n, 606, 2, offsets.ITEM_MODE_IN_STORAGE,
                    offsets.STORAGE_INVENTORY, offsets.NODE_STORAGE, (n, 5), 1)
        for n in range(6)
    ]
    with pytest.raises(BeltBelowMinimum):
        layer(town).refill_belt(PreambleReport())
    assert town.panel_clicks == []  # nothing was clickable


def test_grid_pixel_refuses_cells_outside_the_usable_grid(town):
    """Even if a caller slips through, the pixel maths itself refuses —
    the calibration only describes the 10x4 usable rectangle."""
    with pytest.raises(TownError, match="outside the usable inventory grid"):
        layer(town)._grid_pixel((0, 4))
    with pytest.raises(TownError, match="outside the usable inventory grid"):
        layer(town)._grid_pixel((10, 0))


# -- what the first live run broke on (R63) --------------------------------------


def test_heal_walks_to_the_configured_spot_when_akara_is_out_of_range(town):
    """T12's live failure: perception reaches 80 subtiles, and a town NPC is
    routinely further than that from where you stand. Asking perception and
    giving up is wrong — walk to the known approach position, then look."""
    town.akara_present = False  # out of perception range
    arrivals = []

    known = CALIBRATED.npc_positions[offsets.NPC_AKARA]

    def walk(pos):
        town.walked.append(pos)
        arrivals.append(pos)
        # Arriving NEAR the configured spot brings her into perception —
        # the walk stops short of it on purpose (standoff), so an exact
        # match would be the wrong thing to model.
        if max(abs(pos[0] - known[0]), abs(pos[1] - known[1])) <= 10:
            town.akara_present = True

    step = layer(town)
    step.walk_to = walk
    report = PreambleReport()
    step.heal_at_akara(report)

    assert max(
        abs(arrivals[0][0] - known[0]), abs(arrivals[0][1] - known[1])
    ) <= CALIBRATED.npc_standoff
    assert AKARA_POS in town.world_clicks
    assert report.healed


def test_heal_reports_clearly_when_the_approach_position_is_wrong(town):
    town.akara_present = False  # never appears, even after walking
    with pytest.raises(TownError, match="approach position may be wrong"):
        layer(town).heal_at_akara(PreambleReport())


def test_npc_without_a_configured_position_refuses_to_walk_blind(town):
    town.akara_present = False
    config = TownConfig(npc_positions={})
    with pytest.raises(TownError, match="cannot walk blind"):
        layer(town, config).heal_at_akara(PreambleReport())


def test_steps_close_a_leftover_panel_before_walking(town):
    """T13's live failure: the stash was already open when the step began,
    so GatedInput refused the very first walk and the step died ten seconds
    later in the navigator. Each step now starts from a clean state."""
    town.panels.add(offsets.UI_STASH)
    town.inventory = [loot(1, (2, 1))]
    report = PreambleReport()
    layer(town).deposit_to_stash(lambda i: True, report)
    assert report.deposited == 1


def test_heal_closes_a_leftover_panel_before_walking(town):
    town.panels.add(offsets.UI_INVENTORY)
    report = PreambleReport()
    layer(town).heal_at_akara(report)
    assert report.healed


def cube(uid, cell):
    """The Horadric Cube: right-click opens it, so the transfer gesture
    does something else entirely (R67)."""
    return CarriedItem(uid, offsets.CUBE_KIND, 2, offsets.ITEM_MODE_IN_STORAGE,
                       offsets.STORAGE_INVENTORY, offsets.NODE_STORAGE, cell, 1)


def test_deposit_skips_the_horadric_cube(town):
    """T13's live halt: the cube sat at (1,0), two shift+right-clicks moved
    nothing, and the guardrail stopped the whole preamble. The cube must be
    filtered before it is ever clicked."""
    town.inventory = [cube(1, (1, 0)), loot(2, (3, 1))]
    report = PreambleReport()
    layer(town).deposit_to_stash(lambda i: True, report)
    assert report.deposited == 1
    assert [i.unit_id for i in town.inventory] == [1]  # the cube stayed
    assert town.alerts == []  # and it did not halt
    assert any("unmovable" in line for line in report.log)


def test_deposit_skips_unmovables_even_when_the_predicate_wants_them(town):
    """Filtering lives in the layer, not the caller: a pickit that says
    'keep' must not be able to halt every game on the cube."""
    town.inventory = [cube(1, (0, 0))]
    report = PreambleReport()
    layer(town).deposit_to_stash(lambda i: True, report)
    assert report.deposited == 0 and town.alerts == []


def test_approach_stops_short_of_an_npc(town):
    """T12's real bug: walking ONTO an NPC means clicking on them, which
    opens their dialog, which blocks every later click. Approach walks must
    stop short and leave the interaction to a deliberate click."""
    town.hp = 800  # so the heal actually runs
    step = layer(town)
    step.heal_at_akara(PreambleReport())
    assert town.walked, "expected an approach walk"
    for destination in town.walked:
        gap = max(abs(destination[0] - AKARA_POS[0]), abs(destination[1] - AKARA_POS[1]))
        assert gap >= CALIBRATED.npc_standoff - 1, f"walked onto the NPC at {destination}"


def test_no_walk_at_all_when_already_beside_the_npc(town):
    """The shortest walk is none: standing in range, just click."""
    step = layer(town)
    step._read_player = lambda session: SimpleNamespace(
        position=(AKARA_POS[0] + 2, AKARA_POS[1]), hp=800, max_hp=1265,
        mana=378, max_mana=378,
    )
    step._walk_near(AKARA_POS)
    assert town.walked == []


def test_walk_recovers_when_a_travel_click_opens_a_dialog(town):
    """T12's true cause (R68): the navigator moves by clicking toward the
    destination, and a click landing on a bystander opens their dialog
    instead — the bot was correctly aimed at Akara and waylaid by Kashya en
    route. Close the dialog and resume; every attempt makes real progress."""
    from pd2bot.navigate import NavigationError

    attempts = []

    def walk(pos):
        attempts.append(pos)
        if len(attempts) == 1:
            town.panels.add(offsets.UI_NPCMENU)  # walked into a chat
            raise NavigationError("input stayed refused: npc_menu open")
        town.walked.append(pos)

    step = layer(town)
    step.walk_to = walk
    step._walk_guarded((5900, 5700))
    assert len(attempts) == 2  # retried after closing
    assert offsets.UI_NPCMENU not in town.panels


def test_walk_does_not_retry_a_genuine_pathing_failure(town):
    """A NavigationError with no panel open means the route really failed;
    retrying would just burn time and hide it."""
    from pd2bot.navigate import NavigationError

    attempts = []

    def walk(pos):
        attempts.append(pos)
        raise NavigationError("no route to target")

    step = layer(town)
    step.walk_to = walk
    with pytest.raises(NavigationError, match="no route"):
        step._walk_guarded((5900, 5700))
    assert len(attempts) == 1  # exactly one, then out


def test_walk_gives_up_after_bounded_dialog_recoveries(town):
    from pd2bot.navigate import NavigationError

    def walk(pos):
        town.panels.add(offsets.UI_NPCMENU)
        raise NavigationError("input stayed refused: npc_menu open")

    step = layer(town)
    step.walk_to = walk
    with pytest.raises(TownError, match="kept opening dialogs"):
        step._walk_guarded((5900, 5700))


# -- repair (R70) -------------------------------------------------------------


def worn(uid, current, maximum):
    from pd2bot.items import Durability

    return Durability(unit_id=uid, kind=30, current=current, maximum=maximum)


def with_durability(town_state, monkeypatch, items):
    """Patch the durability reader; `items` is re-read each call so the fake
    repair can change it."""
    monkeypatch.setattr(
        "pd2bot.town.read_equipped_durability", lambda session: tuple(items)
    )


REPAIR_CFG = TownConfig(
    inventory_origin=(0.60, 0.40),
    inventory_cell=(0.02, 0.03),
    trade_repair_row=(0.30, 0.60),
    repair_all_button=(0.20, 0.80),
)


def test_repair_goes_for_even_slight_wear(town, monkeypatch):
    """Repair every game (R71): no threshold to tune, so a single point of
    wear is reason enough to visit."""
    items = [worn(1, 99, 100)]
    with_durability(town, monkeypatch, items)
    charsi = CALIBRATED.npc_positions[offsets.NPC_CHARSI]

    def click_world(x, y, **kwargs):
        town.world_clicks.append((x, y))
        if (x, y) == charsi:
            town.panels.add(offsets.UI_NPCMENU)
        return (0, 0)

    def panel_click(panel_id, sx, sy, button="left", shift=False):
        town.panel_clicks.append((panel_id, sx, sy, button, shift))
        if panel_id == offsets.UI_NPCMENU:
            town.panels.add(offsets.UI_NPCSHOP)
        elif panel_id == offsets.UI_NPCSHOP:
            items[:] = [worn(d.unit_id, d.maximum, d.maximum) for d in items]

    town.click_world = click_world
    town.panel_click = panel_click
    town.press_escape = lambda: town.panels.clear()

    report = PreambleReport()
    layer(town, REPAIR_CFG).repair_at_charsi(report)
    assert report.repaired == 1


def test_repair_skips_only_when_gear_is_pristine(town, monkeypatch):
    """The one case worth skipping: the walk would buy nothing and could
    not be verified either way."""
    with_durability(town, monkeypatch, [worn(1, 100, 100)])
    report = PreambleReport()
    layer(town, REPAIR_CFG).repair_at_charsi(report)
    assert report.repaired == 0 and town.walked == [] and town.world_clicks == []
    assert any("nothing worn" in line for line in report.log)


def test_repair_refuses_without_calibration(town, monkeypatch):
    """TownConfig ships T18's measured fractions, so this strips them
    explicitly: an uncalibrated build must refuse rather than guess."""
    with_durability(town, monkeypatch, [worn(1, 5, 100)])
    bare = TownConfig(trade_repair_row=None, repair_all_button=None)
    with pytest.raises(Uncalibrated, match="repair UI is not calibrated"):
        layer(town, bare).repair_at_charsi(PreambleReport())


def test_repair_walks_clicks_and_verifies_by_durability(town, monkeypatch):
    items = [worn(1, 5, 100), worn(2, 30, 100)]
    with_durability(town, monkeypatch, items)

    # Charsi's dialog opens on the world click; the shop opens on the row
    # click; repair-all restores durability.
    charsi = CALIBRATED.npc_positions[offsets.NPC_CHARSI]
    original_world = town.click_world

    def click_world(x, y, **kwargs):
        if (x, y) == charsi:
            town.world_clicks.append((x, y))
            town.panels.add(offsets.UI_NPCMENU)
            return (0, 0)
        return original_world(x, y, **kwargs)

    def panel_click(panel_id, sx, sy, button="left", shift=False):
        town.panel_clicks.append((panel_id, sx, sy, button, shift))
        if panel_id == offsets.UI_NPCMENU:
            town.panels.add(offsets.UI_NPCSHOP)
        elif panel_id == offsets.UI_NPCSHOP:
            items[:] = [worn(d.unit_id, d.maximum, d.maximum) for d in items]

    town.click_world = click_world
    town.panel_click = panel_click
    town.press_escape = lambda: town.panels.clear()

    report = PreambleReport()
    layer(town, REPAIR_CFG).repair_at_charsi(report)
    assert report.repaired == 2
    assert [c[0] for c in town.panel_clicks] == [offsets.UI_NPCMENU, offsets.UI_NPCSHOP]
    assert all(d.missing == 0 for d in items)


def test_repair_halts_when_durability_does_not_recover(town, monkeypatch):
    """A clicked button that repaired nothing means the row or the button
    moved — NPC menus are state-dependent (R56), so this must be loud."""
    with_durability(town, monkeypatch, [worn(1, 5, 100)])
    charsi = CALIBRATED.npc_positions[offsets.NPC_CHARSI]

    def click_world(x, y, **kwargs):
        town.world_clicks.append((x, y))
        if (x, y) == charsi:
            town.panels.add(offsets.UI_NPCMENU)
        return (0, 0)

    def panel_click(panel_id, sx, sy, button="left", shift=False):
        town.panel_clicks.append((panel_id, sx, sy, button, shift))
        if panel_id == offsets.UI_NPCMENU:
            town.panels.add(offsets.UI_NPCSHOP)
        # repair-all does nothing: the button moved

    town.click_world = click_world
    town.panel_click = panel_click
    town.press_escape = lambda: town.panels.clear()

    with pytest.raises(TownError, match="repair-all button:.*no effect"):
        layer(town, REPAIR_CFG).repair_at_charsi(PreambleReport())
    assert len(town.alerts) == 1


def test_repair_retries_a_missed_npc_click(town, monkeypatch):
    """T19's first live failure: repair had a single attempt where the heal
    had three. NPCs pace, so one click can miss where a second connects —
    and two steps doing the same thing should not differ in robustness."""
    items = [worn(1, 50, 100)]
    with_durability(town, monkeypatch, items)
    charsi = CALIBRATED.npc_positions[offsets.NPC_CHARSI]
    attempts = []

    def click_world(x, y, **kwargs):
        attempts.append((x, y))
        town.world_clicks.append((x, y))
        if (x, y) == charsi and len(attempts) >= 2:  # the first click misses
            town.panels.add(offsets.UI_NPCMENU)
        return (700, 400)

    def panel_click(panel_id, sx, sy, button="left", shift=False):
        town.panel_clicks.append((panel_id, sx, sy, button, shift))
        if panel_id == offsets.UI_NPCMENU:
            town.panels.add(offsets.UI_NPCSHOP)
        elif panel_id == offsets.UI_NPCSHOP:
            items[:] = [worn(d.unit_id, d.maximum, d.maximum) for d in items]

    town.click_world = click_world
    town.panel_click = panel_click
    town.press_escape = lambda: town.panels.clear()

    report = PreambleReport()
    layer(town, REPAIR_CFG).repair_at_charsi(report)
    assert len(attempts) == 2 and report.repaired == 1


def test_repair_failure_names_where_it_clicked(town, monkeypatch):
    """A failure that does not say where it aimed costs a live round trip."""
    with_durability(town, monkeypatch, [worn(1, 50, 100)])
    town.click_world = lambda x, y, **k: (700, 400)  # never opens anything
    with pytest.raises(TownError, match=r"last click at .*player at"):
        layer(town, REPAIR_CFG).repair_at_charsi(PreambleReport())


def test_approach_stops_outside_the_click_selection_radius(town):
    """R78: a 5-subtile standoff put the walk's own travel clicks inside
    D2's selection radius, so the navigator kept opening Kashya's dialog
    and spending its recoveries closing it. Stop far enough out that a
    travel click cannot reach the NPC."""
    step = layer(town)
    step._read_player = lambda session: SimpleNamespace(
        position=(5700, 5700), hp=800, max_hp=1265, mana=100, max_mana=378,
        gold=0, gold_stash=0,
    )
    step._walk_near(KASHYA_POS)
    assert town.walked, "expected a walk"
    gap = max(
        abs(town.walked[-1][0] - KASHYA_POS[0]),
        abs(town.walked[-1][1] - KASHYA_POS[1]),
    )
    assert gap >= 8, f"walk ended {gap} subtiles from the NPC — inside click range"


def test_all_three_npc_steps_share_one_interaction_path(town, monkeypatch):
    """The asymmetry that broke T19: heal retried a missed click, repair did
    not. One path means they cannot drift apart again."""
    import inspect

    from pd2bot.town import TownLayer as Layer

    for method in (Layer.heal_at_akara, Layer.repair_at_charsi,
                   Layer.resurrect_merc_if_dead):
        source = inspect.getsource(method)
        assert "open_npc_dialog" in source, f"{method.__name__} hand-rolls its own"


def test_panel_clicks_wait_for_the_panel_to_settle(town, monkeypatch):
    """R80: the panel flag goes up before the panel can be clicked — D2
    animates dialogs in, and a click landing in that window is lost. So a
    settle delay precedes every in-panel click."""
    slept = []
    step = layer(town)
    step._sleep = slept.append
    town.panels.add(offsets.UI_NPCMENU)
    step.click_in_panel_until(
        offsets.UI_NPCMENU, (0.5, 0.5), lambda: True, what="a row"
    )
    assert slept and slept[0] == TownConfig().panel_settle_s


def test_panel_click_retries_then_reports_what_is_on_screen(town):
    """The diagnostic that matters: not only 'the shop did not open' but
    'here is what WAS open', which is what turns a live round trip into a
    read of the error message."""
    town.panels.add(offsets.UI_NPCMENU)
    town.panel_click = lambda *a, **k: town.panel_clicks.append(a)  # no effect
    with pytest.raises(TownError, match=r"panels now open: npc_menu"):
        layer(town).click_in_panel_until(
            offsets.UI_NPCMENU, (0.5, 0.5), lambda: False, what="a row"
        )
    assert len(town.panel_clicks) == 1 + TownConfig().panel_click_retries


def test_panel_click_stops_if_the_panel_closes_under_it(town):
    """No point clicking into a panel that has gone; say so instead."""
    town.panels.add(offsets.UI_NPCMENU)

    def vanish(*args, **kwargs):
        town.panel_clicks.append(args)
        town.panels.discard(offsets.UI_NPCMENU)

    town.panel_click = vanish
    with pytest.raises(TownError, match="no effect"):
        layer(town).click_in_panel_until(
            offsets.UI_NPCMENU, (0.5, 0.5), lambda: False, what="a row"
        )
    assert len(town.panel_clicks) == 1  # did not keep clicking at nothing


def test_a_stop_request_breaks_out_of_the_retry_ladders(town):
    """R80: a bot looping inside a retry ladder was unstoppable — the drill
    harness could only cancel its own waits, so a human watched a dozen
    approach-and-chat cycles run to exhaustion. Every ladder now honours an
    outside veto."""
    from pd2bot.town import TownStopped

    stop = {"now": False}
    town.panels.add(offsets.UI_NPCMENU)

    def click_and_stop(*args, **kwargs):
        town.panel_clicks.append(args)
        stop["now"] = True  # the human hits cancel after the first click

    # Bind the fake BEFORE building the layer: `layer()` captures the
    # method by value, so a later assignment would never be seen.
    town.panel_click = click_and_stop
    step = layer(town)
    step._should_stop = lambda: stop["now"]
    with pytest.raises(TownStopped):
        step.click_in_panel_until(
            offsets.UI_NPCMENU, (0.5, 0.5), lambda: False, what="a row"
        )
    assert len(town.panel_clicks) == 1  # stopped instead of exhausting retries


def test_dialog_already_open_is_not_re_approached(town):
    """The Kashya loop (R80): re-approaching with the dialog open cannot
    work — the walk is refused while a panel blocks input, so the guard
    closed the dialog, walked, and the next click reopened it, forever."""
    town.panels.add(offsets.UI_NPCMENU)
    step = layer(town)
    step.open_npc_dialog(offsets.NPC_KASHYA, "Kashya")
    assert town.walked == [] and town.world_clicks == []


def test_opening_the_stash_retries_and_allows_for_the_walk(town):
    """The same latent pair that broke the NPC path (R80): clicking the
    stash from across the room means a walk before the panel opens, and a
    single un-retried attempt gives up mid-journey. Fixed before it could
    be found live a third time."""
    attempts = []
    original = town.click_world

    def click_world(x, y, **kwargs):
        attempts.append((x, y))
        if len(attempts) >= 2:  # the first attempt "times out" mid-walk
            return original(x, y, **kwargs)
        town.world_clicks.append((x, y))
        return (0, 0)

    town.click_world = click_world
    town.inventory = [loot(1, (2, 1))]
    report = PreambleReport()
    layer(town).deposit_to_stash(lambda i: True, report)
    assert len(attempts) == 2 and report.deposited == 1


def test_open_object_panel_short_circuits_when_already_open(town):
    """Inside the retry loop this matters: a click that worked but was slow
    to register must not send the bot walking off to click again."""
    town.panels.add(offsets.UI_STASH)
    step = layer(town)
    step.open_object_panel(offsets.OBJ_STASH, "the stash", offsets.UI_STASH)
    assert town.world_clicks == [] and town.walked == []


def test_deposit_closes_a_stale_stash_then_opens_it_itself(town):
    """Not a contradiction of the above: the step must close panels before
    it can walk at all (GatedInput refuses through a panel), so a stash
    left open by a human is closed and then re-opened deliberately."""
    town.panels.add(offsets.UI_STASH)
    town.inventory = [loot(1, (2, 1))]
    report = PreambleReport()
    layer(town).deposit_to_stash(lambda i: True, report)
    assert STASH_POS in town.world_clicks  # opened by us, not inherited
    assert report.deposited == 1
