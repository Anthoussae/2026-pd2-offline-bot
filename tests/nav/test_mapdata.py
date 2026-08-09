"""Decoding d2mapapi replies. The RLE example is the one documented in
d2mapapi_mod's own collisionmap.h (X = collision, . = open):

    [1,5,1,-1,      X.....X
     2,3,2,-1,      XX...XX
     1,5,1,-1]      X.....X
"""

import pytest

from pd2bot.nav.mapdata import MapServiceError, compare_with_live, decode_area_map


def payload(**overrides):
    base = {
        "id": 3,
        "offset": {"x": 5600, "y": 4800},
        "size": {"width": 280, "height": 200},
        "crop": {"x0": 10, "y0": 20, "x1": 17, "y1": 23},
        "mapData": [1, 5, 1, -1, 2, 3, 2, -1, 1, 5, 1, -1],
        "exits": {"4": {"offsets": [{"x": 5610, "y": 4821}], "isPortal": False}},
        "npcs": {},
        "objects": {},
        "pathData": [],
    }
    base.update(overrides)
    return base


def test_decodes_the_documented_example():
    area = decode_area_map(payload())
    assert area.area_id == 3
    assert area.origin == (5610, 4820)  # offset + crop corner
    assert (area.width, area.height) == (7, 3)

    def row(y):
        return "".join(
            "." if area.is_walkable(5610 + x, 4820 + y) else "X" for x in range(7)
        )

    assert row(0) == "X.....X"
    assert row(1) == "XX...XX"
    assert row(2) == "X.....X"


def test_grid_protocol_known_vs_walkable():
    area = decode_area_map(payload())
    assert area.is_known(5610, 4820)
    assert not area.is_walkable(5610, 4820)  # corner X: known but blocked
    assert not area.is_known(5609, 4820)  # left of the crop
    assert not area.is_walkable(5609, 4820)


def test_short_row_padding_is_blocked():
    # A row whose runs cover less than the width: the tail is unknown to the
    # encoder and must decode as non-walkable, never as open ground.
    area = decode_area_map(payload(mapData=[1, 2, -1, 1, 5, 1, -1, 1, 5, 1, -1]))
    assert area.is_walkable(5611, 4820)
    assert not area.is_walkable(5613, 4820)  # beyond the encoded runs
    assert not area.is_walkable(5616, 4820)


def test_overlong_run_is_clamped():
    area = decode_area_map(payload(mapData=[0, 99, -1, 2, 3, 2, -1, 1, 5, 1, -1]))
    assert area.is_walkable(5610, 4820)
    assert area.is_walkable(5616, 4820)
    assert not area.is_walkable(5617, 4820)  # next cell is outside the crop


def test_exits_parsed():
    area = decode_area_map(payload())
    assert area.exits == {4: [(5610, 4821)]}


def test_error_payload_raises():
    with pytest.raises(MapServiceError, match="Invalid map id"):
        decode_area_map({"error": "[d2mapapi_mod v1.3.0] Invalid map id!"})


def test_empty_crop_raises():
    with pytest.raises(MapServiceError, match="empty crop"):
        decode_area_map(payload(crop={"x0": 0, "y0": 0, "x1": 0, "y1": 0}))


class StitchedStub:
    """A fake LocalCollision covering a window with one differing cell."""

    def __init__(self, bounds, wrong=()):
        self._bounds = bounds
        self.wrong = set(wrong)

    @property
    def bounds(self):
        return self._bounds

    def is_known(self, x, y):
        left, top, right, bottom = self._bounds
        return left <= x < right and top <= y < bottom

    def is_walkable(self, x, y):
        # Live truth: everything the generated example calls walkable,
        # except deliberately flipped cells.
        area = decode_area_map(payload())
        truth = area.is_walkable(x, y)
        return not truth if (x, y) in self.wrong else truth


def test_fidelity_comparison_counts_mismatches():
    area = decode_area_map(payload())
    live = StitchedStub(bounds=(5610, 4820, 5617, 4823), wrong={(5612, 4821)})
    compared, mismatched, samples = compare_with_live(area, live)
    assert compared == 21  # full 7x3 overlap
    assert mismatched == 1
    assert samples == [(5612, 4821)]


def test_fidelity_no_overlap():
    area = decode_area_map(payload())
    live = StitchedStub(bounds=(0, 0, 5, 5))
    compared, mismatched, samples = compare_with_live(area, live)
    assert (compared, mismatched, samples) == (0, 0, [])
