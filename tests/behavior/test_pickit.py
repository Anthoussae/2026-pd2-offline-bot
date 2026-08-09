"""Pickit v2: the R117 whitelist, the vocabulary, and the two modes.

Rule evaluation is pure, so most of this is truth tables. The parts that
are not — the pending-vocabulary safety and the strict/permissive split —
are the parts a live mistake would make irreversible, so they get the
densest coverage.
"""

from pathlib import Path

import pytest

from pd2bot import offsets
from pd2bot.perception.items import CarriedItem, CarriedItems
from pd2bot.perception.units import GroundItem
from pd2bot.pickit import (
    ItemTable,
    PickitError,
    cleanse_keep,
    load_item_table,
    load_pickit,
)

REPO = Path(__file__).resolve().parents[2]
SHIPPED = REPO / "config" / "pickit.toml"
SHIPPED_TABLE = REPO / "config" / "item_ids.toml"

HEAL, MANA, REJUV = 606, 611, 530
NORMAL, MAGIC, SET, RARE, UNIQUE = 2, 4, 5, 6, 7

# A fully-resolved test vocabulary, so semantics can be tested without the
# shipped file's pending entries getting in the way.
TABLE = ItemTable(
    ids={"widget": (900,), "rune_a": (901,), "plate": (902,), "ring": (903,)},
    pending=frozenset({"mystery"}),
    groups={"widgets": ("widget", "mystery"), "resolved_pair": ("widget", "rune_a")},
)


def item(kind, quality=NORMAL, uid=1, sockets=None):
    return GroundItem(
        unit_id=uid, kind=kind, position=(10, 10), quality=quality,
        sockets=sockets,
    )


def belt_potion(uid, kind, slot):
    return CarriedItem(uid, kind, 2, offsets.ITEM_MODE_IN_BELT, 0,
                       offsets.NODE_BELT, (slot, 0), 1)


def inv_potion(uid, kind, cell):
    return CarriedItem(uid, kind, 2, offsets.ITEM_MODE_IN_STORAGE,
                       offsets.STORAGE_INVENTORY, offsets.NODE_STORAGE, cell, 1)


def carried_with(*, belt=(), inventory=()):
    return CarriedItems(items=tuple(belt) + tuple(inventory), skipped=0)


def full_healing_belt():
    return [belt_potion(100 + i, HEAL, slot) for i, slot in enumerate((2, 3, 6, 7, 10, 11, 14, 15))]


def write(tmp_path, text):
    path = tmp_path / "pickit.toml"
    path.write_text(text, encoding="utf-8")
    return path


def load(tmp_path, text, table=TABLE):
    return load_pickit(write(tmp_path, text), item_table=table)


# -- the shipped files ---------------------------------------------------------


def test_the_shipped_vocabulary_loads_fully_resolved():
    table = load_item_table(SHIPPED_TABLE)
    assert table.ids["healing_606"] == (606,)  # verified entries carry ids
    assert "runes" in table.groups and len(table.groups["runes"]) == 33
    # Nothing pending: T42's code-table join plus the R128 review closed
    # the list, and the craft-only names were retired (they cannot drop,
    # so a pickup rule for them could never fire).
    assert table.pending == frozenset(), sorted(table.pending)


def test_the_shipped_pickit_resolves_every_name_it_uses():
    pickit = load_pickit(SHIPPED)
    assert pickit.pending_names == frozenset(), sorted(pickit.pending_names)
    # Spot-check that names actually carry ids rather than merely loading.
    table = load_item_table(SHIPPED_TABLE)
    assert 674 in table.ids["worldstone_shard"]  # wss
    assert 435 in table.ids["shako"]             # uap


def test_shipped_potion_rules_fire_on_verified_ids():
    pickit = load_pickit(SHIPPED)
    empty = carried_with()
    assert pickit.decide(item(HEAL), empty)[0] == "belt"
    assert pickit.decide(item(MANA), empty)[0] == "belt"
    assert pickit.decide(item(REJUV), empty)[0] == "belt"


def test_shipped_cleanse_is_now_enabled_and_recognises_keepers():
    # The gate opened when the last name resolved. The safety property it
    # enforced is still tested, against a synthetic pending vocabulary, in
    # test_cleanse_disabled_while_names_are_pending below.
    keep = cleanse_keep(load_pickit(SHIPPED))
    assert keep is not None
    table = load_item_table(SHIPPED_TABLE)

    def carried(kind):
        return CarriedItem(1, kind, NORMAL, offsets.ITEM_MODE_IN_STORAGE,
                           offsets.STORAGE_INVENTORY, offsets.NODE_STORAGE,
                           (0, 0), 1)

    assert keep(carried(table.ids["worldstone_shard"][0]))  # a keeper
    assert keep(carried(REJUV))                             # potions always
    assert not keep(carried(4242))                          # unknown = junk


def test_shipped_cleanse_drops_plain_socket_rule_bases():
    """The R132 gap, against the file the bot actually runs.

    `necro_heads` and `archon_plate` appear in the shipped pickit ONLY
    under socket conditions (3, and 3-4). Every one of them used to be
    kept and stashed regardless — the clutter this fix removes.
    """
    keep = cleanse_keep(load_pickit(SHIPPED))
    table = load_item_table(SHIPPED_TABLE)

    def carried(kind, sockets):
        return CarriedItem(1, kind, NORMAL, offsets.ITEM_MODE_IN_STORAGE,
                           offsets.STORAGE_INVENTORY, offsets.NODE_STORAGE,
                           (0, 0), 1, sockets=sockets)

    plate = table.ids["archon_plate"][0]
    assert keep(carried(plate, 3))
    assert keep(carried(plate, 4))
    assert not keep(carried(plate, 0))
    assert not keep(carried(plate, 2))


def test_cleanse_disabled_while_names_are_pending(tmp_path):
    # The invariant that guarded the whole build-out: a whitelist which
    # cannot recognise a keeper must never be allowed to throw one away.
    pickit = load(tmp_path, PENDING_RULE)  # names the pending "mystery"
    assert pickit.pending_names
    assert cleanse_keep(pickit) is None


# -- potion reserve semantics (R118 Q1) ----------------------------------------


POTION_RULES = """
[[rule]]
name = "healing"
kinds = ["healing_potion"]
potion_reserve = 2
action = "belt"
"""


def test_potion_picked_while_the_belt_has_room(tmp_path):
    pickit = load(tmp_path, POTION_RULES)
    short_belt = carried_with(belt=[belt_potion(1, HEAL, 2)])
    assert pickit.decide(item(HEAL), short_belt)[0] == "belt"


def test_potion_picked_for_the_reserve_when_the_belt_is_full(tmp_path):
    pickit = load(tmp_path, POTION_RULES)
    carried = carried_with(
        belt=full_healing_belt(),
        inventory=[inv_potion(200, HEAL, (0, 0))],  # reserve holds 1 of 2
    )
    assert pickit.decide(item(HEAL), carried)[0] == "belt"


def test_potion_skipped_when_belt_and_reserve_are_both_full(tmp_path):
    pickit = load(tmp_path, POTION_RULES)
    carried = carried_with(
        belt=full_healing_belt(),
        inventory=[inv_potion(200, HEAL, (0, 0)), inv_potion(201, HEAL, (1, 0))],
    )
    assert pickit.decide(item(HEAL), carried)[0] == "skip"


def test_reserve_counts_per_type_not_per_kind(tmp_path):
    # Two mana potions of different tiers still fill the mana reserve.
    pickit = load(
        tmp_path,
        '[[rule]]\nname = "mana"\nkinds = ["mana_potion"]\n'
        'potion_reserve = 2\naction = "belt"\n',
    )
    carried = carried_with(
        belt=[belt_potion(100 + i, MANA, slot) for i, slot in enumerate((0, 4, 8, 12))],
        inventory=[inv_potion(200, 610, (0, 0)), inv_potion(201, 611, (1, 0))],
    )
    assert pickit.decide(item(MANA), carried)[0] == "skip"


def test_reserve_without_carried_state_strict_vs_permissive(tmp_path):
    pickit = load(tmp_path, POTION_RULES)
    assert pickit.decide(item(HEAL), None)[0] == "skip"  # cannot verify: no
    assert pickit.decide(item(HEAL), None, mode="permissive")[0] == "belt"


def test_reserve_requires_a_single_potion_type(tmp_path):
    with pytest.raises(PickitError, match="exactly one potion group"):
        load(
            tmp_path,
            '[[rule]]\nname = "x"\nkinds = ["any_potion"]\n'
            'potion_reserve = 2\naction = "belt"\n',
        )


# -- sockets (waits on T38) ----------------------------------------------------


SOCKET_RULE = """
[[rule]]
name = "3-4 socket plate"
kinds = ["plate"]
sockets = [3, 4]
action = "keep"
"""


def test_socket_rule_matches_a_read_count(tmp_path):
    pickit = load(tmp_path, SOCKET_RULE)
    assert pickit.decide(item(902, sockets=3))[0] == "keep"
    assert pickit.decide(item(902, sockets=2))[0] == "skip"


def test_unknown_sockets_strict_refuses_permissive_allows(tmp_path):
    # sockets=None now means only one thing — the stat list did not read —
    # and it stays the conservative case: strict (pickup) must not pick on
    # a guess; permissive (cleanse) must not drop on one. Both mistakes
    # point the same direction, keep.
    pickit = load(tmp_path, SOCKET_RULE)
    unknowable = item(902, sockets=None)
    assert pickit.decide(unknowable)[0] == "skip"
    assert pickit.decide(unknowable, mode="permissive")[0] == "keep"


def inv_item(uid, kind, cell=(0, 0), quality=NORMAL, sockets=None):
    return CarriedItem(
        uid, kind, quality, offsets.ITEM_MODE_IN_STORAGE,
        offsets.STORAGE_INVENTORY, offsets.NODE_STORAGE, cell, 1,
        sockets=sockets,
    )


def test_cleanse_drops_a_carried_item_whose_sockets_read_zero(tmp_path):
    """R132: the one place the cleanse really was too conservative.

    A socket condition cannot be evaluated against a carried item unless
    the item carries its socket count, and permissive mode counts an
    unevaluable condition as satisfied — so before `CarriedItem.sockets`
    existed, EVERY plate matched the 3-4 socket rule and was kept and
    stashed, however many sockets it actually had. Now a zero reads as a
    zero and the rule says what it means.
    """
    keep = cleanse_keep(load(tmp_path, SOCKET_RULE))
    assert keep is not None
    assert keep(inv_item(1, 902, sockets=3))  # wanted: kept
    assert keep(inv_item(2, 902, sockets=4))
    assert not keep(inv_item(3, 902, sockets=0))  # plain: dropped
    assert not keep(inv_item(4, 902, sockets=2))
    # And the read that failed is still kept — unknown is not zero.
    assert keep(inv_item(5, 902, sockets=None))


# -- pending vocabulary --------------------------------------------------------


PENDING_RULE = """
[[rule]]
name = "widgets"
kinds = ["widgets"]
action = "keep"
"""


def test_pending_names_never_match_in_strict_mode(tmp_path):
    pickit = load(tmp_path, PENDING_RULE)
    assert pickit.decide(item(900))[0] == "keep"  # the resolved member
    assert pickit.decide(item(555))[0] == "skip"  # not the pending one either
    assert pickit.pending_names == frozenset({"mystery"})


def test_pending_names_match_anything_in_permissive_mode(tmp_path):
    # An unknown kind MIGHT be the pending item — permissive says keep.
    pickit = load(tmp_path, PENDING_RULE)
    assert pickit.decide(item(555), mode="permissive")[0] == "keep"


def test_cleanse_enabled_once_all_names_resolve(tmp_path):
    pickit = load(
        tmp_path,
        '[[rule]]\nname = "w"\nkinds = ["resolved_pair"]\naction = "keep"\n',
    )
    keep = cleanse_keep(pickit)
    assert keep is not None
    assert keep(inv_potion(1, 900, (0, 0)))  # a widget: kept
    assert not keep(
        CarriedItem(2, 555, NORMAL, offsets.ITEM_MODE_IN_STORAGE,
                    offsets.STORAGE_INVENTORY, offsets.NODE_STORAGE, (1, 0), 1)
    )


def test_cleanse_always_keeps_potions(tmp_path):
    pickit = load(
        tmp_path, '[[rule]]\nname = "w"\nkinds = ["widget"]\naction = "keep"\n'
    )
    keep = cleanse_keep(pickit)
    assert keep(inv_potion(1, REJUV, (0, 0)))  # no rule needed


def test_skip_rules_do_not_hold_the_cleanse_hostage(tmp_path):
    # A skip rule naming pending items is not a reason to disable dropping:
    # nothing it matches would be kept anyway.
    pickit = load(
        tmp_path,
        '[[rule]]\nname = "ignore mystery"\nkinds = ["mystery"]\naction = "skip"\n'
        '[[rule]]\nname = "w"\nkinds = ["widget"]\naction = "keep"\n',
    )
    assert pickit.pending_names == frozenset()
    assert cleanse_keep(pickit) is not None


# -- evaluation semantics ------------------------------------------------------


def test_first_match_wins(tmp_path):
    pickit = load(
        tmp_path,
        '[[rule]]\nname = "everything"\naction = "keep"\n'
        '[[rule]]\nname = "never reached"\nkinds = ["widget"]\naction = "skip"\n',
    )
    assert pickit.decide(item(900)) == ("keep", "everything")


def test_conditions_are_conjunctive(tmp_path):
    pickit = load(
        tmp_path,
        '[[rule]]\nname = "rare widgets"\nkinds = ["widget"]\n'
        'qualities = ["rare"]\naction = "keep"\n',
    )
    assert pickit.decide(item(900, RARE))[0] == "keep"
    assert pickit.decide(item(900, NORMAL))[0] == "skip"
    assert pickit.decide(item(555, RARE))[0] == "skip"


def test_no_match_says_so_rather_than_naming_a_rule(tmp_path):
    pickit = load(
        tmp_path, '[[rule]]\nname = "w"\nkinds = ["widget"]\naction = "keep"\n'
    )
    assert pickit.decide(item(555)) == ("skip", "no rule matched")


# -- strictness ----------------------------------------------------------------


def test_unknown_item_name_fails_loudly(tmp_path):
    with pytest.raises(PickitError, match="wdget"):
        load(tmp_path, '[[rule]]\nname = "x"\nkinds = ["wdget"]\naction = "keep"\n')


def test_unknown_quality_and_action_fail(tmp_path):
    with pytest.raises(PickitError, match="legendary"):
        load(tmp_path, '[[rule]]\nname = "x"\nqualities = ["legendary"]\naction = "keep"\n')
    with pytest.raises(PickitError, match="vendor"):
        load(tmp_path, '[[rule]]\nname = "x"\naction = "vendor"\n')


def test_unknown_rule_key_fails(tmp_path):
    with pytest.raises(PickitError, match="min_defense"):
        load(tmp_path, '[[rule]]\nname = "x"\naction = "keep"\nmin_defense = 4\n')


def test_socket_values_must_be_integers(tmp_path):
    with pytest.raises(PickitError, match="integers"):
        load(
            tmp_path,
            '[[rule]]\nname = "x"\nkinds = ["plate"]\nsockets = ["three"]\n'
            'action = "keep"\n',
        )


def test_vocabulary_rejects_verified_pending_overlap(tmp_path):
    path = tmp_path / "item_ids.toml"
    path.write_text(
        '[verified]\nwidget = 900\n[pending]\nnames = ["widget"]\n',
        encoding="utf-8",
    )
    with pytest.raises(PickitError, match="both verified and pending"):
        load_item_table(path)


def test_vocabulary_rejects_groups_with_unknown_members(tmp_path):
    path = tmp_path / "item_ids.toml"
    path.write_text(
        '[verified]\nwidget = 900\n[groups]\ng = ["widget", "gadget"]\n',
        encoding="utf-8",
    )
    with pytest.raises(PickitError, match="gadget"):
        load_item_table(path)


def test_empty_pickit_fails(tmp_path):
    with pytest.raises(PickitError, match="no \\[\\[rule\\]\\]"):
        load(tmp_path, "\n")


# -- the learned-id sidecar (T39's output) -------------------------------------


BASE_VOCAB = (
    '[verified]\nwidget = 900\n'
    '[pending]\nnames = ["gadget", "gizmo"]\n'
    '[groups]\nthings = ["widget", "gadget"]\n'
)


def vocab(tmp_path, base=BASE_VOCAB, learned=None):
    path = tmp_path / "item_ids.toml"
    path.write_text(base, encoding="utf-8")
    if learned is not None:
        (tmp_path / "item_ids.learned.toml").write_text(learned, encoding="utf-8")
    return path


def test_learned_ids_fill_pending_slots(tmp_path):
    table = load_item_table(
        vocab(tmp_path, learned="[verified]\ngadget = 901 # T39 2026-07-31\n")
    )
    assert table.ids["gadget"] == (901,)
    assert "gadget" not in table.pending
    assert "gizmo" in table.pending  # the un-drilled one stays pending


def test_learned_id_contradicting_the_base_fails(tmp_path):
    with pytest.raises(PickitError, match="contradicts"):
        load_item_table(
            vocab(tmp_path, learned="[verified]\nwidget = 999\n")
        )


def test_learned_id_for_an_unknown_name_fails(tmp_path):
    with pytest.raises(PickitError, match="not a pending name"):
        load_item_table(
            vocab(tmp_path, learned="[verified]\ndoohickey = 950\n")
        )


def test_learned_duplicate_of_the_same_id_is_fine(tmp_path):
    # Re-running the drill re-appends the same discovery; that is not a
    # conflict, it is a confirmation.
    table = load_item_table(
        vocab(tmp_path, learned="[verified]\nwidget = 900\n")
    )
    assert table.ids["widget"] == (900,)


# -- multi-id names (the PD2 duplicate-record problem, R126) ---------------------


def test_a_name_may_bind_to_several_kinds(tmp_path):
    # PD2 carries TWO records for a Hel rune — the classic 'r15' and its
    # own 'r15s' — and it is the second that drops. A name bound to one
    # would silently never match, which is exactly how T39's first item
    # exposed the bug.
    path = tmp_path / "item_ids.toml"
    path.write_text(
        '[verified]\nhel_rune = [639, 713]\n[pending]\nnames = []\n',
        encoding="utf-8",
    )
    table = load_item_table(path)
    assert table.ids["hel_rune"] == (639, 713)

    rules = write(tmp_path, '[[rule]]\nname = "runes"\nkinds = ["hel_rune"]\naction = "keep"\n')
    pickit = load_pickit(rules, item_table=table)
    assert pickit.decide(item(639))[0] == "keep"  # the classic record
    assert pickit.decide(item(713))[0] == "keep"  # the one that drops
    assert pickit.decide(item(640))[0] == "skip"  # a neighbour is not it


def test_the_shipped_vocabulary_binds_both_pd2_variants():
    table = load_item_table(SHIPPED_TABLE)
    # The two ids confirmed live by T39's spot-check.
    assert 713 in table.ids["hel_rune"], table.ids["hel_rune"]
    assert 690 in table.ids["perfect_sapphire"], table.ids["perfect_sapphire"]


def test_an_empty_id_list_is_refused(tmp_path):
    path = tmp_path / "item_ids.toml"
    path.write_text('[verified]\nghost = []\n', encoding="utf-8")
    with pytest.raises(PickitError, match="matches nothing"):
        load_item_table(path)


# -- the vocabulary is anchored to item CODES (R144) -----------------------------


def test_names_resolve_through_item_codes(tmp_path):
    """A name says the D2 code; the id comes from the live-generated table.

    This is the whole redesign. Kinds are renumbered every PD2 season and
    nobody can check one without the game, which is how R128's eyeball pass
    over 53 proposed ids approved SIX wrong elite armours.
    """
    (tmp_path / "item_codes.toml").write_text(
        '[codes]\n442 = "uui"\n445 = "utu"\n452 = "uld"\n', encoding="utf-8"
    )
    (tmp_path / "item_ids.toml").write_text(
        '[codes]\nwire_fleece = "utu"\nkraken_shell = "uld"\n', encoding="utf-8"
    )
    table = load_item_table(tmp_path / "item_ids.toml")
    assert table.ids["wire_fleece"] == (445,)
    assert table.ids["kraken_shell"] == (452,)


def test_a_code_the_game_does_not_have_is_a_loud_error(tmp_path):
    """The failure mode that matters. A typo'd or season-changed code must
    stop the load — silently binding nothing, or guessing, is exactly what
    let a Wire Fleece be picked up as a Kraken Shell."""
    (tmp_path / "item_codes.toml").write_text(
        '[codes]\n442 = "uui"\n', encoding="utf-8"
    )
    (tmp_path / "item_ids.toml").write_text(
        '[codes]\nmystery = "zzz"\n', encoding="utf-8"
    )
    with pytest.raises(PickitError, match="no item in the live game"):
        load_item_table(tmp_path / "item_ids.toml")


def test_a_code_may_bind_several_records(tmp_path):
    """PD2 carries parallel records for some items (R126's r15/r15s), and
    both must bind or the one that actually drops is missed."""
    (tmp_path / "item_codes.toml").write_text(
        '[codes]\n639 = "r15"\n713 = "r15s"\n', encoding="utf-8"
    )
    (tmp_path / "item_ids.toml").write_text(
        '[codes]\nhel_rune = ["r15", "r15s"]\n', encoding="utf-8"
    )
    assert load_item_table(tmp_path / "item_ids.toml").ids["hel_rune"] == (639, 713)


def test_the_shipped_elite_armours_are_the_right_items():
    """The seven R128 got wrong, pinned against the live code table.

    442-456 is a contiguous run of D2's 15 elite body armours in armor.txt
    order, which is what makes these checkable at all.
    """
    from pd2bot.pickit import load_item_codes

    table = load_item_table(SHIPPED_TABLE)
    codes = load_item_codes(SHIPPED_TABLE.with_name("item_codes.toml"))
    for name, code in (
        ("dusk_shroud", "uui"), ("wire_fleece", "utu"), ("balrog_skin", "upl"),
        ("kraken_shell", "uld"), ("shadow_plate", "uul"),
        ("sacred_armor", "uar"), ("archon_plate", "utp"),
    ):
        assert table.ids[name] == codes[code], f"{name} is not {code}"


def test_gold_is_538_not_the_inherited_523():
    """523 is `elx`, an elixir. kolbot's inherited 523 was carried here with
    an "unverified" note for a whole milestone; the code table settled it."""
    from pd2bot.pickit import load_item_codes

    codes = load_item_codes(SHIPPED_TABLE.with_name("item_codes.toml"))
    assert offsets.GOLD_KIND in codes["gld"]
