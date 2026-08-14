"""T77's report logic: the one-kind-or-many verdict, and honest unknowns.

The drill needs a game; the verdict does not — and the verdict is what
decides the shape of the fix (one registry entry, or a whole set).
"""

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from drills.t77_map_identity import describe  # noqa: E402


@dataclass
class FakeItem:
    unit_id: int
    kind: int
    position: tuple
    quality: int
    sockets: int | None = None

    @property
    def quality_name(self) -> str:
        return {2: "normal", 6: "rare"}.get(self.quality, f"quality_{self.quality}")


CODES = {606: "hp5", 534: "ibk"}


def item(uid, kind, quality=2):
    return FakeItem(unit_id=uid, kind=kind, position=(10, 10), quality=quality)


def test_one_kind_means_one_registry_entry():
    text = "\n".join(describe([item(1, 900), item(2, 900)], CODES))
    assert "DISTINCT KINDS: 1" in text
    assert "a single registry entry" in text


def test_several_kinds_means_the_whole_set():
    text = "\n".join(describe([item(1, 900), item(2, 901), item(3, 902)], CODES))
    assert "DISTINCT KINDS: 3" in text
    assert "the whole set" in text


def test_a_kind_the_code_table_does_not_know_is_named_as_such():
    """R144: a kind with no code is an UNKNOWN, never a guess. Reviewing
    numbers by eye is how six wrong elite armours got approved."""
    text = "\n".join(describe([item(1, 900)], CODES))
    assert "NOT IN THE CODE TABLE" in text
    assert "kinds absent from config/item_codes.toml: [900]" in text
    assert "re-run T42" in text


def test_a_known_kind_shows_its_code():
    text = "\n".join(describe([item(1, 606)], CODES))
    assert "code hp5" in text
    assert "absent from config/item_codes.toml: none" in text


def test_qualities_are_reported_because_maps_may_differ_by_them():
    text = "\n".join(describe([item(1, 900, 2), item(2, 900, 6)], CODES))
    assert "qualities seen: [2, 6]" in text
