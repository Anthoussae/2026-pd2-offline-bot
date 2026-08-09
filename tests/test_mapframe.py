"""Coordinate frames: local conversion, screen bearings, honest fallback."""

from pd2bot.mapframe import (
    MapFrame,
    area_name,
    bearing,
    chebyshev,
    describe,
    screen_north,
)
from pd2bot.perception.world import Area

# The real Forgotten Tower numbers — the case this module exists for.
TOWER = Area(level_no=20, position=(2000, 1600), size=(8, 8))  # x5 -> 10000,8000
ARRIVAL = (10006, 8002)
STAIRCASE = (10002, 8013)


def test_the_tower_reads_as_small_numbers_in_its_own_frame():
    frame = MapFrame.from_area(TOWER)
    assert frame.origin == (10000, 8000)
    assert frame.to_local(ARRIVAL) == (6, 2)
    assert frame.to_local(STAIRCASE) == (2, 13)
    assert frame.name == "area-020"


def test_local_and_world_round_trip():
    frame = MapFrame.from_area(TOWER)
    for point in (ARRIVAL, STAIRCASE, (10000, 8000), (10039, 8039)):
        assert frame.to_world(frame.to_local(point)) == point


def test_contains_uses_the_areas_own_bounds():
    frame = MapFrame.from_area(TOWER)
    assert frame.contains(ARRIVAL)
    assert not frame.contains((12515, 5182))  # Cellar 1's arrival


# -- the payload -------------------------------------------------------------


def test_describe_carries_all_three_frames_and_the_distance():
    frame = MapFrame.from_area(TOWER)
    payload = frame.describe(STAIRCASE, player=ARRIVAL)
    assert payload["world"] == [10002, 8013]
    assert payload["local"] == [2, 13]
    assert payload["rel"] == [-4, 11]
    # Chebyshev, the metric the whole codebase compares reaches against:
    # 11 sits inside TraverseStep.click_range (18), which is exactly why
    # T71 never planned a walk in that room.
    assert payload["dist"] == 11
    assert payload["frame"] == "area-020"


def test_describe_omits_the_relative_half_when_there_is_no_player():
    payload = MapFrame.from_area(TOWER).describe(STAIRCASE)
    assert payload["world"] == [10002, 8013]
    assert "rel" not in payload and "dist" not in payload


def test_describe_of_nothing_is_nothing():
    assert MapFrame.from_area(TOWER).describe(None) is None
    assert describe(None) is None


# -- the honest fallback (no invented origins) ---------------------------------


def test_an_unreadable_area_reports_world_coordinates_not_a_guess():
    frame = MapFrame.from_area(None)
    assert frame.name == "world"
    assert not frame.known
    assert frame.to_local(STAIRCASE) == STAIRCASE  # local == world, stated
    assert frame.describe(STAIRCASE)["frame"] == "world"


def test_a_torn_area_read_falls_back_rather_than_raising():
    class Torn:
        level_no = 20

        @property
        def bounds_subtiles(self):
            raise ValueError("torn read")

    assert MapFrame.from_area(Torn()).name == "world"


def test_an_atlas_frame_says_it_came_from_the_atlas():
    class Explored:
        bounds = (10000, 8000, 10040, 8040)

    frame = MapFrame.from_atlas(Explored(), 20)
    assert frame.name == "atlas-020"
    assert frame.to_local(STAIRCASE) == (2, 13)


# -- the screen compass (R219) ---------------------------------------------------


def test_screen_north_is_the_world_minus_minus_diagonal():
    # The convention, asserted rather than commented: D2 renders
    # isometrically (sx = wx-wy, sy = wx+wy), so decreasing BOTH world
    # coordinates moves up the monitor.
    assert bearing((-1, -1)) == "N"
    assert bearing((1, 1)) == "S"
    assert bearing((-1, 0)) == "NW"
    assert bearing((0, -1)) == "NE"
    assert bearing((1, 0)) == "SE"
    assert bearing((0, 1)) == "SW"
    assert bearing((1, -1)) == "E"
    assert bearing((-1, 1)) == "W"


def test_a_zero_delta_has_no_bearing_rather_than_a_made_up_one():
    assert bearing((0, 0)) is None


def test_the_towers_staircase_bears_south_west_of_the_arrival():
    payload = MapFrame.from_area(TOWER).describe(STAIRCASE, player=ARRIVAL)
    assert payload["bearing"] == "SW"


def test_the_countess_staging_advance_runs_south_east():
    # The R219 staging derivation, as a regression: from the derived
    # staging point the advance onto her anchor runs screen-SE.
    assert bearing((12548 - 12531, 11036 - 11036)) == "SE"


# -- screen_north, the single definition -------------------------------------------


def test_screen_north_without_an_oracle_takes_the_full_diagonal():
    assert screen_north((12548, 11036), 25) == (12523, 11011)


def test_screen_north_degrades_to_the_shoulders_then_closer_in():
    # Only the west band is walkable — the real Cellar 5 shape, where
    # strictly-north-outside ground does not exist.
    def walkable(point):
        return point[1] == 11036 and point[0] < 12548

    assert screen_north((12548, 11036), 25, walkable) == (12523, 11036)


def test_screen_north_treats_a_torn_read_as_not_a_wall():
    def torn(point):
        raise RuntimeError("unreadable")

    assert screen_north((100, 100), 25, torn) == (75, 75)


# -- odds and ends -------------------------------------------------------------------


def test_chebyshev_matches_the_codebases_own_metric():
    assert chebyshev(ARRIVAL, STAIRCASE) == 11


def test_area_names_fall_back_honestly():
    assert area_name(20) == "Forgotten Tower"
    assert area_name(9999) == "area 9999"
    assert area_name(None) is None
