"""The item-exception registry: every item whose right-click bites, and the
two gesture-sets derived from it (pickup-reliability P5).

Each member is pinned by its REASON, not just its membership — a refactor
that silently dropped one would reintroduce R112 (a slipped modifier using
a tome/scroll/map instead of moving it)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402

# -- the members, each with the reason the operator report will print ------------


def test_the_cube_is_an_exception_and_is_policy_protected():
    exc = offsets.ITEM_EXCEPTIONS[offsets.CUBE_KIND]
    assert "Horadric Cube" in exc.reason
    assert exc.no_transfer is True
    assert exc.policy is True, "the Cube's R172 always-protected status is data now"


def test_both_tomes_are_exceptions_with_their_own_reasons():
    tp = offsets.ITEM_EXCEPTIONS[offsets.TOME_OF_TOWN_PORTAL_KIND]
    idt = offsets.ITEM_EXCEPTIONS[offsets.TOME_OF_IDENTIFY_KIND]
    assert "Tome of Town Portal" in tp.reason and "portal" in tp.reason
    assert "Tome of Identify" in idt.reason and "identify cursor" in idt.reason
    assert tp.no_transfer and tp.no_drop
    assert idt.no_transfer and idt.no_drop


def test_the_scrolls_are_now_handled_the_gap_the_old_comment_named():
    tp = offsets.ITEM_EXCEPTIONS[offsets.SCROLL_OF_TOWN_PORTAL_KIND]  # 544 tsc
    idt = offsets.ITEM_EXCEPTIONS[offsets.SCROLL_OF_IDENTIFY_KIND]     # 545 isc
    assert "Scroll of Town Portal" in tp.reason
    assert "Scroll of Identify" in idt.reason
    # A junk Scroll of Identify is the one the cleanse actually aims at.
    assert idt.no_drop is True, "the cleanse must never ctrl+right-click a scroll"
    assert tp.no_transfer and idt.no_transfer


def test_maps_resolve_from_the_code_table_by_pattern():
    # T77 read ten off the floor; the whole `t<dd>` family is 30 kinds
    # (737-788). Resolved from the code table, not hardcoded (R144).
    assert len(offsets.MAP_KINDS) >= 30, offsets.MAP_KINDS
    for observed in (737, 740, 741, 743, 746, 747, 748, 750, 775):
        assert observed in offsets.MAP_KINDS, observed
        exc = offsets.ITEM_EXCEPTIONS[observed]
        assert "Map" in exc.reason and exc.no_transfer and exc.no_drop


def test_the_uncoded_map_810_is_carried_explicitly():
    # T77 saw kind 810 on the floor, but it is absent from the T42 code
    # table — carried as an explicit observed member, never guessed away.
    assert offsets.MAP_KIND_UNCODED == 810
    assert 810 in offsets.MAP_KINDS
    assert 810 in offsets.UNMOVABLE_KINDS


# -- the derived sets: equal to before, PLUS the new members ---------------------


def test_unmovable_kinds_is_derived_and_still_holds_the_originals():
    assert offsets.CUBE_KIND in offsets.UNMOVABLE_KINDS
    assert offsets.TOME_OF_TOWN_PORTAL_KIND in offsets.UNMOVABLE_KINDS
    assert offsets.TOME_OF_IDENTIFY_KIND in offsets.UNMOVABLE_KINDS
    # ... plus the new members
    assert offsets.SCROLL_OF_TOWN_PORTAL_KIND in offsets.UNMOVABLE_KINDS
    assert offsets.SCROLL_OF_IDENTIFY_KIND in offsets.UNMOVABLE_KINDS


def test_the_hazard_set_is_unchanged_for_the_old_members():
    # The original hazard set was POTION_KINDS | {tome_tp, tome_id}. The
    # Cube was NOT in it (is_movable catches it first), and must stay out so
    # the derivation reproduces shipped behaviour exactly.
    assert offsets.TOME_OF_TOWN_PORTAL_KIND in offsets.RIGHT_CLICK_HAZARD_KINDS
    assert offsets.TOME_OF_IDENTIFY_KIND in offsets.RIGHT_CLICK_HAZARD_KINDS
    assert offsets.CUBE_KIND not in offsets.RIGHT_CLICK_HAZARD_KINDS
    for potion in offsets.POTION_KINDS:
        assert potion in offsets.RIGHT_CLICK_HAZARD_KINDS


def test_unmovable_reason_reads_from_the_registry():
    assert "Cube" in offsets.unmovable_reason(offsets.CUBE_KIND)
    assert "Scroll of Identify" in offsets.unmovable_reason(545)
    assert "Map" in offsets.unmovable_reason(737)
    # An ordinary item has no special reason — honest fallback, not a guess.
    assert offsets.unmovable_reason(999) == "kind 999"


def test_a_missing_code_table_leaves_maps_unprotected_not_broken():
    # The load is guarded: a bad/absent config yields the empty set, so
    # `import offsets` never dies over a config read — maps just fall back
    # to unprotected (as they were before this phase).
    from pd2bot.offsets import _load_map_kinds

    assert isinstance(_load_map_kinds(), frozenset)
