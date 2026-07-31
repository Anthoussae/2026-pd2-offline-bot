"""T39's name matcher: forgiving about typing, never about ambiguity.

The drill records an item id against whatever this returns, so a wrong
match writes a wrong id into the vocabulary — the one outcome the whole
pending-ids design exists to prevent. Hence the rule under test: guess
generously between SPELLINGS, never between ITEMS.

Semantics are tested against a FIXED vocabulary rather than the shipped
pending list, which shrinks every time a drill resolves something — the
first version of this file broke the moment T42 filled in the runes, and
a test that fails on progress is testing the wrong thing. One test at the
bottom does still walk the real list, because "every name the user might
type resolves to itself" is a property of that list, not of the matcher.
"""

from drills.t39_item_ids import match_name, normalize
from pd2bot.pickit import load_item_table

# Deliberately mirrors the shapes the real vocabulary contains: a family
# with a shared suffix (runes), a family with a shared prefix (skulls),
# a possessive, and a couple of standalone names.
VOCAB = {
    "el_rune", "eld_rune", "ber_rune",
    "minion_skull", "perfect_skull",
    "liliths_mirror", "trang_ouls_jawbone",
    "shako", "archon_plate", "key_of_terror",
}


def matched(typed, vocab=VOCAB):
    return match_name(typed, vocab)[0]


def candidates(typed, vocab=VOCAB):
    return match_name(typed, vocab)[1]


def test_exact_names_match():
    assert matched("ber_rune") == "ber_rune"
    assert matched("archon_plate") == "archon_plate"


def test_typing_is_forgiving_about_case_and_spacing():
    for typed in ("Ber Rune", "  ber rune  ", "BER   RUNE", "ber-rune"):
        assert matched(typed) == "ber_rune", typed


def test_shorthand_resolves_when_unique():
    assert matched("ber") == "ber_rune"  # suffix omitted
    assert matched("shako") == "shako"
    assert matched("minion") == "minion_skull"


def test_possessives_and_plurals_are_forgiven():
    # The loose tier: every typed word starts a word in the name.
    assert matched("lilith mirror") == "liliths_mirror"
    assert matched("trang oul jawbone") == "trang_ouls_jawbone"


def test_extra_words_still_match_when_unambiguous():
    assert matched("key of terror") == "key_of_terror"


def test_ambiguity_never_guesses():
    # "rune" fits three names and "skull" two: the drill must ask, not
    # pick. Recording a wrong id is the failure this prevents.
    assert matched("rune") is None
    assert set(candidates("rune")) == {"el_rune", "eld_rune", "ber_rune"}
    assert matched("skull") is None
    assert len(candidates("skull")) == 2


def test_an_exact_word_match_outranks_a_loose_one():
    # "el rune" is an exact word-set hit for el_rune; the loose tier must
    # not drag in eld_rune ("el" is a prefix of "eld") and make it
    # ambiguous. Tiers exist precisely so a good match wins outright.
    assert matched("el rune") == "el_rune"


def test_unknown_names_offer_nothing():
    assert matched("nonsense item") is None
    assert candidates("nonsense item") == []


def test_empty_input_is_not_a_match():
    assert matched("") is None
    assert matched("   ") is None


def test_normalize_folds_to_the_vocabulary_convention():
    assert normalize("Larzuk's Puzzlebox") == "larzuk_s_puzzlebox"
    assert normalize("Perfect  Skull") == "perfect_skull"
    assert normalize("!!!") == ""


def test_every_known_name_matches_its_own_readable_form():
    """The list as a human reads it off screen: underscores as spaces.

    Walks the WHOLE vocabulary, resolved and pending alike. T39 only ever
    offers the pending subset, but the property belongs to the names
    themselves — and the vocabulary is fully resolved today, so testing
    only the pending set would test nothing at all.
    """
    table = load_item_table("config/item_ids.toml")
    names = set(table.ids) | set(table.pending)
    assert len(names) > 50, "the vocabulary looks suspiciously small"
    for name in names:
        assert match_name(name.replace("_", " "), names)[0] == name, name
