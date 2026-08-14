"""Route lines: geometry, thinning, and the store round-trip.

Pure-geometry tests — the leash's world behavior is tested where it is
wired (the step tests); here the math itself must be right, because a
wrong nearest-point silently walks the character somewhere strange.
"""

import math

import pytest

from pd2bot.nav.routeline import RouteLine, load_line, save_line, thin


def line(points, seed=0x4E52715F, difficulty=1, area=2):
    return RouteLine(seed, difficulty, area, [tuple(p) for p in points])


# -- construction --------------------------------------------------------------


def test_a_line_needs_two_points():
    with pytest.raises(ValueError):
        line([(0, 0)])


def test_length_is_the_polyline_arc_length():
    aline = line([(0, 0), (30, 0), (30, 40)])
    assert aline.length == 70.0


# -- stray geometry ------------------------------------------------------------


def test_on_the_line_is_zero_stray():
    stray = line([(0, 0), (100, 0)]).stray_from((50, 0))
    assert stray.distance == 0.0
    assert stray.nearest == (50, 0)
    assert stray.progress == pytest.approx(0.5)


def test_perpendicular_stray_projects_onto_the_segment():
    stray = line([(0, 0), (100, 0)]).stray_from((40, 30))
    assert stray.distance == pytest.approx(30.0)
    assert stray.nearest == (40, 0)


def test_beyond_the_end_clamps_to_the_endpoint():
    stray = line([(0, 0), (100, 0)]).stray_from((140, 30))
    assert stray.nearest == (100, 0)
    assert stray.distance == pytest.approx(50.0)  # 3-4-5
    assert stray.progress == pytest.approx(1.0)


def test_corner_tie_goes_to_the_earlier_segment():
    # Equidistant from both segments of an L — progress must not jump.
    stray = line([(0, 0), (10, 0), (10, 10)]).stray_from((12, -2))
    assert stray.segment == 0


def test_progress_is_monotone_along_a_walk():
    aline = line([(0, 0), (50, 0), (50, 50), (0, 50)])
    walk = [(5, 1), (30, 2), (49, 10), (51, 30), (40, 49), (10, 51)]
    fractions = [aline.stray_from(p).progress for p in walk]
    assert fractions == sorted(fractions)


# -- thinning ------------------------------------------------------------------


def test_thin_collapses_collinear_points():
    dense = [(x, 0) for x in range(0, 101, 5)]
    assert thin(dense) == [(0, 0), (100, 0)]


def test_thin_keeps_a_real_corner():
    pts = [(0, 0), (50, 0), (50, 50)]
    dense = pts[:1] + [(x, 0) for x in range(5, 50, 5)] + pts[1:]
    thinned = thin(dense)
    assert (50, 0) in thinned
    assert thinned[0] == (0, 0) and thinned[-1] == (50, 50)


def test_thin_respects_tolerance():
    wiggle = [(x, (x % 10) // 5) for x in range(0, 100)]  # ±1 wiggle
    assert len(thin(wiggle, tolerance=3.0)) == 2
    assert len(thin(wiggle, tolerance=0.1)) > 2


# -- storage -------------------------------------------------------------------


def test_store_round_trip(tmp_path):
    saved = line([(10, 20), (30, 40), (50, 60)])
    save_line(saved, root=tmp_path)
    loaded = load_line(saved.seed, saved.difficulty, saved.area_id, root=tmp_path)
    assert loaded is not None
    assert loaded.points == saved.points


def test_missing_line_is_none(tmp_path):
    assert load_line(1, 1, 2, root=tmp_path) is None


def test_wrong_seed_is_none(tmp_path):
    saved = line([(0, 0), (10, 10)], seed=0xAAAA)
    save_line(saved, root=tmp_path)
    assert load_line(0xBBBB, 1, 2, root=tmp_path) is None


def test_corrupt_file_is_none_not_a_crash(tmp_path):
    saved = line([(0, 0), (10, 10)])
    path = save_line(saved, root=tmp_path)
    path.write_text("{ not json", encoding="utf-8")
    assert load_line(saved.seed, saved.difficulty, saved.area_id, root=tmp_path) is None


def test_progress_never_needs_math_domain_help():
    # A degenerate repeated-point segment must not divide by zero.
    aline = line([(0, 0), (0, 0), (10, 0)])
    stray = aline.stray_from((5, 5))
    assert math.isfinite(stray.distance)
