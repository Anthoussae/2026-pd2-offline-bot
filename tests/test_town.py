"""The town layer: every preamble step verified through scripted perception.

One mutable `Town` world powers all tests: the patched readers consult it,
and the fake input paths mutate it the way the real game would — or don't,
for the failure cases. What is under test is the verify-everything logic:
no step may report success on a click alone.
"""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from pd2bot import offsets
from pd2bot.perception import uistate
from pd2bot.perception.items import CarriedItem, CarriedItems
from pd2bot.perception.player import Player
from pd2bot.perception.snapshot import GameSnapshot
from pd2bot.perception.uistate import UIState
from pd2bot.perception.units import GameObject, Monster
from pd2bot.perception.world import Area
from pd2bot.town import (
    BeltBelowMinimum,
    PreambleReport,
    StashFull,
    TownConfig,
    TownError,
    TownLayer,
    Uncalibrated,
)
from pd2bot.uipoints import default_points
from pd2bot.window import ClientRect

RECT = ClientRect(left=0, top=0, width=1536, height=864)

def points(overrides):
    """The point registry with test values filled in (R87).

    Sets whichever field actually calibrates that point: a screen-anchored
    one takes a client-rect fraction, an NPC-anchored one takes a pixel
    offset from the NPC (R97). Call sites do not have to care which is
    which — that is the registry's business, not the test's.

    Tests that exercise a click must say what they are aiming at, which is
    the honest reading of them anyway: they check the mechanism, never the
    measurement.
    """
    base = default_points()
    for name, value in overrides.items():
        point = base[name]
        if point.by_keyboard:
            base[name] = replace(point, keyboard_row=value)
        elif point.npc_anchored:
            base[name] = replace(point, npc_offset=value)
        else:
            base[name] = replace(point, fraction=value)
    return base


CALIBRATED = TownConfig(
    inventory_origin=(0.60, 0.40),
    inventory_cell=(0.02, 0.03),
    ui_points=points({"kashya.resurrect": 2}),  # row 2 of 4, dead-merc menu
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


def loot(uid, cell, kind=522):
    return CarriedItem(uid, kind, 6, offsets.ITEM_MODE_IN_STORAGE,
                       offsets.STORAGE_INVENTORY, offsets.NODE_STORAGE, cell, 33)


def _point_pixel(name):
    """Where a shipped screen-anchored point lands in the test rect."""
    return default_points()[name].pixel(RECT)


def stashed(uid, cell=(0, 0)):
    """An item sitting in the REGULAR stash — what the tab signal reads."""
    return CarriedItem(uid, 522, 6, offsets.ITEM_MODE_IN_STORAGE,
                       offsets.STORAGE_STASH, offsets.NODE_STORAGE, cell, 33)


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
        # Kinds the game refuses to stash while accepting everything else
        # — the T70 run 2 shape, where ONE item stuck and the layer called
        # it a full stash. `deposit_works = False` is the all-or-nothing
        # version and cannot express it.
        self.refuse_kinds: set[int] = set()
        # A world click on an object that does NOT open its panel — the
        # live 2026-08-01 failure, which the fake could not express.
        self.object_click_works = True
        self.refill_works = True
        self.resurrect_works = True
        self.world_clicks = []
        self.panel_clicks = []
        self.pressed = []
        self.walked = []
        self.pos = (5880, 5720)
        self.alerts = []
        # Kept apart from `alerts` on purpose: a halt and a keep-going
        # warning are different events, and a test that cannot tell them
        # apart cannot catch the two being confused — which is exactly what
        # T27's first run caught in the R132 stash-pressure warning.
        self.notices = []
        self._uid = 0
        # Whose dialog is open, and where the highlight sits in it. The
        # menus genuinely differ, so the fake must too (R104/R105):
        #   Charsi          TALK / TRADE-REPAIR / CANCEL
        #   Kashya, dead    TALK / RESURRECT / HIRE / CANCEL
        #   Kashya, alive   TALK / HIRE / CANCEL   <- row 2 is HIRE, not
        #                                             resurrect: same index,
        #                                             different action (R56)
        self.dialog_npc = None
        self.dialog_row = 1  # the highlight opens here and wraps at the end
        # The stash and its two tabs (R75). `material_kinds` is what the
        # MATERIALS tab will accept — the game does this classification, so
        # the fake owns it and the bot must never assume it.
        self.stash: list[CarriedItem] = [stashed(9001), stashed(9002)]
        self.stash_tab = "regular"
        self.material_kinds: set[int] = set()
        self.tab_toggle_works = True
        # The drop gesture (R117): ctrl+right-click sends an item to the
        # floor. The fake keeps what fell there, so tests can tell dropped
        # from vanished.
        self.dropped: list[CarriedItem] = []
        self.drop_works = True
        # The gold amount dialog raises NO panel flag (T37), so the fake
        # keeps it as hidden state — which is exactly the bot's problem: it
        # cannot see whether this is true before pressing Enter.
        self.gold_dialog = False

    # -- readers ---------------------------------------------------------------

    def player(self, session=None):
        return Player(
            name="MaqiuDoubing", level=91, act=1, position=self.pos, mode=1,
            hp=self.hp, max_hp=self.max_hp, mana=self.mana, max_mana=self.max_mana,
            stamina=586, max_stamina=586, experience=0, gold=self.gold,
            gold_stash=self.gold_stash, strength=122, dexterity=72,
            vitality=357, energy=31,
        )

    def carried(self, session=None):
        # The materials tab makes the ordinary stash read EMPTY (T15) — the
        # fake reproduces that, because it is the tab signal the loop relies
        # on and a fake that always listed the stash would hide every bug in
        # the tab logic.
        visible = self.stash if self.stash_tab == "regular" else []
        return CarriedItems(
            items=tuple(self.belt + self.inventory + visible), skipped=0
        )

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

    def _open_dialog(self, npc):
        self.panels.add(offsets.UI_NPCMENU)
        self.dialog_npc = npc
        self.dialog_row = 1  # a freshly opened menu always starts here

    @staticmethod
    def _same_potion_type(a, b) -> bool:
        return (
            a.is_healing_potion == b.is_healing_potion
            and a.is_mana_potion == b.is_mana_potion
            and a.is_rejuv_potion == b.is_rejuv_potion
        )

    def _belt_column_items(self, column):
        return [b for b in self.belt if b.belt_column == column]

    def _route_belt_column(self, item):
        """Where the game would put a shift-clicked potion: a column of its
        own type with room first, else an empty column, else nowhere.

        The old fake gave each TYPE a fixed capacity (healing 8, others 4),
        which is the R53 layout in disguise — it could not express the R178
        belt, where a mana potion squats in a healing column and eats a slot
        the capacity model still counted as free. Routing by column makes
        the squatter cost what it costs in the real game.
        """
        for column in range(offsets.BELT_COLUMNS):
            items = self._belt_column_items(column)
            if (
                items
                and all(self._same_potion_type(b, item) for b in items)
                and len(items) < offsets.BELT_ROWS
            ):
                return column
        for column in range(offsets.BELT_COLUMNS):
            if not self._belt_column_items(column):
                return column
        return None

    @property
    def dialog_rows(self) -> int:
        if self.dialog_npc == offsets.NPC_KASHYA:
            return 3 if self.merc_alive else 4  # resurrect only when dead
        return 3

    def click_world(self, x, y, **kwargs):
        self.world_clicks.append((x, y))
        if (x, y) == AKARA_POS:
            self._open_dialog(offsets.NPC_AKARA)
            if self.heal_on_interact:
                self.hp, self.mana = self.max_hp, self.max_mana
        elif (x, y) == KASHYA_POS:
            self._open_dialog(offsets.NPC_KASHYA)
        elif (x, y) == CHARSI_POS:
            self._open_dialog(offsets.NPC_CHARSI)
        elif (
            # Within a subtile or two of the tile, not exactly on it: an
            # object's sprite is drawn around its tile, which is the whole
            # premise of the aim ladder a retry walks (R161). An exact
            # match made the fake reject the very offsets the real game
            # accepts.
            max(abs(x - STASH_POS[0]), abs(y - STASH_POS[1])) <= 2
            and self.object_click_works
        ):
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

    def panel_click(self, panel_id, sx, sy, button="left", shift=False, ctrl=False):
        self.panel_clicks.append((panel_id, sx, sy, button, shift, ctrl))
        if ctrl and panel_id == offsets.UI_INVENTORY and button == "right":
            # Ctrl+right-click drops the item to the ground (R117). Routed
            # BEFORE the plain right-click branch: an unmodified reading of
            # this click would DRINK a potion — the R113 race's exact
            # hazard — so the fake must never fall through to it.
            index, item = self._item_at_pixel(sx, sy)
            if item is not None and self.drop_works:
                self.dropped.append(self.inventory.pop(index))
            return
        if panel_id == offsets.UI_STASH and not shift and button == "left":
            # Two different left-click targets live in this panel, so the
            # fake routes by POSITION as the game does — otherwise a gold
            # click would toggle the tab and every test would agree with a
            # bot that aimed anywhere at all.
            if (sx, sy) == _point_pixel("stash.gold_button"):
                self.gold_dialog = True  # invisible to perception (T37)
            elif (sx, sy) == _point_pixel("stash.materials_tab"):
                if self.tab_toggle_works:
                    self.stash_tab = (
                        "materials" if self.stash_tab == "regular" else "regular"
                    )
        elif panel_id == offsets.UI_STASH and shift and button == "right":
            index, item = self._item_at_pixel(sx, sy)
            if item is None or not self.deposit_works:
                return
            if item.kind in self.refuse_kinds:
                return
            # The GAME decides what the materials tab accepts — that is the
            # whole point of R75's design, so the fake refuses the rest
            # rather than quietly taking everything.
            if self.stash_tab == "materials" and item.kind not in self.material_kinds:
                return
            self.inventory.pop(index)
            if self.stash_tab == "regular":
                self.stash.append(stashed(item.unit_id))
        elif panel_id == offsets.UI_INVENTORY and not shift and button == "right":
            index, item = self._item_at_pixel(sx, sy)
            if item is not None and item.potion_name is not None:
                self.inventory.pop(index)  # drunk
        elif panel_id == offsets.UI_INVENTORY and shift:
            if self.refill_works:
                index, item = self._item_at_pixel(sx, sy)
                if item is None or item.potion_name is None:
                    return
                # The belt routes by COLUMN, and a refused click is how it
                # reports itself full. Without that, the fake would swallow
                # every potion ever offered and `fill_belt` would never
                # learn the belt was full — which is exactly how it decides
                # what counts as excess (R107).
                column = self._route_belt_column(item)
                if column is None:
                    return
                slot = column + offsets.BELT_COLUMNS * len(
                    self._belt_column_items(column)
                )
                moved = self.inventory.pop(index)
                self._uid += 1
                self.belt.append(
                    potion(900 + self._uid, moved.kind, belt_slot=slot)
                )

    def press_key(self, vk):
        self.pressed.append(vk)
        if vk == 0x49:  # VK_I
            self.panels.add(offsets.UI_INVENTORY)

    def panel_press_key(self, panel_id, vk):
        """NPC dialogs driven by keyboard exactly as T34 observed them.

        The highlight opens on row 1, Down advances it, and it WRAPS at the
        end — the wrap is what round 4 of that drill proved, and a fake that
        clamped instead would let through a bug the real game would not.

        Row 1 is always Talk (gossip: no panel change) and the last row is
        always Cancel. What row 2 does depends on WHOSE menu it is, and for
        Kashya on whether the merc is dead — which is the whole R56 hazard,
        so the fake reproduces it rather than smoothing it over.
        """
        self.pressed.append((panel_id, vk))
        if panel_id == offsets.UI_STASH and vk == 0x0D:  # VK_RETURN
            if self.gold_dialog:
                self.gold_stash += self.gold  # the dialog defaults to all
                self.gold = 0
                self.gold_dialog = False
            else:
                # An Enter with no dialog under it opens the chat console —
                # R89's mechanism from the other side, and the hazard the
                # gold step has to clean up after (T37).
                self.panels.add(offsets.UI_CHAT_CONSOLE)
            return
        if panel_id != offsets.UI_NPCMENU:
            return
        if vk == 0x28:  # VK_DOWN
            self.dialog_row = self.dialog_row % self.dialog_rows + 1
            return
        if vk != 0x0D:  # VK_RETURN
            return
        if self.dialog_row == self.dialog_rows:  # Cancel, always last
            self.panels.discard(offsets.UI_NPCMENU)
        elif self.dialog_row == 2 and self.dialog_npc == offsets.NPC_CHARSI:
            self.panels.add(offsets.UI_NPCSHOP)
        elif self.dialog_row == 2 and self.dialog_npc == offsets.NPC_KASHYA:
            if self.merc_alive:
                return  # row 2 is HIRE here — opens a list, resurrects nothing
            if self.resurrect_works:
                self.merc_alive = True
                # Paid from the person first, then the stash (R76).
                spend = min(self.gold, 50_000)
                self.gold -= spend
                self.gold_stash -= 50_000 - spend

    def press_escape(self):
        # ESC closes one panel per press, whichever it is — the fake must
        # not be choosier than the game, or a panel the layer fails to
        # close would look closed here (R85).
        #
        # "Whichever it is" INCLUDES slots nobody has named: a dialog box
        # is smaller than a panel and need not be on the blocking list at
        # all (R161, live — Warriv's travel prompt). Walking only
        # `blocking_panels()` here was the fake being choosier than the
        # game in exactly the way the comment above forbids.
        for panel_id in sorted(self.panels):
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


def layer(
    town_state,
    config=CALIBRATED,
    keep_item=None,
    protected_ids=None,
    carried=None,
    carried_with_sockets=None,
    narrate=None,
):
    clock = FakeClock()
    gated = SimpleNamespace(
        click_world=town_state.click_world, press_key=town_state.press_key
    )
    panel = SimpleNamespace(
        click=town_state.panel_click,
        press_key=town_state.panel_press_key,
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
        carried=carried if carried is not None else town_state.carried,
        carried_with_sockets=carried_with_sockets,
        read_player_fn=town_state.player,
        alert=town_state.alerts.append,
        notice=town_state.notices.append,
        clock=clock,
        sleep=clock.sleep,
        keep_item=keep_item,
        protected_ids=protected_ids,
        narrate=narrate,
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


def test_a_step_back_that_did_not_happen_is_tried_again(town):
    """2026-08-01: the run that died standing on the waypoint.

    `min_interact_range` exists because a click on the tile you are
    standing on does nothing in D2 — and the deliberate click that
    follows lands on a DISTANT object, which makes the character walk
    onto it. So the step-back was being issued and then quietly undone,
    and every retry re-clicked from the same hopeless spot: player at
    (5886, 5711), waypoint at (5884, 5709), three times, distance 2
    against a minimum of 4.

    A walk is a request. Asking once and assuming is the bug.
    """
    target = (5884, 5709)
    town.pos = (5886, 5711)  # distance 2: inside the minimum
    layer(town)._walk_near(target, minimum=4)
    assert len(town.walked) > 1, "it asked once and assumed the walk worked"


def test_a_step_back_that_worked_is_not_repeated(town):
    # The other half: verification must not turn one walk into three.
    target = (5884, 5709)
    town.pos = (5886, 5711)

    def walk(pos):
        town.walked.append(pos)
        town.pos = pos  # this fake actually moves, as the game would

    town_layer = layer(town)
    town_layer.walk_to = walk
    town_layer._walk_near(target, minimum=4)
    assert len(town.walked) == 1
    assert max(abs(town.pos[0] - target[0]), abs(town.pos[1] - target[1])) >= 4


def test_already_at_a_good_distance_still_walks_nowhere(town):
    # The shortest walk is none, and that has to survive the retry loop.
    town.pos = (5890, 5715)  # 6 away: inside the band, outside the minimum
    layer(town)._walk_near((5884, 5709), minimum=4)
    assert town.walked == []


def test_verification_polls_the_cheap_reader_and_decides_with_the_other(town):
    """Review 003: deciding may be expensive, verifying may not.

    `read_carried_items(with_sockets=True)` costs one stat read per
    main-inventory item, up to 40 — and the layer's verifications run
    inside `_await` at `poll_s`, so sharing one reader put ~1200 stat
    reads behind every transferred item, to answer a question that never
    needs sockets. Worse, the answer to the user's "the bot dithers"
    report was to halve `poll_s`, doubling that cost.

    The deposit shows both halves at once: one listing (a decision about
    each item, socket-conditioned) and then polling until each item is
    gone (existence only).
    """
    town.inventory = [loot(1, (2, 1)), loot(2, (4, 0))]
    counts = {"cheap": 0, "sockets": 0}

    def cheap(session):
        counts["cheap"] += 1
        return town.carried(session)

    def with_sockets(session):
        counts["sockets"] += 1
        return town.carried(session)

    town_layer = layer(town, carried=cheap, carried_with_sockets=with_sockets)
    town_layer.deposit_to_stash(lambda i: True, PreambleReport())
    assert counts["sockets"] == 1, "the expensive read is for the listing only"
    assert counts["cheap"] >= 2, "the per-item verification polls the cheap one"


def test_the_cleanse_still_gets_its_sockets(town):
    # The other direction, and the one that matters more: an item read
    # without sockets has `sockets=None`, which the permissive whitelist
    # reads as "keep" — so a cleanse on the cheap reader is a silent no-op
    # for exactly the socketed bases it exists to judge (R132).
    town.inventory = [loot(1, (2, 1))]
    seen = []

    def with_sockets(session):
        seen.append(1)
        return town.carried(session)

    town_layer = layer(
        town,
        keep_item=lambda i: False,  # everything is junk
        carried=town.carried,
        carried_with_sockets=with_sockets,
    )
    town_layer.cleanse_inventory(PreambleReport())
    assert seen, "the cleanse must decide from the sockets reader"


def test_one_injected_reader_serves_both(town):
    # A fake has no cheap/expensive distinction, so a caller who supplies
    # one reader must not have the real socket reader reached for behind
    # its back — that would hit a live session from a test.
    reader = town.carried
    town_layer = layer(town, carried=reader)
    assert town_layer._carried_sockets == reader


def test_deposit_needs_grid_calibration(town):
    """TownConfig ships the measured fractions (R60), so this explicitly
    strips them: an uncalibrated build must refuse, not guess."""
    town.inventory = [loot(1, (2, 1))]
    with pytest.raises(Uncalibrated):
        layer(town, UNCALIBRATED).deposit_to_stash(lambda i: True, PreambleReport())


def test_deposit_grid_pixel_math(town):
    town.inventory = [loot(1, (2, 1))]
    layer(town).deposit_to_stash(lambda i: True, PreambleReport())
    _, sx, sy, *_ = town.panel_clicks[0]
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


def test_refill_short_with_no_stock_logs_and_continues(town):
    """Emptiness is normal (user, R179): a shortfall the inventory cannot
    cover is a loud notice, never a halt — R178 halted a healthy run over
    exactly this, and R180 repeated it the same night."""
    town.belt = []
    town.inventory = [potion(30, 606, cell=(1, 1))]  # one healing, nothing else
    report = PreambleReport()
    layer(town).refill_belt(report)  # must NOT raise
    assert report.refilled == 1  # what stock there was got loaded
    assert town.alerts == []
    assert len(town.notices) == 1 and "belt short" in town.notices[0]


def test_refill_click_failure_with_stock_and_room_still_halts(town):
    """The halt that remains: stock in the inventory, an empty column to
    take it, and the potion still not landing — the clicks themselves are
    failing, which is worth a human."""
    town.belt = []
    town.inventory = [potion(30 + n, 606, cell=(n, 1)) for n in range(4)]
    town.refill_works = False
    with pytest.raises(BeltBelowMinimum):
        layer(town).refill_belt(PreambleReport())
    assert len(town.alerts) == 1 and "mechanically failing" in town.alerts[0]


def test_refill_r178_mixed_belt_refills_around_the_squatter(town):
    """The R178 belt: mana potions squatting in a healing column. The
    refill loads healing around them, the squatters count toward the MANA
    minimum where they sit, and nothing halts."""
    town.belt = [
        potion(20, 611, belt_slot=2), potion(21, 611, belt_slot=6),  # col 2
        potion(22, 606, belt_slot=3),  # one healing in col 3
    ]
    town.inventory = [potion(30 + n, 606, cell=(n, 1)) for n in range(3)]
    report = PreambleReport()
    layer(town).refill_belt(report)  # must NOT raise
    assert report.refilled == 3  # routed into col 3 around the squatters
    assert town.alerts == []
    carried = town.carried()
    assert sum(1 for i in carried.belt if i.is_healing_potion) == 4


def test_refill_fully_squatted_belt_continues_despite_stock(town):
    """Every column bottom-held by the wrong type: healing stock exists but
    has no home the game would route it to. Not a mechanical failure — the
    run continues and says so."""
    town.belt = [potion(20 + n, 611, belt_slot=n) for n in range(4)]  # 4 cols mana
    town.inventory = [potion(30 + n, 606, cell=(n, 1)) for n in range(4)]
    report = PreambleReport()
    layer(town).refill_belt(report)  # must NOT raise
    assert town.alerts == []
    assert len(town.notices) == 1 and "belt short" in town.notices[0]


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
    # Stripped explicitly: the shipped row is calibrated now, and what this
    # pins is the refusal — the row can only be measured in a dead-merc
    # window (R56), so a build that lacks it must halt and say so rather
    # than click into a menu whose layout it does not know.
    config = TownConfig(
        inventory_origin=(0.6, 0.4),
        inventory_cell=(0.02, 0.03),
        ui_points=points({"kashya.resurrect": None}),
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
    with pytest.raises(TownError, match=r"kashya\.resurrect:.*no effect"):
        layer(town).resurrect_merc_if_dead(PreambleReport())
    # Selection is by keyboard now (R104/R105): one Enter per attempt, and
    # each attempt reopens the dialog so the highlight is known.
    enters = [k for k in town.pressed if k == (offsets.UI_NPCMENU, 0x0D)]
    assert len(enters) == 1 + TownConfig().panel_click_retries
    assert len(town.alerts) == 1


# -- the inventory-management loop (R75) -------------------------------------------------


def full_belt(town_state):
    """A belt with no room left in any column.

    Needed by any test about DRINKING or stashing potions: the loop fills
    the belt first, so with room to spare a potion goes to the belt rather
    than down the hatch, and nothing is excess (R107).
    """
    town_state.belt = (
        [potion(500 + i, 606, belt_slot=i) for i in range(8)]  # healing x2 cols
        + [potion(520 + i, 611, belt_slot=8 + i) for i in range(4)]  # mana
        + [potion(540 + i, 530, belt_slot=12 + i) for i in range(4)]  # rejuv
    )


def test_the_loop_deposits_everything_in_one_pass_without_toggling(town):
    """R134/T45: a material self-routes from the REGULAR tab, so one pass on
    whatever tab is up empties the inventory and no toggle happens at all.

    R75's good idea survives intact — the GAME classifies the items, so the
    bot still needs no taxonomy to go stale. What went is the machinery that
    tried to identify the tab first. (The material here is a rune-shaped
    thing, not a rejuv: since R118 no potion is offered to the stash.)"""
    town.inventory = [loot(1, (0, 0), kind=800), loot(2, (1, 0), kind=522)]
    town.material_kinds = {800}  # the game accepts the rune, not the sword
    town.stash_tab = "regular"
    full_belt(town)

    report = PreambleReport()
    layer(town).manage_inventory(report)
    assert town.inventory == []  # everything left the inventory
    assert report.deposited == 2
    assert any("2 deposited on the displayed tab" in line for line in report.log)
    assert not any("after switching tab" in line for line in report.log)
    assert town.stash_tab == "regular"  # never toggled


def test_a_stash_opened_on_materials_self_heals_with_one_toggle(town):
    """The user's one foreseeable risk at the R134 gate, and the reason the
    design toggles at all. Starting on materials, the ordinary item bounces,
    the blind toggle happens, and the retry lands it — no halt, no human."""
    town.inventory = [loot(1, (0, 0), kind=800), loot(2, (1, 0), kind=522)]
    town.material_kinds = {800}
    town.stash_tab = "materials"
    full_belt(town)

    report = PreambleReport()
    layer(town).manage_inventory(report)
    assert town.inventory == []
    assert report.deposited == 2
    assert any("after switching tab" in line for line in report.log)
    assert town.stash_tab == "regular"


def test_an_empty_regular_stash_is_no_longer_a_problem(town):
    """The exact condition that killed stage B attempt 1.

    The old design toggled and counted the classic stash to identify the
    tab; on this character it lists nothing on either side, so it refused
    and the whole preamble died. Nothing asks the question now."""
    town.stash = []  # what a PD2 expanded-stash character actually looks like
    town.inventory = [loot(1, (0, 0), kind=522)]
    town.material_kinds = set()
    full_belt(town)

    report = PreambleReport()
    layer(town).manage_inventory(report)  # no raise
    assert town.inventory == [] and report.deposited == 1


def test_an_item_no_tab_wants_is_still_deposited_not_halted_on(town):
    """The old design's asymmetry — a bounce is normal in the materials
    phase, fatal in the regular one — is gone with the phases themselves.
    What has to survive it is the behaviour that asymmetry protected: an
    ordinary item the materials tab would never take must still be stashed
    without anything treating it as a fault."""
    town.inventory = [loot(1, (0, 0), kind=522)]
    town.material_kinds = set()  # materials takes nothing at all
    full_belt(town)

    report = PreambleReport()
    layer(town).manage_inventory(report)
    assert town.inventory == [] and report.deposited == 1
    assert not town.alerts


def test_potion_reserve_kept_and_excess_drunk_including_rejuvs(town):
    """R118 Q1/Q2: after the belt fills, up to `potion_reserve` (2) of each
    type stay in the inventory; EVERYTHING beyond that is drunk — rejuvs
    included, superseding R75's rejuvs-to-materials — and no potion is ever
    offered to the stash."""
    full_belt(town)
    town.inventory = (
        [potion(10 + i, 606, cell=(i, 0)) for i in range(3)]  # 3 healing
        + [potion(20 + i, 611, cell=(i, 1)) for i in range(3)]  # 3 mana
        + [potion(30 + i, 530, cell=(i, 2)) for i in range(3)]  # 3 rejuv
    )
    town.material_kinds = {530}  # the game WOULD take rejuvs; we never offer

    report = PreambleReport()
    layer(town).manage_inventory(report)
    assert any("drink: 3 excess" in line for line in report.log)
    kinds_left = sorted(i.kind for i in town.inventory)
    assert kinds_left == [530, 530, 606, 606, 611, 611]  # the reserve, intact
    assert report.deposited == 0  # not one potion was stashed
    assert town.stash == [stashed(9001), stashed(9002)]  # untouched


def test_reserve_within_cap_is_left_alone(town):
    """A reserve at or under the cap drinks nothing at all."""
    full_belt(town)
    town.inventory = [
        potion(1, 606, cell=(0, 0)), potion(2, 606, cell=(1, 0)),
        potion(3, 530, cell=(2, 0)),
    ]
    report = PreambleReport()
    layer(town).manage_inventory(report)
    assert not any("drink" in line for line in report.log)
    assert len(town.inventory) == 3


def test_the_cube_is_never_deposited_in_either_phase(town):
    """It opens on right-click instead of moving (R67), so an attempt would
    fail forever and trip the halt every run."""
    from pd2bot.offsets import UNMOVABLE_KINDS

    cube = sorted(UNMOVABLE_KINDS)[0]
    town.inventory = [loot(1, (0, 0), kind=cube)]
    full_belt(town)

    report = PreambleReport()
    layer(town).manage_inventory(report)  # no StashFull despite it remaining
    assert [i.unit_id for i in town.inventory] == [1]
    assert any("unmovable" in line for line in report.log)


def test_gold_is_deposited_and_verified_by_the_balance(town):
    """The dialog raises no panel flag (T37), so the balance is the only
    proof there is — and the dialog defaults to the whole carried amount."""
    town.gold, town.gold_stash = 12435, 805539
    full_belt(town)
    town.inventory = [loot(1, (0, 0))]

    report = PreambleReport()
    layer(town).manage_inventory(report)
    assert town.gold == 0 and town.gold_stash == 817974
    assert any("gold: 12435 deposited" in line for line in report.log)


def test_a_missed_gold_click_leaves_no_chat_console_behind(town):
    """The sharp edge of an invisible dialog: with none open, the ENTER is
    the key that opens the CHAT CONSOLE (R89 from the other side), and that
    is a blocking panel. A failed deposit must not leave one up."""
    town.gold, town.gold_stash = 500, 1000
    full_belt(town)
    town.inventory = [loot(1, (0, 0))]
    original = town.panel_click

    def gold_button_misses(panel_id, sx, sy, button="left", shift=False, ctrl=False):
        if (panel_id, sx, sy) == (offsets.UI_STASH, *_point_pixel("stash.gold_button")):
            town.panel_clicks.append((panel_id, sx, sy, button, shift, ctrl))
            return  # the click lands on nothing; no dialog opens
        original(panel_id, sx, sy, button, shift, ctrl)

    town.panel_click = gold_button_misses
    with pytest.raises(TownError, match="gold deposit had no effect"):
        layer(town).manage_inventory(PreambleReport())
    assert town.gold == 500  # nothing moved
    assert offsets.UI_CHAT_CONSOLE not in town.panels  # and nothing left open


def test_no_carried_gold_is_not_an_error(town):
    """Every other game will have nothing to bank — that is normal, not a
    failure, and must not cost a click."""
    town.gold = 0
    full_belt(town)
    town.inventory = [loot(1, (0, 0))]

    report = PreambleReport()
    layer(town).manage_inventory(report)
    assert any("gold: none carried" in line for line in report.log)
    gold_clicks = [
        c for c in town.panel_clicks
        if (c[0], c[1], c[2]) == (offsets.UI_STASH, *_point_pixel("stash.gold_button"))
    ]
    assert gold_clicks == []


def test_a_refusal_on_both_tabs_is_a_full_stash(town):
    """Once a refusal has survived the toggle, the tab is no longer a
    candidate explanation — so this is the genuine full-stash case, and it
    must still halt loudly."""
    town.inventory = [loot(1, (0, 0), kind=522)]
    town.deposit_works = False
    full_belt(town)

    with pytest.raises(StashFull, match="both deposit passes"):
        layer(town).manage_inventory(PreambleReport())
    assert town.alerts
    # The message must not name a container it cannot measure.
    assert any("materials tab cannot be measured" in a for a in town.alerts)


# -- the preamble ------------------------------------------------------------------------


def test_preamble_runs_in_the_agreed_order(town):
    """R46 Q5's order with repair after the heal (R70), and the middle now
    served by the R75 loop rather than a deposit + refill pair — so the belt
    is reported from inside the loop, before the stash phases."""
    town.inventory = [loot(1, (2, 1))]
    _stock_belt_at_minimums(town)
    report = layer(town).run_preamble()
    assert report.healed and report.deposited == 1
    assert report.merc_action == "not_needed"
    steps = [line.split(":")[0] for line in report.log]
    # One "stash" line, not two: the materials/regular split went with the
    # tab inference (R134). Nothing toggles unless something refuses, so the
    # happy path reports a single deposit pass.
    # The "cleanse" line is there even though this preamble drops nothing:
    # the cleanse reports on every path now, because a run where junk
    # reached the stash used to be indistinguishable from one where the
    # cleanse looked and found none (user request, 2026-08-01).
    assert steps == [
        "heal", "repair", "belt", "cleanse", "belt",
        "stash", "stash", "gold", "merc"
    ]  # two stash lines: the deposit, then the held-item count


def test_preamble_narrates_each_station_with_its_duration(town):
    """The narrative log (R179): one line per station, each carrying what
    its report lines said and how long it took — the answer to "what was
    it doing while it dawdled at Akara?"."""
    import re

    town.inventory = [loot(1, (2, 1))]
    _stock_belt_at_minimums(town)
    lines = []
    layer(town, narrate=lines.append).run_preamble()
    assert len(lines) == 4  # heal, repair, inventory, merc — never per poll
    assert lines[0].startswith("heal:")
    assert lines[-1].startswith("merc:")
    assert all(re.search(r"\(\d+\.\ds\)$", line) for line in lines)


def test_preamble_narrates_a_station_failure(town):
    town.akara_present = False
    town.heal_on_interact = False
    lines = []
    with pytest.raises(TownError):
        layer(town, narrate=lines.append).run_preamble()
    assert len(lines) == 1 and lines[0].startswith("heal: FAILED after ")


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
    """Charm-space potions are not stock: nothing is clickable, so the
    shortfall is a no-stock notice (R179), not a mechanical halt."""
    town.belt = [potion(20, 610, belt_slot=0), potion(21, 611, belt_slot=4)]
    town.inventory = [
        CarriedItem(50 + n, 606, 2, offsets.ITEM_MODE_IN_STORAGE,
                    offsets.STORAGE_INVENTORY, offsets.NODE_STORAGE, (n, 5), 1)
        for n in range(6)
    ]
    report = PreambleReport()
    layer(town).refill_belt(report)  # must NOT raise
    assert town.panel_clicks == []  # nothing was clickable
    assert town.alerts == []
    assert len(town.notices) == 1 and "belt short" in town.notices[0]


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


def test_a_repeating_misclick_provokes_a_sidestep(town):
    """R111, live in T27: the navigator clicks TOWARD the destination, so an
    object on that line gets clicked instead of walked past — and closing the
    panel and re-walking aims down the same line at the same object. The
    waypoint sits almost in front of Akara, so every travel click toward her
    rakes across it. A step sideways changes the angle."""
    from pd2bot.navigate import NavigationError

    destination = (5921, 5711)
    attempts = []

    def walk(pos):
        attempts.append(pos)
        if pos == destination and len(attempts) < 4:
            town.panels.add(offsets.UI_WPMENU)  # clipped the waypoint again
            raise NavigationError("input stayed refused: a blocking panel is open")
        town.walked.append(pos)

    step = layer(town)
    step.walk_to = walk
    step._walk_guarded(destination)
    aside = [p for p in attempts if p != destination]
    assert aside, "never stepped aside; it just repeated the same approach"
    # And the sidestep is perpendicular to the route, not toward it.
    px, py = town.player().position
    dx, dy = destination[0] - px, destination[1] - py
    ox, oy = aside[0][0] - px, aside[0][1] - py
    assert abs(dx * ox + dy * oy) < abs(dx * dy) + 1  # near-zero dot product


def test_a_known_obstacle_is_routed_around_not_merely_stepped_past(town):
    """R111's second lesson. A small sidestep does nothing when the obstacle
    is close — after the first misclick the character is standing beside it,
    and 7 subtiles barely moves the angle. T27 proved that live: the waypoint
    sits at the same y as Akara's approach point, dead on the route, and four
    recoveries all clicked it again. So when the panel names a known object,
    the detour goes around THAT."""
    from pd2bot.navigate import NavigationError

    destination = (5917, 5709)
    waypoint = CALIBRATED.object_positions[offsets.OBJ_WAYPOINT_A1]
    attempts = []

    def walk(pos):
        attempts.append(pos)
        if pos == destination and len(attempts) < 4:
            town.panels.add(offsets.UI_WPMENU)
            raise NavigationError("input stayed refused: a blocking panel is open")
        town.walked.append(pos)

    step = layer(town)
    step.walk_to = walk
    step._walk_guarded(destination)

    detours = [p for p in attempts if p != destination]
    assert detours, "never detoured"
    # The detour is measured from the OBSTACLE, not from the player — that is
    # what makes it big enough to change the approach angle.
    near_waypoint = min(
        max(abs(p[0] - waypoint[0]), abs(p[1] - waypoint[1])) for p in detours
    )
    assert near_waypoint <= CALIBRATED.detour + 1


def test_the_first_recovery_does_not_sidestep(town):
    """One interruption may be bad luck — a bystander wandering across the
    route. Only a REPEAT means the route itself is the problem, and a
    sidestep on every recovery would add a detour to ordinary town traffic."""
    from pd2bot.navigate import NavigationError

    destination = (5921, 5711)
    attempts = []

    def walk(pos):
        attempts.append(pos)
        if len(attempts) == 1:
            town.panels.add(offsets.UI_NPCMENU)
            raise NavigationError("input stayed refused: npc_menu open")
        town.walked.append(pos)

    step = layer(town)
    step.walk_to = walk
    step._walk_guarded(destination)
    assert attempts == [destination, destination]  # retried, no detour


def test_walk_gives_up_after_bounded_dialog_recoveries(town):
    from pd2bot.navigate import NavigationError

    def walk(pos):
        town.panels.add(offsets.UI_NPCMENU)
        raise NavigationError("input stayed refused: npc_menu open")

    step = layer(town)
    step.walk_to = walk
    with pytest.raises(TownError, match="kept opening panels"):
        step._walk_guarded((5900, 5700))


def test_walk_recovers_from_any_blocking_panel_not_just_dialogs(town):
    """A travel click can open something no town step ever opens. During
    T19 it hit the WAYPOINT (R85), whose panel blocks input just as hard as
    an NPC dialog — but town.py listed only three panels and so could
    neither recognise nor close it, and the walk died as a bare
    NavigationError. The recovery list now comes from `uistate`."""
    from pd2bot.navigate import NavigationError

    attempts = []

    def walk(pos):
        attempts.append(pos)
        if len(attempts) == 1:
            town.panels.add(offsets.UI_WPMENU)
            raise NavigationError("input stayed refused: a blocking panel is open")
        town.walked.append(pos)

    step = layer(town)
    step.walk_to = walk
    step._walk_guarded((5900, 5700))
    assert len(attempts) == 2
    assert offsets.UI_WPMENU not in town.panels


def test_a_swallowed_escape_is_retried(town):
    """R94: a key sent while a panel is still animating in is swallowed just
    as a click is. T27 died at its first step on exactly this — the heal
    opens Akara's dialog and closes it immediately, so the ESC arrived mid
    animation and one 3-second wait declared the panel unclosable."""
    town.panels.add(offsets.UI_NPCMENU)
    presses = {"n": 0}

    def swallow_the_first(_town=town):
        presses["n"] += 1
        if presses["n"] > 1:  # the first press is lost to the animation
            _town.panels.discard(offsets.UI_NPCMENU)

    town.press_escape = swallow_the_first
    layer(town).close_panels()
    assert presses["n"] == 2 and offsets.UI_NPCMENU not in town.panels


def test_a_panel_that_never_closes_still_fails_loudly(town):
    """Retrying must not become trying forever — a genuinely stuck panel is
    a human problem and has to say so, naming what is still up."""
    town.panels.add(offsets.UI_NPCMENU)
    town.press_escape = lambda: None
    with pytest.raises(TownError, match="closing npc_menu with ESC: no effect"):
        layer(town).close_panels()


def test_row_two_means_something_different_when_the_merc_lives(town):
    """R105, the hazard in concrete form. Kashya dead: TALK / RESURRECT /
    HIRE / CANCEL. Kashya alive: TALK / HIRE / CANCEL — so row 2 stops being
    Resurrect and becomes HIRE. The index is stable; its MEANING is not, and
    that is why the step re-confirms the merc is dead immediately before
    selecting rather than trusting the check it made earlier."""
    town.merc_alive = True
    town._open_dialog(offsets.NPC_KASHYA)
    assert town.dialog_rows == 3  # no resurrect row while the merc lives

    town.merc_alive = False
    town._open_dialog(offsets.NPC_KASHYA)
    assert town.dialog_rows == 4

    # And the guard: a merc that comes back to life between the outer check
    # and the selection must abort, not press Enter on row 2.
    town.merc_alive = False
    step = layer(town)
    original = step.snapshot
    reads = {"n": 0}

    def alive_by_the_time_the_dialog_is_open():
        # Dead for the step's opening check, alive by the re-confirm — the
        # window the guard exists to cover.
        reads["n"] += 1
        snap = original()
        if reads["n"] >= 2:
            town.merc_alive = True
        return snap

    step.snapshot = alive_by_the_time_the_dialog_is_open
    with pytest.raises(TownError, match="merc reads alive"):
        step.resurrect_merc_if_dead(PreambleReport())
    assert (offsets.UI_NPCMENU, 0x0D) not in town.pressed  # no Enter was sent


def test_reaching_an_object_survives_a_dialog_opened_en_route(town):
    """R106, live in T35: a travel click that lands on a bystander opens
    their dialog, and if that happens on the LAST click of the walk the walk
    still succeeds — so the panel is still up when the deliberate click
    comes, and `GatedInput` refuses it outright. The NPC path has always
    coped with this; the object path did not."""
    step = layer(town)
    town.panels.add(offsets.UI_NPCMENU)  # waylaid on the way to the stash
    step.open_object_panel(offsets.OBJ_STASH, "the stash", offsets.UI_STASH)
    assert offsets.UI_STASH in town.panels
    assert offsets.UI_NPCMENU not in town.panels  # cleared, not clicked through


def test_a_keyboard_row_ignores_where_the_npc_is(town):
    """R104, the whole point: an ordinal survives what no position could.
    Charsi pacing moved every stored pixel and broke every calibration; it
    cannot move which option is second."""
    from pd2bot.uipoints import UIPoint

    point = UIPoint(
        "test.row", offsets.UI_NPCMENU, opens=offsets.UI_NPCSHOP,
        anchor_npc=offsets.NPC_CHARSI, keyboard_row=2, row_count=3,
    )
    step = layer(town, TownConfig(ui_points={point.name: point}))
    town.panels.add(offsets.UI_NPCMENU)
    globals()["CHARSI_POS"] = (5900, 5800)  # nowhere near where she was
    try:
        step.click_point(point)
    finally:
        globals()["CHARSI_POS"] = (5824, 5724)
    assert offsets.UI_NPCSHOP in town.panels
    assert town.panel_clicks == []  # nothing was clicked at all


def test_a_keyboard_retry_reopens_rather_than_pressing_on(town):
    """The count only means anything from a freshly opened menu, where the
    highlight is known to be on row 1. After a failed attempt it could be
    anywhere, and pressing on from an unknown position selects something
    nobody intended — which at Kashya costs 50,000 gold."""
    from pd2bot.uipoints import UIPoint

    point = UIPoint(
        "test.row", offsets.UI_NPCMENU, opens=offsets.UI_NPCSHOP,
        anchor_npc=offsets.NPC_CHARSI, keyboard_row=2, row_count=3,
    )
    def reopen(x, y, **kwargs):
        town.world_clicks.append((x, y))
        town._open_dialog(offsets.NPC_CHARSI)  # resets the highlight to row 1
        return (0, 0)

    # Bind the fake BEFORE building the layer: `layer()` captures the method
    # by value, so a later assignment would never be seen.
    town.click_world = reopen
    step = layer(town, TownConfig(ui_points={point.name: point}))
    town._open_dialog(offsets.NPC_CHARSI)
    town.dialog_row = 3  # a stale highlight, as a failed attempt would leave

    step.click_point(point)
    assert offsets.UI_NPCSHOP in town.panels
    assert town.world_clicks, "the retry must reopen the dialog, not press on"


def test_an_npc_anchored_row_moves_with_the_npc(town):
    """R97, the defect behind the whole T19/T27 history: an NPC dialog row
    is drawn relative to the NPC, and NPCs wander. A stored screen position
    is therefore a snapshot of one accidental arrangement — which is why
    three separately verified fractions each worked once and then failed.
    The click target must be recomputed from where the NPC is NOW."""
    from pd2bot.uipoints import UIPoint

    point = UIPoint(
        "test.row", offsets.UI_NPCMENU,
        anchor_npc=offsets.NPC_CHARSI, npc_offset=(8, -211),
    )
    step = layer(town, TownConfig(ui_points={point.name: point}))

    here = step.point_pixel(point)
    # Charsi takes a few steps; nothing else changes.
    globals()["CHARSI_POS"] = (CHARSI_POS[0] + 6, CHARSI_POS[1] - 4)
    try:
        there = step.point_pixel(point)
    finally:
        globals()["CHARSI_POS"] = (5824, 5724)
    assert here != there, "the row must follow the NPC, not stay put"


def test_an_npc_anchored_row_refuses_when_the_npc_is_out_of_range(town):
    """Better to fail naming the reason than to click a projected guess:
    without the NPC there is no anchor, and the row could be anywhere."""
    from pd2bot.uipoints import UIPoint

    point = UIPoint(
        "test.row", offsets.UI_NPCMENU,
        anchor_npc=offsets.NPC_CHARSI, npc_offset=(8, -211),
    )
    town.charsi_present = False
    step = layer(town, TownConfig(ui_points={point.name: point}))
    with pytest.raises(TownError, match="not in perception range"):
        step.point_pixel(point)


def test_a_screen_anchored_point_ignores_the_npcs(town):
    """The waypoint list and the stash really are fixed furniture — proven
    live (T26, T16) — so they must not acquire NPC-dependent behaviour."""
    from pd2bot.uipoints import UIPoint

    point = UIPoint("test.fixed", offsets.UI_STASH, fraction=(0.5, 0.5))
    step = layer(town, TownConfig(ui_points={point.name: point}))
    before = step.point_pixel(point)
    town.charsi_present = False
    assert step.point_pixel(point) == before


def test_closing_panels_covers_every_blocking_panel(town):
    """The close list and the guard's refuse list must be the same list —
    a panel in one and not the other is a panel the layer cannot clear."""
    for panel_id in uistate.blocking_panels():
        town.panels.add(panel_id)
    layer(town).close_panels()
    assert town.panels == set()


# -- repair (R70) -------------------------------------------------------------


def worn(uid, current, maximum):
    from pd2bot.perception.items import Durability

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
    # The trade row is chosen by ordinal now, not by position (R104), so it
    # takes a row index; the repair-all button lives in the shop panel,
    # which really is fixed furniture, and stays a fraction.
    ui_points=points(
        {"charsi.trade_repair": 2, "charsi.repair_all": (0.20, 0.80)}
    ),
)


def test_repair_skips_slight_wear(town, monkeypatch):
    """R186 superseded R71's repair-every-game: run 4 paid a 33 s Charsi
    trip to restore ONE durability point. Above `repair_below_pct` the
    trip buys nothing a later run will not buy cheaper."""
    with_durability(town, monkeypatch, [worn(1, 99, 100)])
    report = PreambleReport()
    layer(town, REPAIR_CFG).repair_at_charsi(report)
    assert report.repaired == 0 and town.world_clicks == []
    assert any("nothing damaged" in line for line in report.log)


def test_repair_goes_when_wear_crosses_the_threshold(town, monkeypatch):
    items = [worn(1, 65, 100)]  # 65% <= repair_below_pct 70
    with_durability(town, monkeypatch, items)
    charsi = CALIBRATED.npc_positions[offsets.NPC_CHARSI]

    def click_world(x, y, **kwargs):
        town.world_clicks.append((x, y))
        if (x, y) == charsi:
            town._open_dialog(offsets.NPC_CHARSI)
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
    # "nothing DAMAGED", not "nothing worn": this character has an item on,
    # it just does not need Charsi. The old wording contradicted the count
    # in its own parenthesis on a live run.
    assert any("nothing damaged" in line for line in report.log)


def test_repair_refuses_without_calibration(town, monkeypatch):
    """An uncalibrated point must refuse rather than guess — and refuse
    BEFORE the walk, since crossing town first buys nothing (R87)."""
    with_durability(town, monkeypatch, [worn(1, 5, 100)])
    # Stripped explicitly rather than relying on what happens to ship
    # uncalibrated today: the point is the refusal, not the inventory.
    bare = TownConfig(ui_points=points({"charsi.trade_repair": None}))
    with pytest.raises(Uncalibrated, match=r"charsi\.trade_repair is not calibrated"):
        layer(town, bare).repair_at_charsi(PreambleReport())
    assert town.walked == [] and town.world_clicks == []


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
            town._open_dialog(offsets.NPC_CHARSI)
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
    # The dialog row is chosen by KEYBOARD now (1 Down, then Enter, for row 2
    # of 3) and only the shop's repair-all button is clicked (R104).
    assert [c[0] for c in town.panel_clicks] == [offsets.UI_NPCSHOP]
    assert (offsets.UI_NPCMENU, 0x28) in town.pressed  # a Down
    assert (offsets.UI_NPCMENU, 0x0D) in town.pressed  # then Enter
    assert all(d.missing == 0 for d in items)


def test_repair_halts_when_durability_does_not_recover(town, monkeypatch):
    """A clicked button that repaired nothing means the row or the button
    moved — NPC menus are state-dependent (R56), so this must be loud."""
    with_durability(town, monkeypatch, [worn(1, 5, 100)])
    charsi = CALIBRATED.npc_positions[offsets.NPC_CHARSI]

    def click_world(x, y, **kwargs):
        town.world_clicks.append((x, y))
        if (x, y) == charsi:
            town._open_dialog(offsets.NPC_CHARSI)
        return (0, 0)

    def panel_click(panel_id, sx, sy, button="left", shift=False):
        town.panel_clicks.append((panel_id, sx, sy, button, shift))
        if panel_id == offsets.UI_NPCMENU:
            town.panels.add(offsets.UI_NPCSHOP)
        # repair-all does nothing: the button moved

    town.click_world = click_world
    town.panel_click = panel_click
    town.press_escape = lambda: town.panels.clear()

    with pytest.raises(TownError, match=r"charsi\.repair_all:.*no effect"):
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
            town._open_dialog(offsets.NPC_CHARSI)
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
        offsets.UI_NPCMENU, lambda: (768, 432), lambda: True, what="a row"
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
            offsets.UI_NPCMENU, lambda: (768, 432), lambda: False, what="a row"
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
            offsets.UI_NPCMENU, lambda: (768, 432), lambda: False, what="a row"
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
            offsets.UI_NPCMENU, lambda: (768, 432), lambda: False, what="a row"
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


def test_a_misclick_dialog_is_closed_and_the_retry_differs(town):
    """R161, the user's rule after watching a run lock itself out.

    Warriv stood between the character and the stash, so the deliberate
    click hit HIM. His dialog opened — not the stash — the wait reported
    "no panel", and the character never moved because the NPC ate the
    click. The next attempt closed the dialog, re-approached the same
    side, and clicked the same pixel. Three times.

    *Check for unexpected dialogs/screens, close them immediately if they
    are not the current expected target, move the mouse pointer a little,
    and click elsewhere.* So: the stray dialog is closed, and the retry
    must stand somewhere else and aim somewhere else — a retry that
    cannot differ from the attempt it retries is not a retry.
    """
    aimed: list[tuple[int, int]] = []
    original = town.click_world

    def click_world(x, y, **kwargs):
        aimed.append((x, y))
        if len(aimed) == 1:
            # The misclick: a bystander's dialog opens instead.
            town.panels.add(offsets.UI_NPCMENU)
            return (0, 0)
        return original(x, y, **kwargs)

    town.click_world = click_world
    layer(town).open_object_panel(offsets.OBJ_STASH, "the stash", offsets.UI_STASH)

    assert offsets.UI_NPCMENU not in town.panels, "the stray dialog was left open"
    assert offsets.UI_STASH in town.panels
    assert len(aimed) >= 2 and aimed[0] != aimed[1], "the retry repeated itself"


def test_stray_ui_is_cleared_even_when_it_is_not_a_blocking_panel(town):
    # "not just panel — dialog boxes too (smaller than panels)". A dialog
    # need not be in the BLOCKING list to be in the way, and `close_panels`
    # only walks that list, so anything open that is not our target counts.
    town.panels.add(0x21)  # an unmodelled slot: a dialog nobody has named
    found = layer(town)._clear_stray_ui(keep=offsets.UI_STASH)
    assert "ui_0x21" in found
    assert town.panels == set()


def test_the_automap_is_not_treated_as_an_obstacle(town):
    # It takes no clicks and the human may well have left it on. "Close
    # everything that is open" would fight them for it on every retry.
    town.panels.add(offsets.UI_AUTOMAP)
    assert layer(town)._clear_stray_ui(keep=offsets.UI_STASH) == ""
    assert offsets.UI_AUTOMAP in town.panels


def test_clearing_stray_ui_keeps_the_panel_we_asked_for(town):
    town.panels.add(offsets.UI_STASH)
    assert layer(town)._clear_stray_ui(keep=offsets.UI_STASH) == ""
    assert offsets.UI_STASH in town.panels


def test_a_failed_object_panel_reports_every_attempt(town):
    """2026-08-01: two identical live failures the message could not explain.

    All it could say was where the character finished, and that fitted
    three different stories — the standoff never achieved, the click never
    sent, or the click sent and ignored. Two of the three were wrong, and
    each cost a supervised run to find out. T49 then opened the same panel
    first try in isolation, so whatever this is only happens in context,
    and the context is the thing that has to be recorded.
    """
    town.object_click_works = False
    with pytest.raises(TownError) as failure:
        layer(town).open_object_panel(
            offsets.OBJ_STASH, "the stash", offsets.UI_STASH
        )
    message = str(failure.value)
    assert message.count("#") == CALIBRATED.interact_retries + 1, message
    for expected in ("d=", "want ", "panels ", "clicked ", "ended "):
        assert expected in message, f"{expected!r} missing from: {message}"


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


# -- the inventory cleanse (R117) -------------------------------------------------


def junk_only(item):
    """A whitelist that recognises nothing: everything non-potion is junk."""
    return False


def test_cleanse_drops_junk_and_stashes_the_rest(town):
    """Junk goes to the FLOOR, keepers go to the stash — and the whitelist
    is what tells them apart."""
    town.inventory = [
        loot(1, (0, 0), kind=999),  # a keeper (the whitelist says so)
        loot(2, (1, 0), kind=700),  # junk
    ]
    full_belt(town)
    report = PreambleReport()
    # Explicit empty baseline: this test is about the DROP, not the
    # protection default (review 001), so it opts out deliberately.
    layer(
        town, keep_item=lambda item: item.kind == 999,
        protected_ids=lambda: set(),
    ).manage_inventory(report)
    assert [i.kind for i in town.dropped] == [700]
    assert town.inventory == []
    assert report.deposited == 1  # the keeper, stashed as usual
    # The report names what went on the floor and what stayed, and why.
    # "1 dropped" alone is not something the keep-rule can be checked
    # against; a kind is.
    assert any("1 judged junk" in line and "1 dropped" in line
               for line in report.log), report.log
    assert any("cleanse: DROP kind 700" in line for line in report.log), report.log
    assert any("cleanse: KEEP kind 999" in line and "whitelisted" in line
               for line in report.log), report.log


def test_cleanse_disabled_without_a_whitelist(town):
    """No whitelist wired (pickit vocabulary still has pending ids): nothing
    is EVER dropped — everything falls through to the stash as before."""
    town.inventory = [loot(1, (0, 0), kind=700)]
    full_belt(town)
    report = PreambleReport()
    layer(town).manage_inventory(report)
    assert town.dropped == []
    assert report.deposited == 1
    # And it SAYS SO. This was the worst of the three silent paths: a
    # cleanse that examined nothing at all looked exactly like a cleanse
    # that examined everything and approved of it.
    assert any("DISABLED" in line for line in report.log), report.log


def test_the_cleanse_says_why_each_item_survived(town):
    """The user's rule is that only whitelisted items and the Cube stay.

    That rule is only checkable if the report says which reason applied to
    each survivor — and "protected: predates this bot session" is the one
    worth surfacing, because it is the likeliest reason junk the user
    wants gone survives a cleanse indefinitely: the baseline is captured
    at the first cleanse and protects everything present then, for the
    whole session.
    """
    town.inventory = [
        loot(1, (0, 0), kind=999),  # whitelisted
        loot(2, (1, 0), kind=700),  # junk, but predates the session
    ]
    full_belt(town)
    report = PreambleReport()
    layer(
        town, keep_item=lambda item: item.kind == 999,
        protected_ids=lambda: {2},
    ).manage_inventory(report)
    assert town.dropped == [], "a protected item must not be dropped"
    reasons = [line for line in report.log if line.startswith("cleanse: KEEP")]
    assert any("kind 700" in r and "predates" in r for r in reasons), reasons
    assert any("kind 999" in r and "whitelisted" in r for r in reasons), reasons
    assert any("0 judged junk" in line for line in report.log), report.log


def test_cleanse_never_drops_potions_or_unmovables(town):
    """The reserve potions and the Cube survive even a whitelist that
    recognises nothing: potions are the town loop's business, and the Cube
    cannot survive the gesture (R67)."""
    from pd2bot.offsets import UNMOVABLE_KINDS

    cube = sorted(UNMOVABLE_KINDS)[0]
    town.inventory = [
        potion(1, 606, cell=(0, 0)),
        loot(2, (1, 0), kind=cube),
    ]
    full_belt(town)
    report = PreambleReport()
    layer(town, keep_item=junk_only).manage_inventory(report)
    assert town.dropped == []
    kinds_left = sorted(i.kind for i in town.inventory)
    assert kinds_left == sorted([606, cube])


def test_drop_refuses_with_the_stash_open(town):
    """Gesture meaning depends on open panels (R64): a drop sent with the
    stash up could quick-move instead. The layer refuses outright."""
    town.panels.add(offsets.UI_STASH)
    item = loot(1, (0, 0), kind=700)
    town.inventory = [item]
    with pytest.raises(TownError, match="stash open"):
        layer(town).drop_item(item)
    assert town.dropped == []


def test_a_stuck_drop_alerts_and_leaves_the_item_to_the_stash(town):
    """Failing to drop junk costs stash space, not correctness: alert,
    leave it, let the stash phases take it — never halt the preamble over
    garbage."""
    town.inventory = [loot(1, (0, 0), kind=700)]
    town.drop_works = False
    full_belt(town)
    report = PreambleReport()
    layer(
        town, keep_item=junk_only, protected_ids=lambda: set()
    ).manage_inventory(report)
    assert town.dropped == []
    assert any("would not drop" in alert for alert in town.alerts)
    assert town.inventory == []  # the stash phases still took it
    assert report.deposited == 1


def test_cleanse_never_drops_protected_items(town):
    """The startup baseline is untouchable (R128).

    Several keep-list items can only be CRAFTED, so the whitelist can
    never learn their ids from a live pickup — and one sitting in the
    inventory would look exactly like junk. The bot is only ever cleaning
    up its own accidents, so anything it did not pick up this session is
    off limits regardless of what the whitelist says.
    """
    heirloom = loot(1, (0, 0), kind=9999)  # unrecognised AND irreplaceable
    accident = loot(2, (1, 0), kind=700)
    town.inventory = [heirloom, accident]
    full_belt(town)

    report = PreambleReport()
    layer(
        town, keep_item=junk_only, protected_ids=lambda: {1}
    ).manage_inventory(report)
    assert [i.kind for i in town.dropped] == [700]  # only the accident fell


def test_cleanse_protects_everything_when_no_baseline_is_wired(town):
    """The safe default (review 001): a caller that supplies a whitelist
    but forgets the baseline must NOT get the most destructive setting.

    T43's audit showed the stakes on real data — 4 of 12 carried items
    would have been dropped, one of them a magic grand charm. Half-done
    wiring should cost nothing, not everything.
    """
    town.inventory = [loot(1, (0, 0), kind=700), loot(2, (1, 0), kind=701)]
    full_belt(town)
    report = PreambleReport()
    # keep_item recognises nothing; protected_ids deliberately omitted.
    layer(town, keep_item=junk_only).manage_inventory(report)
    assert town.dropped == []  # nothing fell


def test_the_implicit_baseline_still_cleans_later_accidents(town):
    """Protecting the startup set must not make the cleanse useless: an
    item picked up AFTER that point is still junk and still goes."""
    town.inventory = [loot(1, (0, 0), kind=700)]
    full_belt(town)
    layer_under_test = layer(town, keep_item=junk_only)

    # First pass captures the baseline and drops nothing.
    layer_under_test.cleanse_inventory(PreambleReport())
    assert town.dropped == []

    # An accidental pickup arrives afterwards.
    town.inventory.append(loot(99, (2, 0), kind=702))
    layer_under_test.cleanse_inventory(PreambleReport())
    assert [i.kind for i in town.dropped] == [702]


# -- stash pressure (R132) --------------------------------------------------------


def _pressing(town, count):
    """A character holding `count` stashed items, in the container PD2
    actually uses (location 8 — location 7 is empty on this character, which
    is the whole T45 story)."""
    town.stash = [stashed(9000 + i) for i in range(count)]
    town.inventory = [loot(1, (0, 0))]
    full_belt(town)


def test_stash_pressure_warns_before_the_stash_is_actually_full(town):
    """Give the human notice while there is still room to act.

    `StashFull` is a hard stop the bot cannot work around, so the first
    warning about a filling stash should not BE that stop.
    """
    _pressing(town, TownConfig().stash_pressure_at + 5)
    report = PreambleReport()
    layer(town).manage_inventory(report)
    assert any("items stashed" in line for line in report.log)
    assert any("stash pressure" in n for n in town.notices)


def test_stash_pressure_is_a_notice_not_a_halt_alert(town):
    """T27's first live run printed the HALT banner for a warning that halts
    nothing — the drill sailed past it and passed while the console said the
    bot was waiting for a human. An alert that lies about severity is worse
    than no alert."""
    _pressing(town, TownConfig().stash_pressure_at + 5)
    layer(town).manage_inventory(PreambleReport())
    assert town.notices and town.alerts == []


def test_stash_pressure_warns_once_per_session_not_once_per_run(town):
    """A warning that repeats every game is noise, and noise is how people
    learn to ignore alerts."""
    _pressing(town, TownConfig().stash_pressure_at + 5)
    town_layer = layer(town)
    for _ in range(3):
        town.inventory = [loot(1, (0, 0))]
        town_layer.manage_inventory(PreambleReport())
    assert len(town.notices) == 1


def test_no_stash_pressure_warning_with_room_to_spare(town):
    _pressing(town, 10)
    report = PreambleReport()
    layer(town).manage_inventory(report)
    assert town.notices == [] and town.alerts == []


def test_stash_pressure_is_a_warning_and_never_a_halt(town):
    """It is a count, not an occupancy — item sizes are unreadable (P1) —
    so it must never be the thing that stops a run."""
    _pressing(town, TownConfig().stash_pressure_at + 50)
    report = PreambleReport()
    layer(town).manage_inventory(report)  # no raise
    assert report.deposited == 1


# -- the drop gesture's blast radius (stage B run 4) ------------------------------


def test_the_cleanse_never_aims_at_a_tome(town):
    """Run 4 opened a town portal, which is exactly what an unmodified
    right-click on tome 533 does — so the ctrl modifier did not land that
    time. Potions were already excluded for the same reason (an unmodified
    right-click drinks one); tomes belong in the same set. 534 is worse
    than 533: it arms the identify cursor, and every later click identifies."""
    town.inventory = [
        loot(1, (0, 0), kind=offsets.TOME_OF_TOWN_PORTAL),
        loot(2, (1, 0), kind=offsets.TOME_OF_IDENTIFY),
        loot(3, (2, 0), kind=700),  # ordinary junk, and it still goes
    ]
    full_belt(town)
    layer(
        town, keep_item=lambda item: False, protected_ids=lambda: set()
    ).cleanse_inventory(PreambleReport())
    assert [i.kind for i in town.dropped] == [700]


def test_a_failed_drop_abandons_the_cleanse_rather_than_continuing(town):
    """A drop that did not land means the gesture did not do what we asked,
    and the likeliest reason is the modifier not registering — in which case
    every further attempt is an unmodified right-click on an inventory item,
    which USES it. One surprise is recoverable; a sequence is not."""
    town.inventory = [
        loot(1, (0, 0), kind=700),
        loot(2, (1, 0), kind=701),
        loot(3, (2, 0), kind=702),
    ]
    town.drop_works = False
    full_belt(town)
    layer(
        town, keep_item=lambda item: False, protected_ids=lambda: set()
    ).cleanse_inventory(PreambleReport())
    assert town.dropped == []
    assert len(town.alerts) == 1, "one alert, not one per item"
    assert "abandoning the cleanse" in town.alerts[0]


def test_walking_near_steps_back_when_standing_on_the_target(town):
    """Stage B, live: the character ended at (5885, 5710) clicking the
    waypoint at (5884, 5709) — distance 1 — three times and never opened it.

    Clicking a distant object makes the character WALK ONTO it, so an
    interaction that does not take leaves us standing on the thing we are
    trying to click, and a click on your own tile does nothing. Every retry
    then found itself already "close enough" and re-clicked from the same
    hopeless spot: a one-sided range cannot express "step back".
    """
    target = (5884, 5709)
    town.pos = target  # dead on top of it
    layer(town)._walk_near(target, minimum=CALIBRATED.min_interact_range)
    assert town.walked, "standing on the target must produce a walk"
    away = max(
        abs(town.walked[-1][0] - target[0]), abs(town.walked[-1][1] - target[1])
    )
    assert away >= CALIBRATED.min_interact_range


def test_walking_near_still_does_nothing_at_a_sane_distance(town):
    """The other end stays intact: already in range means no walk at all —
    the shortest walk is none."""
    target = (5884, 5709)
    town.pos = (target[0] + 8, target[1])
    layer(town)._walk_near(target, minimum=CALIBRATED.min_interact_range)
    assert town.walked == []


def test_walking_near_without_a_minimum_is_unchanged(town):
    """NPC approaches pass no minimum: you cannot stand inside a unit, and
    the close-range behaviour they rely on must not move."""
    target = (5884, 5709)
    town.pos = target
    layer(town)._walk_near(target)
    assert town.walked == []


# -- the tome misclick and the stash-full misdiagnosis (T70 run 2) ------------


def test_tomes_are_never_right_clicked():
    """A tome's plain right-click USES it (identify cursor, or a town
    portal), and a lost SHIFT turns the transfer gesture into exactly
    that — twice now, on the same item (R112/R113, then T70 run 2). The
    settle made the race rare; this makes the hazard absent, the way the
    Cube's has always been."""
    for kind in (
        offsets.TOME_OF_IDENTIFY_KIND,
        offsets.TOME_OF_TOWN_PORTAL_KIND,
        offsets.CUBE_KIND,
    ):
        assert not loot(1, (0, 0), kind=kind).is_movable


def test_a_tome_is_left_alone_and_never_clicked(town):
    town.inventory = [
        loot(1, (0, 0), kind=offsets.TOME_OF_IDENTIFY_KIND),
        loot(2, (2, 0), kind=522),
    ]
    full_belt(town)
    report = PreambleReport()
    layer(town).manage_inventory(report)
    # The ordinary item stashed; the tome stayed, untouched.
    assert [i.unit_id for i in town.inventory] == [1]
    tome_pixel = cell_pixel((0, 0))
    assert all(
        (c[1], c[2]) != tome_pixel
        for c in town.panel_clicks
        if c[0] == offsets.UI_STASH
    ), "the tome was clicked at all — the one thing that must never happen"


def test_one_stubborn_item_does_not_end_the_run_when_others_stashed(town):
    """The evidence was always there and was never consulted: if other
    items went in, the stash HAS room, so a refusal is about the item.
    Notice and continue (the R208 belt-short policy), never StashFull."""
    town.inventory = [loot(1, (0, 0), kind=522), loot(2, (2, 0), kind=523)]
    town.refuse_kinds = {523}  # one item the game will not take
    full_belt(town)
    report = PreambleReport()

    layer(town).manage_inventory(report)  # must NOT raise

    assert report.deposited == 1
    assert [i.unit_id for i in town.inventory] == [2]
    assert any("carried on" in line for line in report.log)
    assert any(
        "other item(s) did" in a and "stash has room" in a for a in town.alerts
    ), f"the alert must say the stash is not the problem: {town.alerts}"


def test_nothing_deposited_at_all_is_still_a_full_stash(town):
    """The genuine case keeps its loud halt: no evidence of room, so the
    container really is a candidate."""
    town.inventory = [loot(1, (0, 0), kind=522)]
    town.deposit_works = False
    full_belt(town)
    with pytest.raises(StashFull, match="both deposit passes"):
        layer(town).manage_inventory(PreambleReport())
    assert any("NOTHING deposited this visit" in a for a in town.alerts)


def test_a_retry_clears_the_cursor_before_re_clicking(town):
    """A retry that repeats the same click unchanged is not a retry: an
    armed cursor eats every one of them. The second attempt must close
    and reopen the panel first (ESC clears the cursor)."""
    town.inventory = [loot(1, (0, 0), kind=522)]
    town.deposit_works = False
    full_belt(town)
    with pytest.raises(StashFull):
        layer(town).manage_inventory(PreambleReport())
    # The stash chest was clicked more than once: opened, and reopened
    # after the recovery.
    assert town.world_clicks.count(STASH_POS) > 1, (
        "the panel was never reopened, so no retry ever cleared the cursor"
    )


# -- the walk cap: a capped return is not an arrival ---------------------------
#
# 2026-08-07 gave `walk_to` a 2 s wall-clock cap so a blocking walk can no
# longer starve the chicken. Field steps were already built for short
# legs; the TOWN layer crossed town in one call and trusted it to block
# until arrival. Live on 2026-08-08 that was `heal: FAILED after 2.1s` -
# one walk budget - and the bot correctly reported an NPC it had not
# actually walked to yet.


def _capped(target, arrived_at):
    from pd2bot.navigate import WalkResult

    return WalkResult(
        target=target, arrived_at=arrived_at, duration_seconds=2.0,
        waypoints=2, capped=True,
    )


def _arrived(target):
    from pd2bot.navigate import WalkResult

    return WalkResult(
        target=target, arrived_at=target, duration_seconds=1.0, waypoints=2,
    )


def test_town_walks_are_re_issued_until_they_actually_arrive(town):
    """The regression test for the live failure: three capped legs then
    an arrival must be four calls, not one."""
    target = (5922, 5714)
    calls = []

    def walk(pos):
        calls.append(pos)
        if len(calls) < 4:
            return _capped(pos, (5900 + len(calls), 5700))
        return _arrived(pos)

    town_layer = layer(town)
    town_layer.walk_to = walk
    town_layer._walk_all_the_way(target)
    assert len(calls) == 4, f"stopped after {len(calls)} capped leg(s)"


def test_an_uncapped_walk_is_a_single_call(town):
    """The old contract still holds when the walk finishes in one go -
    this must not turn every town walk into a polling loop."""
    calls = []

    def walk(pos):
        calls.append(pos)
        return _arrived(pos)

    town_layer = layer(town)
    town_layer.walk_to = walk
    town_layer._walk_all_the_way((5922, 5714))
    assert len(calls) == 1


def test_a_walker_that_returns_nothing_still_works(town):
    """Drills and older fakes hand back None; `capped` is read defensively
    so a walker with no WalkResult is treated as having arrived."""
    calls = []
    town_layer = layer(town)
    town_layer.walk_to = lambda pos: calls.append(pos)
    town_layer._walk_all_the_way((5922, 5714))
    assert len(calls) == 1


def test_endless_capped_legs_give_up_rather_than_spin(town):
    """The second bound: something that crawls forever without ever quite
    failing must not hold the run open."""
    from pd2bot.town import TownError

    clock = {"now": 0.0}

    def walk(pos):
        clock["now"] += 2.0
        return _capped(pos, (5000, 5000))

    town_layer = layer(town)
    town_layer.walk_to = walk
    town_layer._clock = lambda: clock["now"]
    with pytest.raises(TownError, match="capped legs"):
        town_layer._walk_all_the_way((5922, 5714))
